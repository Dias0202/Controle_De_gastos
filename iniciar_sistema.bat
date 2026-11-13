@echo off
title Controle Financeiro e Open Finance (FastAPI + React + Pluggy)
echo ========================================================
echo   Iniciando Controle Financeiro (Backend + Frontend)
echo ========================================================

start "Backend FastAPI (Porta 8000)" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload"
start "Frontend React (Porta 5173)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Servidores iniciados! Acesse no navegador:
echo http://localhost:5173
pause
