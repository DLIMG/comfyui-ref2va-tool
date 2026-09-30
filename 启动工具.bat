@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Clear proxy variables so LAN ComfyUI requests are not intercepted.
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=
REM Bypass proxies for EasyTier, hotspot networks and localhost.
set NO_PROXY=192.168.11.0/24;192.168.137.0/24;localhost;127.0.0.1
set no_proxy=192.168.11.0/24;192.168.137.0/24;localhost;127.0.0.1

python start.py
if errorlevel 1 (
  echo.
  echo Startup failed. Please verify Python, FastAPI, Uvicorn and python-multipart are installed.
  pause
)
