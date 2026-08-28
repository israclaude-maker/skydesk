@echo off
echo ===================================
echo   SkyDesk Build Script
echo ===================================

echo.
echo [1/2] Building EXE with PyInstaller...
"C:\Python314\Scripts\pyinstaller.exe" --onefile --windowed --name SkyDesk --icon=SkyDesk.ico ^
  --hidden-import=websocket --hidden-import=websocket._app --hidden-import=websocket._core --collect-all websocket ^
  --hidden-import=pyautogui --hidden-import=pymsgbox --hidden-import=pytweening --hidden-import=pyscreeze --hidden-import=pygetwindow --hidden-import=mouseinfo --collect-all pyautogui ^
  --hidden-import=mss --hidden-import=mss.windows --collect-all mss ^
  --collect-all PIL ^
  --hidden-import=main_window --hidden-import=register_window --hidden-import=screen_share --hidden-import=screen_view --hidden-import=session_store --hidden-import=ws_client --hidden-import=debug_log --hidden-import=config --hidden-import=unlock_client ^
  login_window.py

echo.
echo [1.5/2] Building Unlock Service EXE...
"C:\Python314\Scripts\pyinstaller.exe" --onefile --name SkyDeskUnlock ^
  --hidden-import=win32timezone --hidden-import=win32serviceutil --hidden-import=servicemanager ^
  unlock_service.py

echo.
echo [2/2] Building Installer with Inno Setup...
"C:\Users\skypc\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer_script.iss

echo.
echo ===================================
echo   Build Complete!
echo   Installer is in: installer_output\SkyDeskSetup.exe
echo ===================================
pause