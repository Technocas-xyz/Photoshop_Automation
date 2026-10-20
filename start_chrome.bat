@echo off
REM ==========================================================================
REM start_chrome.bat - launch YOUR installed Chrome with remote debugging so
REM the app can attach over CDP (the robust connection mode).
REM
REM Chrome 136+ ignores --remote-debugging-port on the DEFAULT profile, so a
REM dedicated --user-data-dir (.\chrome_profile) is MANDATORY. Debugging binds
REM to 127.0.0.1 only, never 0.0.0.0.
REM
REM Override Chrome location:  set CHROME_PATH=C:\path\to\chrome.exe
REM ==========================================================================
setlocal enableextensions

set "PORT=9222"
set "PROJECT_ROOT=%~dp0"
set "PROFILE_DIR=%PROJECT_ROOT%chrome_profile"
set "URL=https://photoshop.adobe.com"

REM --- Locate Chrome --------------------------------------------------------
set "CHROME="
if defined CHROME_PATH if exist "%CHROME_PATH%" set "CHROME=%CHROME_PATH%"

if not defined CHROME if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
    echo [ERROR] Could not find Chrome.
    echo Set CHROME_PATH to your chrome.exe, e.g.:
    echo   set CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe
    exit /b 1
)

REM --- Is port 9222 already in use? -----------------------------------------
netstat -ano -p tcp | findstr /r /c:"127.0.0.1:%PORT% .*LISTENING" >nul 2>&1
if %errorlevel%==0 (
    REM Port is in use - is it a Chrome debug endpoint?
    curl -s --max-time 2 "http://127.0.0.1:%PORT%/json/version" >nul 2>&1
    if %errorlevel%==0 (
        echo [INFO] Port %PORT% is already serving a Chrome debug endpoint.
        echo Chrome already looks ready - run the app or python login_once.py.
        exit /b 0
    ) else (
        echo [ERROR] Port %PORT% is in use but is NOT a Chrome debug endpoint.
        echo Close whatever uses port %PORT%, or set PS_CDP_URL to a free port.
        exit /b 1
    )
)

REM --- Launch ---------------------------------------------------------------
if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

echo Starting Chrome:
echo   exe     : %CHROME%
echo   profile : %PROFILE_DIR%
echo   debug   : http://127.0.0.1:%PORT% (localhost only)
echo.

start "" "%CHROME%" --remote-debugging-port=%PORT% --remote-debugging-address=127.0.0.1 --user-data-dir="%PROFILE_DIR%" --start-maximized "%URL%"

echo Chrome launched. Log in to Adobe, then run: python login_once.py
endlocal
