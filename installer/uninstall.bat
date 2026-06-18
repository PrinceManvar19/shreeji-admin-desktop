@echo off
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "INSTALL_DIR=C:\ShreejiAdmin"
set "DESKTOP_SHORTCUT=%PUBLIC%\Desktop\ShreejiAdmin.lnk"
set "START_MENU_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\Shreeji Auto Service"
set "START_MENU_SHORTCUT=%START_MENU_DIR%\ShreejiAdmin.lnk"

if exist "%DESKTOP_SHORTCUT%" del /f /q "%DESKTOP_SHORTCUT%"
if exist "%START_MENU_SHORTCUT%" del /f /q "%START_MENU_SHORTCUT%"
if exist "%START_MENU_DIR%" rmdir "%START_MENU_DIR%" 2>nul
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"

echo Shreeji Auto Service Admin uninstalled successfully.
pause
