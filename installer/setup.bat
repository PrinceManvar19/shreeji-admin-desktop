@echo off
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "SOURCE_DIR=%~dp0ShreejiAdmin"
set "INSTALL_DIR=C:\ShreejiAdmin"
set "DESKTOP_SHORTCUT=%PUBLIC%\Desktop\ShreejiAdmin.lnk"
set "START_MENU_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\Shreeji Auto Service"
set "START_MENU_SHORTCUT=%START_MENU_DIR%\ShreejiAdmin.lnk"

if not exist "%SOURCE_DIR%\ShreejiAdmin.exe" (
    echo ERROR: ShreejiAdmin.exe was not found in "%SOURCE_DIR%".
    echo Make sure the installer folder includes the ShreejiAdmin folder.
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
robocopy "%SOURCE_DIR%" "%INSTALL_DIR%" /MIR >nul
if %errorlevel% geq 8 (
    echo ERROR: Failed to copy application files.
    pause
    exit /b 1
)

if not exist "%START_MENU_DIR%" mkdir "%START_MENU_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut('%DESKTOP_SHORTCUT%'); $s.TargetPath='%INSTALL_DIR%\ShreejiAdmin.exe'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.IconLocation='%INSTALL_DIR%\ShreejiAdmin.exe'; $s.Save(); $s=$w.CreateShortcut('%START_MENU_SHORTCUT%'); $s.TargetPath='%INSTALL_DIR%\ShreejiAdmin.exe'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.IconLocation='%INSTALL_DIR%\ShreejiAdmin.exe'; $s.Save()"

echo Shreeji Auto Service Admin installed successfully!
pause
