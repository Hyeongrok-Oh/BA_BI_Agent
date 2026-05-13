"""
Search Agent - 데이터 검색 에이전트

역할:
- 자연어 질문을 분석하여 적절한 Tool 선택 (SQL/Graph/Vector)
- 쿼리 생성 (Planning)
- Tool 실행 및 결과 반환

사용 Tool:
- SQLExecutor: ERP 데이터 조회
- GraphExecutor: Knowledge Graph 조회
- VectorSearchTool: 이벤트 유사도 검색
"""

import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .base import BaseAgent, AgentContext
from .tools import SQLExecutor, SQLGenerator, GraphExecutor, VectorSearchTool


# SQL 생성 프롬프트
SQL_GENERATION_PROMPT = """당신은 LG전자 HE사업부 ERP 데이터베이스 전문가입니다.

## 데이터베이스 스키마
{schema}

## 비즈니스 컨텍스트

**지역별 SUBSIDIARY_ID 매핑 (필수)**:
- 북미(NA): SUBSIDIARY_ID IN ('LGEUS', 'LGECA')
- 유럽(EU): SUBSIDIARY_ID IN ('LGEUK', 'LGEDE', 'LGEFR')
- 한국(KR): SUBSIDIARY_ID = 'LGEKR'

**원가 유형 (COST_TYPE)**:
- MAT: 재료비
- LOG: 물류비
- TAR: 관세
- OH: 오버헤드

**가격 조건 (COND_TYPE)**:
- ZPR0: 매출 (Gross Price)
- ZPRO: Price Protection (비용)
- K007: 할인
- ZMDF: MDF (마케팅비용)

**기간 필터**:
- Q1: 01-03월, Q2: 04-06월, Q3: 07-09월, Q4: 10-12월
- 예: strftime('%Y-%m', DOC_DATE) BETWEEN '2024-10' AND '2024-12'

## 사용자 질문
{question}

## 태스크
위 질문에 답하기 위한 SQLite 쿼리를 생성하세요.
SQL 쿼리만 반환하세요. 설명 없이 쿼리만 작성하세요.
"""

# Graph 쿼리 생성 프롬프트
GRAPH_GENERATION_PROMPT = """당신은 Knowledge Graph 전문가입니다.

## 그래프 스키마 (동적)
{schema}

## 노드 유형
- **Event**: 외부 이벤트/뉴스 (name, category, severity, source_urls, source_titles, sources)
  - category: geopolitical, policy, market, company, macro_economy, technology, natural
  - severity: low, medium, high, critical
- **Driver**: 비즈니스 요인 (id, name_kr, name_en)
- **Anchor**: KPI (매출, 원가, 판매수량)
- **Dimension**: 차원 (Region, ProductCategory, TimePeriod 하위 라벨)

## 관계 유형
- (Event)-[AFFECTS]->(Driver): 이벤트가 요인에 영향 (polarity, weight, magnitude, evidence)
- (Event)-[TARGETS]->(Dimension): 이벤트 영향 범위
- (Driver)-[AFFECTS]->(Anchor): 요인이 KPI에 영향

## 예시 쿼리
1. 특정 키워드 관련 이벤트 검색:
   MATCH (e:Event) WHERE e.name CONTAINS '키워드' RETURN e LIMIT 10

2. 최근 이벤트 검색:
   MATCH (e:Event) RETURN e ORDER BY e.start_date DESC LIMIT 10

3. 특정 카테고리 이벤트:
   MATCH (e:Event {{category: 'company'}}) RETURN e LIMIT 10

4. 이벤트와 연결된 Driver:
   MATCH (e:Event)-[r:AFFECTS]->(d:Driver) WHERE e.name CONTAINS '키워드' RETURN e, r, d

## 사용자 질문
{question}

## 태스크
위 질문에 답하기 위한 Cypher 쿼리를 생성하세요.
- Event 노드의 name, source_titles, source_urls 속성을 활용하세요.
- 검색 키워드가 있으면 CONTAINS를 사용하세요.
- 결과는 LIMIT 10으로 제한하세요.
Cypher 쿼리만 반환하세요.
"""

