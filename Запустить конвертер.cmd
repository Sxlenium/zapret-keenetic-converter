@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Python\bin\python.exe"
    goto run_python_exe
)

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
    goto run_python_exe
)

where py.exe >nul 2>nul
if not errorlevel 1 goto run_py

where python.exe >nul 2>nul
if not errorlevel 1 goto run_python

goto python_not_found

:run_python_exe
"%PYTHON_EXE%" -m zapret_keenetic.gui
if not errorlevel 1 exit /b 0
goto launch_failed

:run_py
py.exe -3 -m zapret_keenetic.gui
if not errorlevel 1 exit /b 0
where python.exe >nul 2>nul
if not errorlevel 1 goto run_python
goto launch_failed

:run_python
python.exe -m zapret_keenetic.gui
if not errorlevel 1 exit /b 0
goto launch_failed

:python_not_found
echo.
echo Python 3.9 or newer was not found.
echo Install Python from https://www.python.org/downloads/
echo Enable the "Add Python to PATH" option during installation.
echo.
pause
exit /b 1

:launch_failed
echo.
echo The converter could not be started. See the Python error above.
echo.
pause
exit /b 1
