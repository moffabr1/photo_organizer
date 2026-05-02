"""
Photo Organizer — entry point.
"""
import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.database import PhotoDB
from app.ui.main_window import MainWindow


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.json"
    defaults = {
        "thumbnail_cache": "~/.cache/photo_app/thumbs",
        "db_path":         "~/.local/share/photo_app/photos.db",
    }
    if config_path.exists():
        try:
            with open(config_path) as f:
                return {**defaults, **json.load(f)}
        except Exception:
            pass
    return defaults


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Photo Organizer")
    app.setStyle("Fusion")

    config  = load_config()
    db_path = str(Path(config["db_path"]).expanduser())
    db      = PhotoDB(db_path)

    window = MainWindow(db, config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()