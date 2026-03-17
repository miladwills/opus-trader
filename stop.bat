@echo off
echo 🛑 Shutting down ALL Bybit Control Center components...

:: Kill all running python processes (Server, Runner, etc.)
taskkill /F /IM python.exe /T >nul 2>&1

echo ✅ Python processes stopped.
echo 👋 Closing all CMD windows...

:: Kill all CMD windows. This will also close this script's window.
taskkill /F /IM cmd.exe >nul 2>&1
