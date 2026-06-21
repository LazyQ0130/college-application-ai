@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="

call :find_python
if defined PYTHON_EXE goto start_server

echo Python 3.10 or newer was not found.
echo Downloading and installing Python 3.12.10 from python.org...

set "PYTHON_VERSION=3.12.10"
set "PYTHON_INSTALLER=%TEMP%\snowpeak-python-%PYTHON_VERSION%-installer.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
  "$version = '%PYTHON_VERSION%';" ^
  "$installer = '%PYTHON_INSTALLER%';" ^
  "if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $name = 'python-' + $version + '-arm64.exe' }" ^
  "elseif ([Environment]::Is64BitOperatingSystem) { $name = 'python-' + $version + '-amd64.exe' }" ^
  "else { $name = 'python-' + $version + '.exe' };" ^
  "$url = 'https://www.python.org/ftp/python/' + $version + '/' + $name;" ^
  "Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer;" ^
  "$signature = Get-AuthenticodeSignature -FilePath $installer;" ^
  "if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike '*Python Software Foundation*') { throw 'The Python installer signature is invalid.' };" ^
  "$process = Start-Process -FilePath $installer -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_test=0','Include_launcher=1','InstallLauncherAllUsers=0' -Wait -PassThru;" ^
  "exit $process.ExitCode"

if errorlevel 1 goto install_failed

call :find_python
if not defined PYTHON_EXE goto install_failed

:start_server
echo Starting Snowpeak College Application Assistant...
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8766/'"
"%PYTHON_EXE%" %PYTHON_ARGS% server.py
if errorlevel 1 (
    echo.
    echo The application stopped because of an error.
    pause
)
exit /b

:find_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    exit /b
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    set "PYTHON_ARGS="
    exit /b
)

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
        set "PYTHON_ARGS="
        exit /b
    )
)

if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
    "%LocalAppData%\Programs\Python\Launcher\py.exe" -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Launcher\py.exe"
        set "PYTHON_ARGS=-3"
        exit /b
    )
)
exit /b

:install_failed
echo.
echo Python could not be installed automatically.
echo Check the internet connection, then run this file again.
echo You can also install Python manually from https://www.python.org/downloads/windows/
pause
exit /b 1
