# Quick Start

## Requirements

- Docker Desktop
- OpenAI API key

## Docker

```bash
cp .env.example .env
# edit OPENAI_API_KEY in .env

docker-compose up -d
docker exec bi-app python scripts/init_neo4j.py
```

Open:

- App: http://localhost:8501
- Neo4j Browser: http://localhost:7474

Default local Neo4j credentials:

```text
username: neo4j
password: password123
```

## Local Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Example Queries

- `2025년 Q3 북미 매출 보여줘`
- `2025년 Q3 영업이익이 왜 하락했는지 분석해줘`
- `최근 물류비 관련 이벤트 알려줘`
- `2025년 Q4 통합 KPI 보고서 만들어줘`

## Useful Commands

```bash
python -m unittest tests.test_query_guard tests.test_intent_service
python -m compileall .
docker-compose logs -f app
docker-compose down
```
