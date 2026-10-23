@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Gerar Consultar Pix EXE
cd /d "%~dp0"
if errorlevel 1 goto erro_pasta

echo.
echo GERAR CONSULTAR PIX EXE
echo Feche o ConsultarPix.exe antes de gerar novamente.
echo Na primeira vez, e preciso internet para baixar o PyInstaller.
echo.

if not exist "consulta_pix.py" goto falta_programa
if not exist "lista_pix.py" goto falta_programa
set "PIX_BUILD_DIR=%CD%\.gerador-exe"
set "PIX_BUILD_PY=%PIX_BUILD_DIR%\Scripts\python.exe"
if exist "%PIX_BUILD_PY%" goto preparar_pacotes

where py >nul 2>nul
if errorlevel 1 goto tentar_python
py -3 -c "import sys, tkinter, venv; assert sys.version_info >= (3, 9)" >nul 2>nul
if errorlevel 1 goto tentar_python
py -3 -m venv "%PIX_BUILD_DIR%"
if errorlevel 1 goto erro_ambiente
goto preparar_pacotes

:tentar_python
where python >nul 2>nul
if errorlevel 1 goto falta_python
python -c "import sys, tkinter, venv; assert sys.version_info >= (3, 9)" >nul 2>nul
if errorlevel 1 goto falta_python
python -m venv "%PIX_BUILD_DIR%"
if errorlevel 1 goto erro_ambiente

:preparar_pacotes
"%PIX_BUILD_PY%" -c "import sys, tkinter; assert sys.version_info >= (3, 9)" >nul 2>nul
if errorlevel 1 goto erro_ambiente
"%PIX_BUILD_PY%" -c "import PyInstaller; assert int(PyInstaller.__version__.split('.')[0]) >= 6" >nul 2>nul
if not errorlevel 1 goto gerar
echo Instalando o gerador. Aguarde...
"%PIX_BUILD_PY%" -m pip --disable-pip-version-check install --no-input "pyinstaller>=6,<7"
if errorlevel 1 goto erro_instalacao

:gerar
echo.
echo Gerando o executavel. Aguarde...
"%PIX_BUILD_PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --hidden-import lista_pix --name ConsultarPix --distpath "%CD%" --workpath "%PIX_BUILD_DIR%\build" --specpath "%PIX_BUILD_DIR%" "consulta_pix.py"
if errorlevel 1 goto erro_geracao
if not exist "ConsultarPix.exe" goto erro_geracao
echo.
echo PRONTO! O executavel foi criado nesta pasta:
echo "%CD%\ConsultarPix.exe"
echo Agora voce pode abrir ConsultarPix.exe com dois cliques.
echo O computador que usar esse EXE nao precisa ter Python instalado.
echo.
pause
exit /b 0

:falta_programa
echo ERRO: faltam consulta_pix.py ou lista_pix.py nesta pasta.
echo Extraia todos os arquivos do ConsultaPix.zip e abra Gerar_EXE.bat novamente.
goto falha

:falta_python
echo ERRO: instale Python 3.9 ou superior com Tcl/Tk:
echo https://www.python.org/downloads/
echo Marque Add Python to PATH durante a instalacao.
echo Depois abra Gerar_EXE.bat novamente.
goto falha

:erro_ambiente
echo ERRO: nao foi possivel preparar o Python do gerador.
echo Confira a instalacao do Python e a permissao de escrita nesta pasta.
echo Se a pasta .gerador-exe estiver incompleta, remova somente essa pasta e tente novamente.
goto falha

:erro_instalacao
echo ERRO: nao foi possivel instalar o PyInstaller.
echo Confira a internet e a mensagem acima, depois abra Gerar_EXE.bat novamente.
goto falha

:erro_geracao
echo ERRO: nao foi possivel gerar o executavel.
echo Feche ConsultarPix.exe, confira a mensagem acima e tente novamente.
goto falha

:erro_pasta
echo ERRO: nao foi possivel acessar a pasta do programa.
echo Extraia o ZIP para uma pasta local em que voce tenha permissao de escrita.

:falha
echo.
pause
exit /b 1
