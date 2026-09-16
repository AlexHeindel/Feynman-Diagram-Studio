# Feynman Diagram Studio

A lightweight, native desktop editor for drawing publication-ready Feynman diagrams. It uses operating-system GUI controls and a native canvas.

![Feynman Diagram Studio editing a kaon decay diagram](docs/images/feynman-diagram-studio.png)

## Features

- Native GUI for macOS, Windows, and Linux
- Fermion, photon, gluon, scalar, and ghost propagators
- Straight, curved, self-loop, and two-vertex circular paths
- Forward/reverse arrows and one-, two-, or three-line quark bundles
- Open, filled, hatched, crosshatched, dotted, and standard interaction vertices
- Antialiased, high-resolution canvas preview
- Drag vertices and labels; consistent 20-unit grid snapping; keyboard nudging
- Undo/redo history and local crash-recovery autosave
- Ten starting templates and editable JSON project files
- Vector SVG/PDF export and PNG/JPEG export at 300, 600, or 1200 ppi
- LaTeX export for TikZ-Feynman, TikZ-FeynHand, feynMP, feynMF, PST-Feyn, and axodraw2

## Install and run

### Packaged app

Packaged builds include Python and the application dependencies, so no separate runtime is required. When a packaged build is available, download it for your operating system from the project's [GitHub Releases](https://github.com/AlexHeindel/Feynman-Diagram-Studio/releases) page, then follow the matching instructions. If no packaged build is listed yet, use the source installation below.

#### macOS

1. Unzip the macOS download.
2. Drag `FeynmanDiagramStudio.app` into `Applications`.
3. Open **FeynmanDiagramStudio** from Applications.

If macOS reports that the app is from an unidentified developer, Control-click the app, choose **Open**, and confirm **Open**. Release builds should be signed and notarized before general distribution.

#### Windows

1. Unzip the Windows download.
2. Move `FeynmanDiagramStudio.exe` to a convenient folder.
3. Double-click `FeynmanDiagramStudio.exe` to run it.

Windows SmartScreen may warn about an unsigned development build. Only choose **More info → Run anyway** when the file came from this repository's official release page.

#### Linux

1. Extract the Linux download.
2. Open a terminal in the extracted folder and make the app executable:

   ```bash
   chmod +x FeynmanDiagramStudio
   ```

3. Run it:

   ```bash
   ./FeynmanDiagramStudio
   ```

You can optionally move the executable to a directory on your `PATH`, such as `~/.local/bin`.

### Run from source

Running from source requires Python 3.10 or newer and Tk 8.6+. Clone the repository (or download and extract its source ZIP), then open a terminal in the project folder:

```bash
git clone https://github.com/AlexHeindel/Feynman-Diagram-Studio.git
cd Feynman-Diagram-Studio
```

Continue with the instructions for your operating system.

#### macOS

Apple’s `/usr/bin/python3` is not compatible: it ships old `pip` and obsolete Tk 8.5. Install the current **macOS installer** from [python.org](https://www.python.org/downloads/macos/) first. Then open a new Terminal window and run:

```bash
python3.14 -c 'import sys, tkinter; print(sys.executable, sys.version.split()[0], "Tk", tkinter.TkVersion)'
python3.14 -m venv --clear .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m feynman_studio
```

The first command should report Python 3.14 and Tk 8.6 or newer. If the installer exposes `python3` rather than `python3.14`, use `python3` in the first two commands.

#### Windows

Install the current 64-bit Python from [python.org](https://www.python.org/downloads/windows/). Leave **Install Tcl/Tk and IDLE** enabled in the installer. In PowerShell, run:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m feynman_studio
```

If PowerShell blocks the activation script, use Command Prompt instead and activate with `.venv\Scripts\activate.bat`, then run the final three `python` commands above.

#### Linux

On Debian or Ubuntu, install Python, virtual-environment support, and Tk first:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e .
python -m feynman_studio
```

For Fedora, use `sudo dnf install python3 python3-tkinter`; for Arch Linux, use `sudo pacman -S python tk` before creating the virtual environment.

### Run again later

For a packaged app, open the `.app` or `.exe`, or run the Linux executable as described above. For a source installation, return to the repository and reactivate its virtual environment before starting the editor:

```bash
# macOS or Linux
source .venv/bin/activate
python -m feynman_studio
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
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
| Shift + arrow keys | Nudge farther (two grid steps while snapping) |

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
