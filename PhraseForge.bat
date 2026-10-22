@echo off
rem Start PhraseForge from this folder (double-click, or run from any terminal).
cd /d "%~dp0"
set "PY=C:\venvs\phraseforge\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo Python environment not found at C:\venvs\phraseforge
  echo Create it with:
  echo   python -m venv C:\venvs\phraseforge
  echo   C:\venvs\phraseforge\Scripts\python -m pip install PySide6 pytest openpyxl httpx
  pause
  exit /b 1
)
start "" "%PY%" -m phraseforge %*
