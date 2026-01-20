@echo off
echo ============================================================
echo Guest Check-in ^& Invoice Collection System
echo ============================================================
echo.

REM Check if venv exists, create if not
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -q -r requirements.txt

echo.
echo Starting server...
echo.
python app.py

pause
