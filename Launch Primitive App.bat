@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%LocalAppData%\Microsoft\WindowsApps\python3.13.exe"
set "GO_EXE="

if exist "C:\Program Files\Go\bin\go.exe" set "GO_EXE=C:\Program Files\Go\bin\go.exe"
if "%GO_EXE%"=="" if exist "C:\Program Files (x86)\Go\bin\go.exe" set "GO_EXE=C:\Program Files (x86)\Go\bin\go.exe"
if "%GO_EXE%"=="" (
    for /f "delims=" %%I in ('where go 2^>nul') do (
        set "GO_EXE=%%I"
        goto :go_found
    )
)

:go_found
if not "%GO_EXE%"=="" (
    echo Building primitive.exe ...
    "%GO_EXE%" build -o "%~dp0primitive.exe" .
    if exist "%~dp0primitive.exe" (
        set "PRIMITIVE_BIN=%~dp0primitive.exe"
    ) else (
        echo Build failed. The app may still run using Go fallback.
    )
) else (
    if exist "%~dp0primitive.exe" set "PRIMITIVE_BIN=%~dp0primitive.exe"
)

if exist "%PYTHON_EXE%" (
    start "Primitive Desktop" "%PYTHON_EXE%" "%~dp0desktop_app.py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        start "Primitive Desktop" python "%~dp0desktop_app.py"
    ) else (
        echo Python was not found.
        echo Install Python 3 and try again.
        pause
    )
)

endlocal