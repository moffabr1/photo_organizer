"""
Properties dialog — shows full metadata for an image or video file.

Sections:
  File        — name, path, size, modified date
  Image/Video — dimensions, format, duration (video), fps, codec
  EXIF        — date taken, camera, lens, exposure, ISO, GPS
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".m4v",
    ".wmv", ".flv", ".webm", ".3gp", ".mts", ".m2ts",
}

_EXIF_TAGS = {
    271:  "Camera make",
    272:  "Camera model",
    305:  "Software",
    36867: "Date taken",
    36868: "Date digitized",
    33434: "Shutter speed",
    33437: "Aperture (f/)",
    34855: "ISO",
    37386: "Focal length (mm)",
    37385: "Flash",
    41986: "Exposure mode",
    41987: "White balance",
    42035: "Lens make",
    42036: "Lens model",
    2:    "GPS latitude",
    4:    "GPS longitude",
}

_SS = """
    QDialog     { background: #1e1e22; color: #d0d0d0; }
    QLabel      { color: #d0d0d0; background: transparent; }
    QScrollArea { border: none; background: #1e1e22; }
    QWidget#inner { background: #1e1e22; }
"""

_SECTION_SS  = "font-size: 12px; font-weight: 600; color: #4a9eff; padding-top: 10px;"
_KEY_SS      = "font-size: 12px; color: #888890; min-width: 140px;"
_VALUE_SS    = "font-size: 12px; color: #d8d8d8; padding-left: 8px;"
_DIVIDER_SS  = "background: #2e2e36; max-height: 1px; margin: 2px 0;"


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_rational(val) -> str:
    """Convert PIL rational tuple or IFDRational to a readable string."""
    try:
        if hasattr(val, "numerator"):
            num, den = val.numerator, val.denominator
        else:
            num, den = val
        if den == 0:
            return str(num)
        if den == 1:
            return str(num)
        result = num / den
        if result < 1:
            return f"1/{round(den/num)}"
        return f"{result:.1f}"
    except Exception:
        return str(val)


def _get_image_date(path: str) -> str:
    """Extract EXIF date taken from an image."""
    try:
        with Image.open(path) as img:
            exif = img._getexif()  # type: ignore
            if exif:
                raw = exif.get(36867) or exif.get(36868) or exif.get(306)
                if raw:
                    # EXIF format: "2024:06:15 14:32:01" → readable
                    raw = str(raw).strip()
                    if len(raw) >= 19:
                        return f"{raw[0:4]}-{raw[5:7]}-{raw[8:10]}  {raw[11:19]}"
                    return raw
    except Exception:
        pass
    return ""


def _get_video_date(path: str) -> str:
    """Extract creation_time from video via ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return ""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", path],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        raw  = tags.get("creation_time") or tags.get("date") or ""
        if raw:
            # ISO format: "2024-06-15T14:32:01.000000Z"
            raw = raw.replace("T", "  ").split(".")[0].replace("Z", "").strip()
            return raw
    except Exception:
        pass
    return ""


def _get_image_meta(path: str) -> dict:
    meta = {}
    try:
        with Image.open(path) as img:
            meta["Dimensions"]  = f"{img.width} × {img.height} px"
            meta["Format"]      = img.format or Path(path).suffix.upper().lstrip(".")
            meta["Color mode"]  = img.mode

            exif_raw = img._getexif()  # type: ignore
            if exif_raw:
                exif = {}
                for tag_id, label in _EXIF_TAGS.items():
                    val = exif_raw.get(tag_id)
                    if val is None:
                        continue
                    if tag_id in (33434,):   # shutter speed — rational
                        exif[label] = f"{_fmt_rational(val)} s"
                    elif tag_id == 33437:    # aperture
                        exif[label] = f"f/{_fmt_rational(val)}"
                    elif tag_id == 37386:    # focal length
                        exif[label] = f"{_fmt_rational(val)} mm"
                    else:
                        exif[label] = str(val)

                # GPS
                gps = exif_raw.get(34853)
                if gps:
                    try:
                        lat_r = gps.get(2)
                        lon_r = gps.get(4)
                        lat_ref = gps.get(1, "N")
                        lon_ref = gps.get(3, "E")
                        if lat_r and lon_r:
                            def to_deg(r):
                                d = float(r[0].numerator) / float(r[0].denominator)
                                m = float(r[1].numerator) / float(r[1].denominator)
                                s = float(r[2].numerator) / float(r[2].denominator)
                                return d + m / 60 + s / 3600
                            lat = to_deg(lat_r) * (-1 if lat_ref == "S" else 1)
                            lon = to_deg(lon_r) * (-1 if lon_ref == "W" else 1)
                            exif["GPS"] = f"{lat:.6f}, {lon:.6f}"
                    except Exception:
                        pass

                meta["__exif__"] = exif
    except Exception as e:
        meta["__error__"] = str(e)
    return meta


def _get_video_meta(path: str) -> dict:
    meta = {}
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        meta["__error__"] = "ffprobe not found (install ffmpeg)"
        return meta
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        fmt  = data.get("format", {})
        streams = data.get("streams", [])

        duration = float(fmt.get("duration", 0))
        if duration:
            m, s = divmod(int(duration), 60)
            h, m = divmod(m, 60)
            meta["Duration"] = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        meta["Bitrate"] = f"{int(fmt.get('bit_rate', 0)) // 1000} kbps"

        for stream in streams:
            codec_type = stream.get("codec_type")
            if codec_type == "video":
                meta["Video codec"]  = stream.get("codec_name", "").upper()
                meta["Dimensions"]   = f"{stream.get('width')} × {stream.get('height')} px"
                r_frame = stream.get("r_frame_rate", "")
                if "/" in r_frame:
                    num, den = r_frame.split("/")
                    if int(den):
                        meta["Frame rate"] = f"{int(num) / int(den):.2f} fps"
                meta["Pixel format"] = stream.get("pix_fmt", "")
            elif codec_type == "audio":
                meta["Audio codec"]    = stream.get("codec_name", "").upper()
                meta["Sample rate"]    = f"{stream.get('sample_rate', '')} Hz"
                meta["Audio channels"] = str(stream.get("channels", ""))

    except Exception as e:
        meta["__error__"] = str(e)
    return meta


class PropertiesDialog(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Properties")
        self.setModal(True)
        self.resize(480, 560)
        self.setStyleSheet(_SS)
        self._path = path
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("inner")
        form  = QVBoxLayout(inner)
        form.setContentsMargins(20, 16, 20, 20)
        form.setSpacing(2)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        path = self._path
        stat = os.stat(path)
        is_video = Path(path).suffix.lower() in VIDEO_EXTENSIONS

        # ── File section ───────────────────────────────────────────────────
        import datetime
        self._section(form, "FILE")
        self._row(form, "Name",     Path(path).name)
        self._row(form, "Location", str(Path(path).parent))
        self._row(form, "Size",     _fmt_size(stat.st_size))

        # Date taken — EXIF for images, ffprobe creation_time for video
        date_taken = ""
        if is_video:
            date_taken = _get_video_date(path)
        else:
            date_taken = _get_image_date(path)

        if date_taken:
            self._row(form, "Date taken", date_taken)
        else:
            self._row(form, "Date taken", "Not available")
        self._row(form, "File modified",
                  datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d  %H:%M:%S"))

        # ── Media section ──────────────────────────────────────────────────
        if is_video:
            self._section(form, "VIDEO")
            vmeta = _get_video_meta(path)
            err = vmeta.pop("__error__", None)
            for k, v in vmeta.items():
                self._row(form, k, v)
            if err:
                self._row(form, "Error", err)
        else:
            self._section(form, "IMAGE")
            imeta = _get_image_meta(path)
            exif  = imeta.pop("__exif__", {})
            err   = imeta.pop("__error__", None)
            for k, v in imeta.items():
                self._row(form, k, v)
            if err:
                self._row(form, "Error", err)

            if exif:
                self._section(form, "EXIF")
                for k, v in exif.items():
                    self._row(form, k, v)

        form.addStretch()

        # ── Close button ───────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.setStyleSheet("""
            QDialogButtonBox QPushButton {
                background: #3a3a3f; border: none; color: #c8c8c8;
                border-radius: 6px; padding: 6px 20px; font-size: 13px;
            }
            QDialogButtonBox QPushButton:hover { background: #4a4a52; }
        """)
        btns.rejected.connect(self.reject)
        root.addWidget(btns, 0, Qt.AlignRight)
        root.setContentsMargins(0, 0, 12, 10)

    def _section(self, layout, title: str):
        lbl = QLabel(title)
        lbl.setStyleSheet(_SECTION_SS)
        layout.addWidget(lbl)
        div = QWidget()
        div.setStyleSheet(_DIVIDER_SS)
        div.setFixedHeight(1)
        layout.addWidget(div)

    def _row(self, layout, key: str, value: str):
        row = QWidget()
        row.setStyleSheet("QWidget { background: transparent; }")
        hl  = __import__("PySide6.QtWidgets", fromlist=["QHBoxLayout"]).QHBoxLayout(row)
        hl.setContentsMargins(0, 3, 0, 3)
        hl.setSpacing(0)

        k = QLabel(key)
        k.setStyleSheet(_KEY_SS)
        k.setFixedWidth(148)
        k.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        v = QLabel(str(value))
        v.setStyleSheet(_VALUE_SS)
        v.setWordWrap(True)
        v.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)

        hl.addWidget(k)
        hl.addWidget(v, 1)
        layout.addWidget(row)