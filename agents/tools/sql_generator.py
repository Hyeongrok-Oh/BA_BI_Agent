"""
SQL Generator - LLM 기반 SQL 쿼리 생성기

역할:
- 자연어 질문을 분석하여 SQL 쿼리 생성
- Chain-of-Thought 추론으로 정확한 쿼리 보장
- SQLExecutor와 분리되어 생성만 담당
"""

import sqlite3
from typing import Dict, Any, Optional
from dataclasses import dataclass
from openai import OpenAI

from config.settings import get_erp_db_path, get_settings
from ..base import BaseTool, ToolResult


@dataclass
class SQLGenerationResult:
    """SQL 생성 결과"""
    query: str
    reasoning: str
    success: bool
    error: Optional[str] = None


class SQLGenerator(BaseTool):
    """LLM 기반 SQL 쿼리 생성기"""

    name = "sql_generator"
    description = "자연어 질문을 분석하여 SQLite 쿼리를 생성합니다."

    DEFAULT_DB_PATH = get_erp_db_path()

    def __init__(self, db_path: str = None, api_key: str = None):
        settings = get_settings()
        self.db_path = db_path or str(settings.erp_db_path)
        self.api_key = api_key or settings.openai_api_key
        self._client = None
        self._schema_cache = None

    @property
    def client(self) -> OpenAI:
        """Lazy OpenAI client initialization"""
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    @property
    def schema_info(self) -> str:
        """데이터베이스 스키마 정보 (캐시)"""
        if self._schema_cache is None:
            self._schema_cache = self._get_schema_info()
        return self._schema_cache

    def _get_schema_info(self) -> str:
        """데이터베이스 스키마 정보 추출"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()

            schema_lines = ["=== DATABASE SCHEMA ===\n"]

            for (table_name,) in tables:
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

                schema_lines.append(f"\nTable: {table_name}")
                schema_lines.append("Columns:")
                for col in columns:
                    col_id, name, col_type, not_null, default_val, pk = col
                    pk_marker = " (PRIMARY KEY)" if pk else ""
                    schema_lines.append(f"  - {name}: {col_type}{pk_marker}")

            conn.close()
            return "\n".join(schema_lines)
        except Exception as e:
            return f"Schema extraction error: {e}"

    def _create_sql_prompt(self, question: str, context: Dict = None) -> str:
        """SQL 생성 프롬프트"""
        context = context or {}
        period = context.get("period", {})
        region = context.get("region")

        period_hint = ""
        if period:
            year = period.get("year", 2024)
            quarter = period.get("quarter", 4)
            period_hint = f"\n현재 분석 기간: {year}년 Q{quarter}"

        region_hint = ""
        if region:
            region_hint = f"\n현재 분석 지역: {region}"

        return f"""당신은 LG전자 HE사업부 ERP 데이터베이스 전문가입니다.

{self.schema_info}

=== 비즈니스 컨텍스트 ===

**지역별 매핑 (MD_ORG.REGION)**:
- Americas: 북미 (US, CA, MX)
- Europe: 유럽 (DE, UK, FR)
- Asia: 아시아 (KR, CN, VN)
- Production: 생산법인 (VN, MX, PL)

**테이블 구조**:

1. TR_SALES (판매):
   - SALES_DATE: 판매 날짜
   - PRODUCT_ID, ORG_ID, CHANNEL_ID: 조인 키
   - QTY: 판매 수량
   - REVENUE_USD, REVENUE_KRW: 매출
   - WEBOS_REV_USD: webOS 플랫폼 수익
   - IS_B2B_SALES: B2B 여부 ('Y'/'N')
   - EXCHANGE_RATE: 환율

2. TR_PURCHASE (구매/원가):
   - PURCHASE_DATE: 구매 날짜
   - PANEL_PRICE_USD: 패널 단가
   - DRAM_PRICE_USD_PER_GB: DRAM 단가
   - RAW_MATERIAL_INDEX: 원자재 지수
   - TOTAL_COGS_USD, TOTAL_COGS_KRW: 총 원가

3. TR_EXPENSE (비용):
   - EXPENSE_DATE: 비용 발생일
   - EXPENSE_TYPE: LOGISTICS, MARKETING, PROMOTION, LABOR
   - LOGISTICS_COST: 물류비
   - MARKETING_COST: 마케팅비
   - PROMOTION_COST: 프로모션비
   - LABOR_COST: 인건비

4. EXT_MACRO (거시경제):
   - DATA_DATE, COUNTRY_CODE
   - EXCHANGE_RATE_KRW_USD: 원달러 환율
   - INTEREST_RATE: 기준금리
   - INFLATION_RATE: 인플레이션율
   - CSI_INDEX: 소비자심리지수

5. EXT_MARKET (시장):
   - DATA_DATE, REGION
   - TOTAL_SHIPMENT_10K: 글로벌 TV 출하량 (만대)
   - LGE_MARKET_SHARE: LG 점유율 (%)
   - SCFI_INDEX: 해상운임지수

6. EXT_TRADE_POLICY (무역정책):
   - DATA_DATE, COUNTRY_CODE
   - TARIFF_RATE: 관세율 (%)
   - TRADE_RISK_INDEX: 무역 리스크 지수

