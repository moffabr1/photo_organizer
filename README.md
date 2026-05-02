# Photo Organizer

A fast, lightweight desktop photo and video organizer for Linux. Point it at any combination of local folders, NAS shares, or external drives and browse everything in a single unified thumbnail grid — without moving, copying, or importing any files.

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![PySide6](https://img.shields.io/badge/UI-PySide6-brightgreen.svg)

---

## What it is

Most photo apps want to own your files — they import everything into a private library, duplicate originals, and hide the folder structure. This app doesn't. It indexes where your files already are and shows them to you. Your files stay exactly where they are.

It's fast. The thumbnail grid never blocks the UI. It handles libraries of 100,000+ images by loading only what's visible and caching aggressively to disk.

---

## Features

- Browse photos and videos from multiple folders in one grid
- Async thumbnail loading with persistent disk cache
- Video support with thumbnail extraction via ffmpeg
- Tags and albums (stored in SQLite, no file changes)
- Multi-select with Ctrl+click — tag or delete batches at once
- Full-size preview with keyboard navigation
- Basic image enhancement — brightness, contrast, saturation, sharpness
- Right-click file operations — rotate, rename, move, delete
- Desktop shortcut installer with app icon

---

## Requirements

- Linux (tested on Ubuntu 24.04)
- Python 3.10 or newer
- ffmpeg — for video thumbnails (`sudo apt install ffmpeg`)

---

## Quick start

```bash
git clone git@github.com:moffabr1/photo_organizer.git
cd photo_organizer
sudo apt install ffmpeg        # optional, for video thumbnails
bash setup.sh                  # creates venv, installs dependencies
source venv/bin/activate
python main.py
```

To add a desktop shortcut:

```bash
bash install/install_shortcut.sh
```

---

## How it works

### Setup

`setup.sh` creates a Python virtual environment in `venv/` and installs two dependencies: PySide6 (Qt6 UI) and Pillow (image processing). Nothing is installed system-wide.

### Adding folders

Click **＋ Add Folder** in the sidebar. The app scans the folder and all subfolders in a background thread — the UI stays responsive. Thumbnails appear as they generate.

### Thumbnails

On first view, thumbnails are generated asynchronously (up to 4 at a time) and cached to disk at `~/.cache/photo_app/thumbs/`. On subsequent runs they load from cache instantly. The cache can be deleted at any time — it regenerates automatically.

### Database

Sources, tags, albums, and image metadata are stored in a SQLite database at `~/.local/share/photo_app/photos.db`. No image data is stored — only file paths and metadata. If you delete a source folder, you can remove it from the sidebar and the index entries are cleaned up.

---

## Project structure

```
photo_organizer/
├── main.py                  # Entry point
├── setup.sh                 # Venv + dependency setup
├── requirements.txt         # PySide6, Pillow
├── config.json              # Cache and database paths
├── app/
│   ├── database.py          # SQLite — sources, images, tags, albums
│   ├── scanner.py           # Background folder scanner (QThread)
│   ├── thumbnailer.py       # Async thumbnail generator (QThreadPool)
│   └── ui/
│       ├── main_window.py   # Main window and orchestration
│       ├── sidebar.py       # Sources / Albums / Tags panel
│       ├── grid_view.py     # Thumbnail grid (model/view/delegate)
│       └── preview_window.py # Full-size preview + enhancement
└── install/
    ├── icon.svg / *.png     # App icon at multiple sizes
    └── install_shortcut.sh  # Installs .desktop entry and icons
```

---

## Configuration

`config.json` controls where data is stored:

```json
{
  "thumbnail_cache": "~/.cache/photo_app/thumbs",
  "db_path": "~/.local/share/photo_app/photos.db"
}
```

---

## Supported formats

**Images:** `.jpg` `.jpeg` `.png` `.webp` `.tiff` `.tif` `.bmp` `.gif`

**Video:** `.mp4` `.mov` `.avi` `.mkv` `.m4v` `.wmv` `.flv` `.webm` `.3gp` `.mts` `.m2ts`

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+click | Add to selection |
| Delete / Backspace | Delete selected (with confirmation) |
| ← → | Navigate in preview |
| Escape | Close preview |

---

## Tested on

| Component | Version |
|---|---|
| OS | Ubuntu 24.04 |
| Python | 3.12 |
| PySide6 | 6.11.0 |
| Pillow | 12.2.0 |

---

## Contributing

Contributions are welcome. Please follow this workflow:

### 1. Fork and clone

```bash
git clone git@github.com:YOUR_USERNAME/photo_organizer.git
cd photo_organizer
```

### 2. Create a branch

Use a descriptive name:

```bash
git checkout -b feature/add-crop-tool
git checkout -b fix/thumbnail-cache-bug
git checkout -b docs/update-readme
```

### 3. Set up your dev environment

```bash
bash setup.sh
source venv/bin/activate
python main.py
```

### 4. Make your changes

- Keep changes focused — one feature or fix per PR
- Test manually before submitting
- If you're fixing a bug, describe how to reproduce it in the PR

### 5. Push and open a pull request

```bash
git add .
git commit -m "Brief description of what changed and why"
git push origin feature/your-branch-name
```

Then open a PR against the `main` branch on GitHub. Describe what you changed, why, and how you tested it.

### Guidelines

- Open an issue before starting significant work so we can discuss the approach first
- Do not commit `venv/`, `*.db`, or the thumbnail cache — these are gitignored
- Do not commit personal config changes to `config.json`
- Keep the no-import-library philosophy intact — the filesystem stays the source of truth

---

## License

MIT — see [LICENSE](LICENSE).
