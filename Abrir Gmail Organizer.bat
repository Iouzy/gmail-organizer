@echo off
REM Duplo-clique neste ficheiro para abrir o Gmail Organizer.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Nao encontrei o Python. Instala-o em https://www.python.org/downloads/
  echo Marca a opcao "Add Python to PATH" durante a instalacao.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo Primeira utilizacao: a preparar o ambiente ^(demora um minuto^)...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
  echo Pronto.
)

echo A abrir o Gmail Organizer no browser...
echo Fecha esta janela quando acabares.
".venv\Scripts\python.exe" -m gmail_organizer ui %*
