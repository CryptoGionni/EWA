@echo off
rem Crea dist\EWA-Setup.exe (vedi README, sezione "Creare l'installer").
python "%~dp0packaging\build.py" %*
if errorlevel 1 (
  echo.
  echo Build non completata.
  exit /b 1
)
