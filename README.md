# Feynman Diagram Studio

A lightweight, native desktop editor for drawing publication-ready Feynman diagrams. It uses operating-system GUI controls and a native canvas—there is no browser, embedded web server, Electron runtime, or webview.

## Features

- Native GUI for macOS, Windows, and Linux
- Fermion, photon, gluon, scalar, and ghost propagators
- Straight, curved, self-loop, and two-vertex circular paths
- Forward/reverse arrows and one-, two-, or three-line quark bundles
- Open, filled, hatched, crosshatched, dotted, and standard interaction vertices
- Drag vertices and labels; grid snapping; keyboard nudging
- Undo/redo history and local crash-recovery autosave
- Four starting templates and editable JSON project files
- Vector SVG/PDF export and PNG/JPEG export at 300, 600, or 1200 ppi
- LaTeX export for TikZ-Feynman, TikZ-FeynHand, feynMP, feynMF, PST-Feyn, and axodraw2

## Run from source

Python 3.10 or newer and Tk 8.6+ are required. Downloadable release apps bundle their own runtime and do not require Python.

### macOS

Apple’s `/usr/bin/python3` is not compatible: it ships old `pip` and obsolete Tk 8.5. Install the current **macOS installer** from [python.org](https://www.python.org/downloads/macos/) first. Then open a new Terminal window and run:

```bash
cd "/path/to/Feynman Diagram Studio"
python3.14 -c 'import sys, tkinter; print(sys.executable, sys.version.split()[0], "Tk", tkinter.TkVersion)'
python3.14 -m venv --clear .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m feynman_studio
```

The first command should report Python 3.14 and Tk 8.6 or newer. If the installer exposes `python3` rather than `python3.14`, use `python3` in the first two commands.

### Windows and Linux

Tk is included with the standard Windows installer. On Debian/Ubuntu, install `python3-tk` first.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m feynman_studio
```

Pillow handles PNG/JPEG encoding and ReportLab writes vector PDF pages. The editor, SVG renderer, and LaTeX exporters otherwise use the Python standard library.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `V` | Select |
| `A` | Add vertex |
| `C` | Connect vertices |
| `L` | Add loop |
| `Ctrl/Cmd+Z` | Undo |
| `Ctrl/Cmd+Shift+Z` | Redo |
| `Delete` | Delete selection |
| Arrow keys | Nudge selected vertex |
| Shift + arrow keys | Nudge by 10 units |

## Build distributable apps

```bash
python -m pip install -e '.[dev]'
pyinstaller --noconfirm --clean --onefile --windowed --name FeynmanDiagramStudio run_feynman_studio.py
```

The GitHub Actions workflow builds ready-to-run artifacts for all three operating systems. Release builds should be code-signed (and notarized on macOS) before public distribution so users do not see platform security warnings.

## Tests

```bash
python -m unittest discover -s tests -v
```

The headless test suite covers project compatibility and validation, all propagator geometry, loops, marker and line rendering, SVG safety, and all six LaTeX exporters.

## License

MIT. See [LICENSE](LICENSE).