# Tool 선택 프롬프트
TOOL_SELECTION_PROMPT = """사용자 질문을 분석하여 어떤 데이터 소스를 사용할지 결정하세요.

## 데이터 소스
1. **sql**: ERP 데이터베이스 (매출, 원가, 판매량 등 정량 데이터)
2. **graph**: Knowledge Graph (외부 이벤트, 인과관계, 영향 요인)
3. **both**: 둘 다 필요한 경우

## 판단 기준
- 수치/금액/수량 관련 → sql
- 원인/이벤트/요인 관련 → graph
- "왜", "원인", "영향" 키워드 → graph 또는 both

## 사용자 질문
{question}

## 응답 형식 (JSON)
{{"tool": "sql" | "graph" | "both", "reason": "선택 이유"}}
"""


class SearchAgent(BaseAgent):
    """데이터 검색 에이전트"""

    name = "search_agent"
    description = "자연어 질문을 분석하여 ERP, Knowledge Graph, 또는 Vector Index에서 데이터를 검색합니다."

    def __init__(self, api_key: str = None, db_path: str = None):
        super().__init__(api_key)

        # Tools 초기화
        self.sql_generator = SQLGenerator(db_path, api_key)  # SQL 생성기
        self.sql_executor = SQLExecutor(db_path)  # SQL 실행기
        self.graph_tool = GraphExecutor()
        self.vector_tool = VectorSearchTool(api_key=api_key)

        self.add_tool(self.sql_generator)
        self.add_tool(self.sql_executor)
        self.add_tool(self.graph_tool)
        self.add_tool(self.vector_tool)

        # 스키마 캐시
        self._sql_schema = None
        self._graph_schema = None

    @property
    def sql_schema(self) -> str:
        if self._sql_schema is None:
            self._sql_schema = self.sql_generator.schema_info
        return self._sql_schema

    @property
    def graph_schema(self) -> str:
        if self._graph_schema is None:
            self._graph_schema = self.graph_tool.get_schema()
        return self._graph_schema

    def _select_tool(self, question: str) -> Dict[str, str]:
        """질문 분석하여 Tool 선택"""
        prompt = TOOL_SELECTION_PROMPT.format(question=question)

        response = self._call_llm(
            prompt=prompt,
            system_prompt="당신은 데이터 소스 선택 전문가입니다. JSON 형식으로만 응답하세요.",
            model="gpt-4o-mini",
            temperature=0
        )

        try:
            # JSON 파싱
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return json.loads(response.strip())
        except:
            # 기본값: SQL
            return {"tool": "sql", "reason": "파싱 실패, 기본값 사용"}

    def _generate_sql(self, question: str, context: Dict = None) -> str:
        """SQL 쿼리 생성 (SQLGenerator 사용)"""
        result = self.sql_generator.generate(question, context, with_reasoning=False)

        if result.success:
            return result.query
        else:
            # Fallback: 기존 방식
            prompt = SQL_GENERATION_PROMPT.format(
                schema=self.sql_schema,
                question=question
            )

            response = self._call_llm(
                prompt=prompt,
                system_prompt="당신은 SQL 전문가입니다. 유효한 SQLite 쿼리만 반환하세요.",
                model="gpt-4o",
                temperature=0
            )

            if "```sql" in response:
                response = response.split("```sql")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            return response.strip()

    def _generate_cypher(self, question: str) -> str:
        """Cypher 쿼리 생성"""
        prompt = GRAPH_GENERATION_PROMPT.format(
            schema=self.graph_schema,
            question=question
        )

        response = self._call_llm(
            prompt=prompt,
            system_prompt="당신은 Neo4j Cypher 전문가입니다. 유효한 Cypher 쿼리만 반환하세요.",
            model="gpt-4o",
            temperature=0
        )

        # 코드 블록 제거
        if "```cypher" in response:
            response = response.split("```cypher")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]

        return response.strip()

    def search_sql(self, question: str, context: Dict = None) -> Dict[str, Any]:
        """SQL 기반 검색 (SQLGenerator → SQLExecutor)"""
        # 1. SQLGenerator로 쿼리 생성
        sql_query = self._generate_sql(question, context)

        # 2. SQLExecutor로 쿼리 실행
        result = self.sql_executor.execute(sql_query)

        return {
            "source": "sql",
            "query": sql_query,
            "success": result.success,
            "data": result.data.to_dict('records') if result.success and result.data is not None else None,
            "error": result.error
        }

    def search_graph(self, question: str) -> Dict[str, Any]:
        """Graph 기반 검색"""
        cypher_query = self._generate_cypher(question)
        result = self.graph_tool.execute(cypher_query)

        # LLM 생성 쿼리가 실패하면 개선된 fallback 시도
        if not result.success or not result.data:
            # 키워드 추출 (불용어 제외)
            stopwords = {'뉴스', '알려줘', '검색', '찾아줘', '보여줘', '관련', '최근', '에', '의', '를', '을', '이', '가'}
            keywords = [w for w in question.split() if len(w) > 1 and w not in stopwords]

            if keywords:
                fallback_query = """
                MATCH (e:Event)
                WHERE any(kw IN $keywords WHERE
                    toLower(e.name) CONTAINS kw
                    OR toLower(coalesce(e.name_en, '')) CONTAINS kw
                    OR any(t IN coalesce(e.source_titles, []) WHERE toLower(t) CONTAINS kw)
                )
                RETURN e
                LIMIT 10
                """
                fallback_params = {"keywords": [kw.lower() for kw in keywords[:3]]}
                result = self.graph_tool.execute(fallback_query, fallback_params)
                if result.success and result.data:
                    cypher_query = fallback_query

        # 결과 데이터 평탄화 (e 키에서 Node 속성 추출)
        flat_data = []
        if result.success and result.data:
            for record in result.data:
                if 'e' in record and isinstance(record['e'], dict):
                    flat_data.append(record['e'])
                else:
                    flat_data.append(record)

        return {
            "source": "graph",
            "query": cypher_query,
            "success": result.success and len(flat_data) > 0,
            "data": flat_data if flat_data else result.data,
            "error": result.error if not result.success else (None if flat_data else "검색 결과가 없습니다.")
        }

    def search_vector(self, question: str, top_k: int = 5, category: str = None) -> Dict[str, Any]:
        """Vector 유사도 기반 이벤트 검색"""
        if category:
            events = self.vector_tool.search_by_category(question, category, top_k)
        else:
            result = self.vector_tool.execute(question, top_k)
            events = result.data if result.success else []

        # 결과를 직렬화 가능한 형태로 변환
        data = []
        for ev in events:
            data.append({
                "name": ev.name,
                "category": ev.category,
                "evidence": ev.evidence[:300] if ev.evidence else "",
                "severity": ev.severity,
                "score": round(ev.score, 4),
                "related_factors": ev.related_factors,
                "source_urls": ev.source_urls or [],
                "source_titles": ev.source_titles or []
            })

        return {
            "source": "vector",
            "query": question,
            "success": len(data) > 0,
            "data": data,
            "error": None if data else "관련 이벤트를 찾지 못했습니다."
        }

    def run(self, context: AgentContext) -> Dict[str, Any]:
        """
        검색 실행

        Args:
            context: AgentContext with query

        Returns:
            검색 결과 딕셔너리
        """
        question = context.query
        metadata = context.metadata or {}

        # 데이터 소스가 지정된 경우
        source = metadata.get("source")
        top_k = metadata.get("top_k", 5)
        category = metadata.get("category")

        if source == "sql":
            result = self.search_sql(question)
        elif source == "graph":
            result = self.search_graph(question)
        elif source == "vector":
            # 벡터 유사도 검색 (이벤트 검색)
            result = self.search_vector(question, top_k, category)
        else:
            # Tool 선택
            selection = self._select_tool(question)
            context.add_step("tool_selection", selection)

            tool_choice = selection.get("tool", "sql")

            if tool_choice == "sql":
                result = self.search_sql(question)
            elif tool_choice == "graph":
                result = self.search_graph(question)
            else:  # both
                sql_result = self.search_sql(question)
                graph_result = self.search_graph(question)
                result = {
                    "source": "both",
                    "sql": sql_result,
                    "graph": graph_result
                }

        context.add_step("search_result", result)
        return result

    def execute_sql_directly(self, sql_query: str) -> Dict[str, Any]:
        """SQL 직접 실행 (쿼리가 이미 있는 경우) - SQLExecutor만 사용"""
        result = self.sql_executor.execute(sql_query)
        return {
            "source": "sql",
            "query": sql_query,
            "success": result.success,
            "data": result.data.to_dict('records') if result.success and result.data is not None else None,
            "error": result.error
        }

    def execute_cypher_directly(self, cypher_query: str, params: Dict = None) -> Dict[str, Any]:
        """Cypher 직접 실행 (쿼리가 이미 있는 경우)"""
        result = self.graph_tool.execute(cypher_query, params)
        return {
            "source": "graph",
            "query": cypher_query,
            "success": result.success,
            "data": result.data,
            "error": result.error
        }
