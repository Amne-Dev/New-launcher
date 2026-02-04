@echo off
echo Building Agent...
pyinstaller --clean agent.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo Building Launcher...
pyinstaller --clean alt.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo. 
echo Build Complete.
echo Now compile 'installer.iss' with Inno Setup.
pause
