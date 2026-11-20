# Development setup (Windows)

This folder is the live, editable source for RAM Model and a git working copy of
https://github.com/EIEng-enginering/ram.

## First-time setup

```powershell
cd "C:\Users\Admin\OneDrive - Enhance Integration Engineering\Company\006 Calculation Methods\30 RAM\ram"
.\setup.ps1      # creates the venv and installs RAM Model in editable mode (pip install -e .)
.\run.ps1        # starts the desktop app
```

The virtual environment is kept **outside OneDrive** at `%LOCALAPPDATA%\rammodel\venv`.
PySide6 contains paths longer than Windows' 260-character limit when placed in this
OneDrive folder, and syncing thousands of library files is slow. Override the location
with the `RAM_VENV` environment variable if needed. Because the install is editable,
changes under `src\rammodel` take effect the next time you start the app.

## Tests

```powershell
& "$env:LOCALAPPDATA\rammodel\venv\Scripts\python.exe" -B tools\run_tests.py
```

## ChatGPT (AI workspace)

AI is off by default. The cloud provider reads the `OPENAI_API_KEY` user environment
variable (set with `setx`; open a new terminal afterwards). In the app choose the
**cloud** provider and enter a model ID such as `gpt-4.1-mini`, `gpt-4.1` or `gpt-4o`.
Never commit the key; it is not stored in cases, reports or this repository.
