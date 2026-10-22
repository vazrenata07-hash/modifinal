@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys, tkinter; assert sys.version_info >= (3,9)" >nul 2>nul
    if not errorlevel 1 (
        py -3 consulta_pix.py
        if errorlevel 1 pause
        exit /b
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys, tkinter; assert sys.version_info >= (3,9)" >nul 2>nul
    if not errorlevel 1 (
        python consulta_pix.py
        if errorlevel 1 pause
        exit /b
    )
)
echo.
echo Instale o Python 3.9 ou mais recente com Tcl/Tk em:
echo https://www.python.org/downloads/
echo Na instalacao, marque "Add Python to PATH".
echo Depois, abra este arquivo novamente.
echo.
pause
