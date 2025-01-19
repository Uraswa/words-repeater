@echo off
set VENV_DIR=./venv
set REQUIREMENTS_FILE=requirements.txt


if not exist ./venv/Scripts/activate.bat (
    echo Ustanovka venv....
    python -m venv ./venv
    if errorlevel 1 (
        echo Ошибка при создании виртуального окружения.
        pause
        exit /b
    )
    echo Venv created
)

echo Venv activation
call ./venv/Scripts/activate.bat
if errorlevel 1 (
    echo Eror activating vevnv
    pause
    exit /b
)

echo Installing requirements.txt
if exist requirements.txt (
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Error at installing requirements
        pause
        exit /b
    )
) else (
    echo file requirements.txt not found
)

python app.py
if errorlevel 1 (
    echo Error at script exec
    pause
    exit /b
)

echo Gotovo
pause
