@echo off
echo ========================================================
echo        TRACE-X Hackathon Demo Auto-Start
echo ========================================================
echo.
echo Starting Docker containers (Postgres, Neo4j)...
cd /d D:\Projects\TRACE-X
docker compose up -d

echo.
echo Starting FastAPI Backend...
start "TRACE-X Backend" cmd /k "cd backend && set DATABASE_URL=postgresql://tracex:tracex_dev_password@localhost:5432/tracex && set NEO4J_URI=bolt://localhost:7687 && .venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo.
echo Starting Vite Frontend...
start "TRACE-X Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Starting Auto-Drip Live Simulation...
start "TRACE-X Auto-Drip Simulation" cmd /k "cd backend && set DATABASE_URL=postgresql://tracex:tracex_dev_password@localhost:5432/tracex && .venv\Scripts\python C:\Users\krish\.gemini\antigravity-cli\brain\5b13b87a-b542-4b84-8b2f-be1260a8f7c6\scratch\auto_drip.py"

echo.
echo ========================================================
echo All services started!
echo 1. Investigator Portal: http://localhost:5173/login
echo    (investigator.chennai_central@tracex-demo.com / TraceX@Demo123)
echo 2. Citizen Portal: http://localhost:5173/report
echo.
echo During your presentation, just submit a complaint via 
echo the Citizen Portal. The Auto-Drip service will detect 
echo it and automatically simulate money laundering hops 
echo over the next 30 seconds so the AI pipeline lights up!
echo ========================================================
pause
