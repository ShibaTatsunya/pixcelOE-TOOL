@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title pixcelOE - 图片转像素图

echo ================================================================
echo   pixcelOE - 把插画转成像素图
echo ================================================================
echo.

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  if exist "C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" (
    set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
  )
)
if not defined PY (
  echo [错误] 没找到 Python。请先安装 Python 3.9+ 并勾选 "Add to PATH"。
  echo        下载：https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

"%PY%" -c "import numpy, PIL" >nul 2>nul
if errorlevel 1 (
  echo [提示] 缺少 numpy / Pillow，正在自动安装...
  "%PY%" -m pip install --quiet numpy pillow
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请手动执行：  "%PY%" -m pip install numpy pillow
    echo.
    pause
    exit /b 1
  )
)

echo 正在启动，浏览器会自动打开 http://127.0.0.1:8760
echo 用完直接关掉这个黑窗口即可。
echo.
"%PY%" app.py
echo.
echo 服务已停止。
pause
