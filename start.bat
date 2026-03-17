@echo off
echo ========================================
echo   Bybit Futures Control Center
echo ========================================
echo.

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

:: Create storage directory if it doesn't exist
if not exist "storage" mkdir storage

echo Starting Flask app on http://localhost:8000 ...
start "Bybit Control Center - Web" cmd /k "python app.py"

:: Wait a moment for Flask to start
timeout /t 2 /nobreak >nul

echo Starting Grid Bot Runner...
start "Bybit Control Center - Runner" cmd /k "python runner.py"

echo.
echo ========================================
echo   Bybit Control Center is now RUNNING!
echo   
echo   Web Dashboard: http://localhost:8000
echo   (No login required for local access)
echo ========================================
echo.

:: Wait for services to fully initialize before opening browser
echo Finalizing startup...
timeout /t 3 /nobreak >nul

:: Open the dashboard in the default browser
echo Opening dashboard...
start http://localhost:8000

echo.
echo Press any key to exit this window...
echo (The services will continue running)
pause >nul

