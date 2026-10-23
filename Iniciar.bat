@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto erro_pasta
where py >nul 2>nul
if errorlevel 1 goto tentar_python
py -3 -c "import sys, tkinter; assert sys.version_info >= (3,9)" >nul 2>nul
if errorlevel 1 goto tentar_python
py -3 "%CD%\consulta_pix.py"
if errorlevel 1 goto erro_programa
exit /b 0

:tentar_python
where python >nul 2>nul
if errorlevel 1 goto falta_python
python -c "import sys, tkinter; assert sys.version_info >= (3,9)" >nul 2>nul
if errorlevel 1 goto falta_python
python "%CD%\consulta_pix.py"
if errorlevel 1 goto erro_programa
exit /b 0

:falta_python
echo Instale Python 3.9 ou mais recente com Tcl/Tk em:
echo https://www.python.org/downloads/
echo Marque Add Python to PATH durante a instalacao.
goto falha

:erro_programa
echo Nao foi possivel abrir o programa. Confira a mensagem acima.
goto falha

:erro_pasta
echo Extraia o ZIP para uma pasta local com permissao de gravacao.

:falha
echo.
pause
exit /b 1
