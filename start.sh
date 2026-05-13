#!/bin/bash
# Multi-Agent BI System 시작 스크립트

set -e

echo "====================================="
echo "  LG HE Multi-Agent BI System"
echo "====================================="
echo ""

# .env 파일 확인
if [ ! -f ".env" ]; then
    echo "[!] .env 파일이 없습니다. .env.example을 복사합니다..."
    cp .env.example .env
    echo "[!] .env 파일을 열어 OPENAI_API_KEY를 설정하세요!"
    echo ""
    echo "    nano .env  또는  vim .env"
    echo ""
    exit 1
fi

# OPENAI_API_KEY 확인
if grep -q "your_openai_api_key_here" .env 2>/dev/null; then
    echo "[!] OPENAI_API_KEY가 설정되지 않았습니다."
    echo "    .env 파일을 열어 실제 API 키를 입력하세요."
    exit 1
fi

# Docker 확인
if ! command -v docker &> /dev/null; then
    echo "[!] Docker가 설치되지 않았습니다."
    echo "    https://www.docker.com/products/docker-desktop/ 에서 설치하세요."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "[!] Docker Compose가 설치되지 않았습니다."
    exit 1
fi

echo "[1/3] Docker 컨테이너 시작 중..."
docker-compose up -d

echo ""
echo "[2/3] Neo4j 준비 대기 중 (최대 60초)..."
sleep 10

# Neo4j 상태 확인
MAX_RETRIES=10
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker exec bi-neo4j curl -s http://localhost:7474 > /dev/null 2>&1; then
        echo "    Neo4j 준비 완료!"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "    대기 중... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 5
done

echo ""
echo "[3/3] Knowledge Graph 초기화 중..."
docker exec bi-app python scripts/init_neo4j.py

echo ""
echo "====================================="
echo "  시작 완료!"
echo "====================================="
echo ""
echo "  App:        http://localhost:8501"
echo "  Neo4j:      http://localhost:7474"
echo "              (neo4j / password123)"
echo ""
echo "  종료: docker-compose down"
echo "====================================="
