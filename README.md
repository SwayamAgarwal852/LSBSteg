# LSBSteg

LSB-based steganography for images and video (Multimedia & Data Security project).
Full documentation is added in a later step; see `PLAN.md` for the design.

## Installation (Windows)

### 1. Python 3.12 or newer

Python **3.12+** is required (only **3.13.2** has been tested). Older versions cannot
install `requirements.txt`: the pinned numpy 2.5.4 and contourpy 1.4.0 need Python ≥ 3.12.

Check your version:

```powershell
python --version
```

Make sure Tkinter is included (it is by default in the python.org installer):

```powershell
python -c "import tkinter; print(tkinter.TkVersion)"
```

### 2. FFmpeg (needed for video)

```powershell
winget install --id Gyan.FFmpeg -e
```

**After installing FFmpeg, close and reopen your terminal** (and VS Code / any IDE you
run it from). winget adds FFmpeg to `PATH`, but terminals that were already open do not
see the change. Then check:

```powershell
ffmpeg -version
ffprobe -version
```

If you get "not recognized", the terminal has not picked up the new `PATH` yet; restart it
(or sign out and back in).

### 3. Virtual environment and packages

From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. You can also skip activation and
call `.\.venv\Scripts\python.exe` directly.

`requirements.txt` contains the exact versions tested on Python 3.13.2.

### 4. Check the setup

```powershell
.\.venv\Scripts\python.exe -c "import numpy, PIL, matplotlib, pytest, tkinter; print('OK')"
```
