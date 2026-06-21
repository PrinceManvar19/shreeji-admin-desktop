@echo off
setlocal

pyinstaller ShreejiAdmin.spec --clean
if %errorlevel% neq 0 (
    echo Build failed.
    pause
    exit /b 1
)

if not exist "installer" mkdir "installer"
if exist "installer\ShreejiAdmin" rmdir /s /q "installer\ShreejiAdmin"
mkdir "installer\ShreejiAdmin"

robocopy "dist\ShreejiAdmin" "installer\ShreejiAdmin" /E >nul
if %errorlevel% geq 8 (
    echo Failed to copy built files into installer folder.
    pause
    exit /b 1
)

if exist ".env" (
    copy /Y ".env" "installer\ShreejiAdmin\.env" >nul
) else (
    echo WARNING: .env not found. Copy it into installer\ShreejiAdmin before sharing.
)

if exist "ShreejiAdmin_Release.zip" del /f /q "ShreejiAdmin_Release.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'installer' -DestinationPath 'ShreejiAdmin_Release.zip' -Force"
if %errorlevel% neq 0 (
    echo Failed to create ShreejiAdmin_Release.zip.
    pause
    exit /b 1
)

echo Build complete. Share ShreejiAdmin_Release.zip with the client.
pause
