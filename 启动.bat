@echo off
title 雪峰Agent
cd /d "%~dp0"

if not exist ".env" (
    echo .env not found!
    echo Copy .env.example to .env and fill in your API key.
    pause
    exit /b 1
)

:: 自动找 Python：先试 py 启动器，再试 python，最后搜常见路径
set PYEXE=
py --version >nul 2>&1 && set PYEXE=py
if "%PYEXE%"=="" python --version >nul 2>&1 && set PYEXE=python
if "%PYEXE%"=="" if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe" set PYEXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe
if "%PYEXE%"=="" if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe" set PYEXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe
if "%PYEXE%"=="" if exist "C:\Python312\python.exe" set PYEXE=C:\Python312\python.exe
if "%PYEXE%"=="" (
    echo Python not found!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo Python found: %PYEXE%
echo Checking dependencies...
%PYEXE% -c "import openai" 2>nul
if errorlevel 1 (
    echo Installing required packages...
    %PYEXE% -m pip install openai pywin32 -q
    echo Done.
)

echo Starting...
%PYEXE% agent.py
echo.
pause
