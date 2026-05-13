@echo off
REM Multi-Agent BI System 시작 스크립트 (Windows)

echo =====================================
echo   LG HE Multi-Agent BI System
echo =====================================
echo.

REM .env 파일 확인
if not exist ".env" (
    echo [!] .env 파일이 없습니다. .env.example을 복사합니다...
    copy .env.example .env
    echo [!] .env 파일을 열어 OPENAI_API_KEY를 설정하세요!
    echo.
    notepad .env
    pause
    exit /b 1
)

echo [1/3] Docker 컨테이너 시작 중...
docker-compose up -d

echo.
echo [2/3] Neo4j 준비 대기 중 (30초)...
timeout /t 30 /nobreak

echo.
echo [3/3] Knowledge Graph 초기화 중...
docker exec bi-app python scripts/init_neo4j.py

echo.
echo =====================================
echo   시작 완료!
echo =====================================
echo.
echo   App:        http://localhost:8501
echo   Neo4j:      http://localhost:7474
echo               (neo4j / password123)
echo.
echo   종료: docker-compose down
echo =====================================
pause
