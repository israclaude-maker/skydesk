@echo off
echo ===================================
echo   SkyDesk Build Script
echo ===================================

echo.
echo [1/2] Building EXE with PyInstaller...
call venv\Scripts\activate
pyinstaller --onefile --windowed --name SkyDesk --icon=SkyDesk.ico login_window.py

echo.
echo [2/2] Building Installer with Inno Setup...
"C:\Users\skypc\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_script.iss

echo.
echo ===================================
echo   Build Complete!
echo   Installer is in: installer_output\SkyDeskSetup.exe
echo ===================================
pause