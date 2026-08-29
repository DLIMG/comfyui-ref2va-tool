@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 清空系统代理，避免提交到局域网/虚拟网 ComfyUI 被代理拦截（502）
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=
REM 直连名单：EasyTier 虚拟网、热点网段、本机
set NO_PROXY=192.168.11.0/24;192.168.137.0/24;localhost;127.0.0.1
set no_proxy=192.168.11.0/24;192.168.137.0/24;localhost;127.0.0.1

python start.py
if errorlevel 1 (
  echo.
  echo Startup failed. Please verify Python, FastAPI, Uvicorn and python-multipart are installed.
  pause
)