**기간 필터**:
- Q1: 01-03월, Q2: 04-06월, Q3: 07-09월, Q4: 10-12월
- 예: SALES_DATE BETWEEN '2024-10-01' AND '2024-12-31'
- 데이터 범위: 2023-01-01 ~ 2025-12-31
{period_hint}{region_hint}

**JOIN 예제**:

1. 지역별 매출 조회:
```sql
SELECT o.REGION, SUM(s.REVENUE_USD) as total_revenue
FROM TR_SALES s
JOIN MD_ORG o ON s.ORG_ID = o.ORG_ID
WHERE s.SALES_DATE BETWEEN '2024-10-01' AND '2024-12-31'
GROUP BY o.REGION
```

2. 물류비 추이:
```sql
SELECT strftime('%Y-%m', EXPENSE_DATE) as month,
       SUM(LOGISTICS_COST) as logistics
FROM TR_EXPENSE
WHERE EXPENSE_DATE BETWEEN '2024-01-01' AND '2024-12-31'
GROUP BY month
```

3. 패널 가격과 원가 관계:
```sql
SELECT strftime('%Y-%m', PURCHASE_DATE) as month,
       AVG(PANEL_PRICE_USD) as panel_price,
       AVG(TOTAL_COGS_USD) as cogs
FROM TR_PURCHASE
GROUP BY month
```

**분석 가이드라인**:
1. 수익성 분석 시 전년 동기 비교 우선 (YoY)
2. TR_EXPENSE로 비용 요인 분석
3. EXT_MACRO, EXT_MARKET으로 외부 요인 파악
4. 변동률 계산: (New - Old) / Old * 100

=== 사용자 질문 ===
{question}

=== 태스크 ===
위 질문에 답하기 위한 SQLite 쿼리를 생성하세요.
SQL 쿼리만 반환하세요. 설명이나 마크다운 없이 순수 SQL만 작성하세요.
"""

    def _create_reasoning_prompt(self, question: str) -> str:
        """추론 과정 생성 프롬프트"""
        return f"""당신은 LG전자 HE사업부 데이터 분석 전문가입니다.

{self.schema_info}

=== 비즈니스 컨텍스트 ===
- 지역: MD_ORG.REGION (Americas, Europe, Asia, Production)
- 판매: TR_SALES (REVENUE_USD, QTY, WEBOS_REV_USD)
- 원가: TR_PURCHASE (PANEL_PRICE_USD, TOTAL_COGS_USD)
- 비용: TR_EXPENSE (LOGISTICS_COST, MARKETING_COST, PROMOTION_COST)
- 외부데이터: EXT_MACRO, EXT_MARKET, EXT_TRADE_POLICY
- 데이터 범위: 2023-01-01 ~ 2025-12-31

=== 사용자 질문 ===
{question}

=== 태스크 ===
SQL 쿼리 생성 전, 분석 전략을 설명하세요:

1. **질문 해석**: 사용자가 무엇을 요청하는가?
2. **테이블 선택**: 어떤 테이블이 필요한가?
3. **기간 선택**: 비교할 기간은? (YoY 우선)
4. **분석 방법**: 어떤 메트릭과 집계가 필요한가?

한국어로 간결하게 3-5줄로 작성하세요.
"""

    def generate_reasoning(self, question: str) -> str:
        """추론 과정 생성"""
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert data analyst."},
                    {"role": "user", "content": self._create_reasoning_prompt(question)}
                ],
                temperature=0,
                max_tokens=500
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"추론 생성 오류: {e}"

    def generate(self, question: str, context: Dict = None, with_reasoning: bool = False) -> SQLGenerationResult:
        """
        SQL 쿼리 생성

        Args:
            question: 자연어 질문
            context: 추가 컨텍스트 (period, region 등)
            with_reasoning: Chain-of-Thought 추론 포함 여부

        Returns:
            SQLGenerationResult
        """
        reasoning = ""

        try:
            # Chain-of-Thought 추론 (선택적)
            if with_reasoning:
                reasoning = self.generate_reasoning(question)

            # SQL 생성
            prompt = self._create_sql_prompt(question, context)

            response = self.client.chat.completions.create(
                model="gpt-4o",  # 더 정확한 SQL 생성을 위해 gpt-4o 사용
                messages=[
                    {"role": "system", "content": "You are an expert SQL query generator. Return only valid SQLite queries without any markdown or explanation."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1000
            )

            sql_query = response.choices[0].message.content.strip()

            # SQL 코드 블록 제거
            if "```sql" in sql_query:
                sql_query = sql_query.split("```sql")[1].split("```")[0]
            elif "```" in sql_query:
                sql_query = sql_query.split("```")[1].split("```")[0]

            sql_query = sql_query.strip()

            return SQLGenerationResult(
                query=sql_query,
                reasoning=reasoning,
                success=True
            )

        except Exception as e:
            return SQLGenerationResult(
                query="",
                reasoning=reasoning,
                success=False,
                error=str(e)
            )

    def execute(self, question: str, context: Dict = None) -> ToolResult:
        """Tool 인터페이스 구현"""
        result = self.generate(question, context)

        if result.success:
            return ToolResult(
                success=True,
                data={
                    "query": result.query,
                    "reasoning": result.reasoning
                }
            )
        else:
            return ToolResult(
                success=False,
                error=result.error
            )
