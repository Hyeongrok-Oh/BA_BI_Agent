"""
Analysis Agent - 분석 조율 에이전트 (Orchestrator)

역할:
- 가설 생성 → 가설 검증 (SQL) → 이벤트 매칭 플로우 조율
- 하위 에이전트들의 협업 관리
- 최종 분석 결과 종합 (SQL 쿼리 + 매칭된 이벤트 포함)
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..base import BaseAgent, AgentContext
from ..tools import SQLExecutor
from .hypothesis_generator import HypothesisGenerator, Hypothesis
from .hypothesis_validator import HypothesisValidator
from .event_matcher import EventMatcher, MatchedEvent


@dataclass
class KPIChange:
    """KPI 변동 정보 (QoQ + YoY)"""
    kpi_name: str  # 매출, 원가, 판매수량
    current_value: float
    current_period: str  # "2025년 Q3"
    # QoQ (전분기 대비)
    qoq_previous_value: float
    qoq_change_percent: float
    qoq_change_amount: float
    qoq_period_info: str  # "2025 Q3 vs 2025 Q2"
    # YoY (전년 동기 대비)
    yoy_previous_value: float
    yoy_change_percent: float
    yoy_change_amount: float
    yoy_period_info: str  # "2025 Q3 vs 2024 Q3"
    # 기존
    region: str = ""
    sql_query: str = ""


@dataclass
class AnalysisResult:
    """분석 결과"""
    question: str
    kpi_change: KPIChange = None  # KPI 변동 (먼저 보여줌)
    hypotheses: List[Hypothesis] = field(default_factory=list)
    validated_hypotheses: List[Hypothesis] = field(default_factory=list)
    matched_events: Dict[str, List[MatchedEvent]] = field(default_factory=dict)
    sql_queries: List[Dict] = field(default_factory=list)
    summary: str = ""
    sources: List[Dict] = field(default_factory=list)
    details: List[Dict] = field(default_factory=list)
    # 3-Stage 분석 결과
    analysis_plan: Dict = field(default_factory=dict)
    interpretation: Dict = field(default_factory=dict)
    contributions: List = field(default_factory=list)
    model_r_squared: float = 0.0


REASONING_PROMPT = """당신은 LG전자 HE사업부 경영 분석 전문가입니다.

## 분석 질문
{question}

## KPI 변동
{kpi_summary}

## 분석된 주요 요인
{factors_summary}

## 관련 시장 이벤트
{events_summary}

---

## 핵심 원칙 - 반드시 지킬 것

### 1) 인과관계를 절대로 단정하지 않는다

**금지 표현:**
- "~이 원인이다"
- "~때문이다"
- "~영향을 주었다"
- "~을 초래했다"
- "~의 결과이다"

**허용 표현:**
- "함께 움직이는 경향이 있습니다"
- "동일한 방향성이 관찰됩니다"
- "맥락적으로 연결될 수 있습니다"
- "동시에 나타난 흐름입니다"
- "시사하는 바가 있습니다"
- "계절성 여부를 판단할 수 있는 패턴입니다"

### 2) 단기(QoQ)와 장기(YoY)를 분리하지 말고, 요인 단위로 패턴을 묶어서 해석한다

### 3) Driver Type에 따른 다섯 가지 패턴 분류

**Driver Type:**
- Volume: 판매량, 출하량 (expected_sign: +)
- Mix: OLED 비중, 프리미엄 비중 (expected_sign: +)
- Price: ASP, 할인율 (expected_sign: +)
- Cost: 프로모션 비용, 마케팅 비용 (expected_sign: -)

| 패턴 | 조건 | 해석 |
|------|------|------|
| 구조적 성장 패턴 | Volume/Mix/Price ↑↑ | 지속적 성장 흐름 |
| 비용 압박 패턴 | Cost ↑↑ | 비용 증가로 인한 압박 |
| 단기 조정 + 장기 회복 | QoQ↓ YoY↑ | 일시적 조정, 구조적 회복 |
| 일시적 변동 | QoQ↑ YoY↓ | 반짝 증가, 지속성 낮음 |
| 구조적 하락 가능성 | QoQ↓ YoY↓ | 단기·장기 모두 하락 |

### 4) 외부 이벤트 연결 시 인과 단정 금지

사용 표현:
- "같은 시기에 언급된 이벤트와 맥락적으로 유사한 흐름입니다"
- "직접적인 인과는 단정할 수 없으나 참고할 수 있는 정보입니다"

### 5) 실제 데이터 기반으로만 설명하고, 새로운 요인/이벤트를 상상하지 않는다

---

## 출력 구조 — 반드시 이 형식 유지

### 1) 도입부
- KPI의 QoQ/YoY 변화 요약
- 단기/장기 흐름의 큰 그림
- 예: "전분기 대비 X% 감소했으나, 전년 대비로는 Y% 증가했습니다. 이는 단기 조정과 장기 회복 흐름이 동시에 나타난 패턴입니다."

### 2) 요인별 단기·장기 패턴 해석

각 요인은 아래 구조로 작성한다:

**[요인명]**

"[Driver]는 전분기 대비 X%, 전년 대비 Y% 변화를 보였습니다.
이 패턴은 [패턴 분류]로 해석될 수 있으며,
직접적인 인과는 단정할 수 없지만 KPI와의 방향성과 맥락적 일치를 참고할 수 있습니다."

패턴 분류: 위 5가지 중 하나 (구조적 성장/비용 압박/단기 조정+장기 회복/일시적 변동/구조적 하락 가능성)

### 3) 외부 이벤트와의 맥락 연결
- 단정 없이 맥락적 관계만 설명
- 수치와 방향을 기반으로 해석
- "같은 시기에 언급된 ~와 맥락적으로 유사한 흐름입니다"

### 4) 결론
- 패턴 기반 정리
- 인과 단정 없이 단기·장기 균형 평가
- "전체적으로 ~한 패턴이 관찰되며, ~한 점을 시사합니다"

---

## 금지 사항
- Factor, Score, Graph, 기여도 % 등 기술 용어
- 인과 단정 표현 ("원인", "~때문에", "영향", "초래", "결과")
- 데이터에 없는 요인/이벤트 상상

## 응답
"""


REASONING_PROMPT_V2 = """당신은 LG전자 HE사업부 경영 분석 전문가입니다.

## 분석 질문
{question}

## KPI 변동
{kpi_summary}

## 그룹별 요인 데이터
{grouped_factors_summary}

## 관련 이벤트
{events_summary}

---

## 글쓰기 규칙

### 1) 인과 단정 절대 금지
- 금지: "원인이다", "때문이다", "영향을 주었다", "초래했다", "기여했다"
- 허용: "함께 움직이는 경향", "맥락적으로 유사한 흐름", "참고할 수 있는 정보", "동일한 방향성이 관찰됨"

### 2) 한 요인당 5가지 관점으로 5문장 이상 작성

| 관점 | 설명 |
|------|------|
| QoQ 수치 | 전분기 대비 변화와 방향성 |
| YoY 수치 | 전년 대비 변화와 방향성 |
| 시장 의미 | 업계 전반의 흐름과 연결 |
| 경쟁사 맥락 | 동종 업체 동향과 비교 (관련 이벤트 있으면) |
| 전략적 시사점 | 향후 점검 포인트 |

### 3) 문장 구조 다양화
- 동일한 문장 패턴 반복 금지
- 어미 변화: "~했습니다", "~입니다", "~됩니다", "~보입니다"
- 연결어 활용: "한편", "이와 함께", "같은 시기에", "특히"

### 4) 5가지 패턴 분류 (각 요인에 적용)

| 패턴 | 조건 | 해석 |
|------|------|------|
| 구조적 성장 패턴 | Volume/Mix/Price QoQ↑ YoY↑ | 지속적 성장 흐름 |
| 비용 압박 패턴 | Cost QoQ↑ YoY↑ | 비용 증가 압박 |
| 단기 조정 + 장기 회복 | QoQ↓ YoY↑ | 일시적 조정, 구조적 회복 |
| 일시적 변동 | QoQ↑ YoY↓ | 반짝 증가, 지속성 낮음 |
| 구조적 하락 가능성 | QoQ↓ YoY↓ | 단기·장기 모두 하락 |

---

## 출력 형식 (반드시 준수)

### 1. 도입부
(KPI QoQ/YoY 요약 2-3문장, 전체 패턴 큰 그림)

### 2. 믹스 요인 (Mix)
(해당 그룹에 요인이 있으면 작성, 각 요인당 5문장 이상)

### 3. 물량 요인 (Volume)
(해당 그룹에 요인이 있으면 작성, 각 요인당 5문장 이상)

### 4. 가격 요인 (Price)
(해당 그룹에 요인이 있으면 작성, 각 요인당 5문장 이상)

### 5. 비용 요인 (Cost)
(해당 그룹에 요인이 있으면 작성, 각 요인당 5문장 이상)

### 6. 외부 이벤트
(이벤트 출처 번호 [1], [2] 활용하여 맥락적 연결)

### 7. 결론
(패턴 기반 정리 2-3문장, 인과 단정 없이)

---

## 금지 사항
- Factor, Score, Graph 등 기술 용어
- 인과 단정 표현 ("원인", "때문에", "영향", "초래", "결과")
- 데이터에 없는 정보 추가
- 해당 그룹에 요인이 없으면 그 섹션 생략

## 응답
"""


class AnalysisAgent(BaseAgent):
    """분석 조율 에이전트"""

    name = "analysis_agent"
    description = "가설 생성, SQL 검증, 이벤트 매칭을 조율하여 KPI 변동 원인을 분석합니다."

    # KPI 추출 패턴 (실제 ERP DB 스키마: TR_SALES, TR_PURCHASE, TR_EXPENSE)
    KPI_PATTERNS = {
        "매출": {
            "keywords": ["매출", "revenue", "sales", "수익"],
            "query_template": """
                SELECT
                    CASE
                        WHEN SALES_DATE >= '{prev_start}' AND SALES_DATE <= '{prev_end}' THEN 'Previous'
                        WHEN SALES_DATE >= '{curr_start}' AND SALES_DATE <= '{curr_end}' THEN 'Current'
                    END AS PERIOD,
                    SUM(REVENUE_USD) AS TOTAL_VALUE
                FROM TR_SALES
                WHERE (
                    (SALES_DATE >= '{prev_start}' AND SALES_DATE <= '{prev_end}')
                    OR (SALES_DATE >= '{curr_start}' AND SALES_DATE <= '{curr_end}')
                ) {region_filter}
                GROUP BY PERIOD
            """
        },
        "원가": {
            "keywords": ["원가", "cost", "비용"],
            "query_template": """
                SELECT
                    CASE
                        WHEN PURCHASE_DATE >= '{prev_start}' AND PURCHASE_DATE <= '{prev_end}' THEN 'Previous'
                        WHEN PURCHASE_DATE >= '{curr_start}' AND PURCHASE_DATE <= '{curr_end}' THEN 'Current'
                    END AS PERIOD,
                    SUM(TOTAL_COGS_USD) AS TOTAL_VALUE
                FROM TR_PURCHASE
                WHERE (
                    (PURCHASE_DATE >= '{prev_start}' AND PURCHASE_DATE <= '{prev_end}')
                    OR (PURCHASE_DATE >= '{curr_start}' AND PURCHASE_DATE <= '{curr_end}')
                ) {region_filter}
                GROUP BY PERIOD
            """
        },
        "판매수량": {
            "keywords": ["판매량", "수량", "quantity", "volume"],
            "query_template": """
                SELECT
                    CASE
                        WHEN SALES_DATE >= '{prev_start}' AND SALES_DATE <= '{prev_end}' THEN 'Previous'
                        WHEN SALES_DATE >= '{curr_start}' AND SALES_DATE <= '{curr_end}' THEN 'Current'
                    END AS PERIOD,
                    SUM(QTY) AS TOTAL_VALUE
                FROM TR_SALES
                WHERE (
                    (SALES_DATE >= '{prev_start}' AND SALES_DATE <= '{prev_end}')
                    OR (SALES_DATE >= '{curr_start}' AND SALES_DATE <= '{curr_end}')
                ) {region_filter}
                GROUP BY PERIOD
            """
        },
        "영업이익": {
            "keywords": ["영업이익", "operating profit", "이익"],
            "query_template": """
                SELECT
                    CASE
                        WHEN s.SALES_DATE >= '{prev_start}' AND s.SALES_DATE <= '{prev_end}' THEN 'Previous'
                        WHEN s.SALES_DATE >= '{curr_start}' AND s.SALES_DATE <= '{curr_end}' THEN 'Current'
                    END AS PERIOD,
                    SUM(s.REVENUE_USD) - COALESCE(SUM(p.TOTAL_COGS_USD), 0) AS TOTAL_VALUE
                FROM TR_SALES s
                LEFT JOIN TR_PURCHASE p ON s.PRODUCT_ID = p.PRODUCT_ID
                    AND strftime('%Y-%m', s.SALES_DATE) = strftime('%Y-%m', p.PURCHASE_DATE)
                WHERE (
                    (s.SALES_DATE >= '{prev_start}' AND s.SALES_DATE <= '{prev_end}')
                    OR (s.SALES_DATE >= '{curr_start}' AND s.SALES_DATE <= '{curr_end}')
                ) {region_filter_sales}
                GROUP BY PERIOD
            """
        }
    }

    # 지역 → Subsidiary 매핑
    REGION_SUBSIDIARY_MAP = {
        "NA": ["LGEUS", "LGECA"],
        "EU": ["LGEDE", "LGEFR", "LGEUK"],
        "KR": ["LGEKR"],
        "US": ["LGEUS"],
        "북미": ["LGEUS", "LGECA"],
        "유럽": ["LGEDE", "LGEFR", "LGEUK"],
        "한국": ["LGEKR"]
    }

    # 유사 Factor 그룹화 (대표 Factor → 유사 Factor 목록)
    FACTOR_GROUPS = {
        # 수요 관련
        "수요 변동": ["수요", "글로벌수요", "지역별수요", "계절적 수요", "계절적수요", "IT 세트 수요 둔화",
                    "수요부진", "수요 부진", "TV수요", "가전수요", "성수기효과", "성수기 효과"],
        # 경기/소비 관련
        "경기/소비심리": ["경기부진", "경기 부진", "소비심리위축", "소비심리 위축", "소비 심리",
                      "침체된 주택 매매", "주택 매매", "경기침체", "소비 둔화"],
        # 환율 관련
        "환율": ["환율", "원/달러 환율", "달러 환율", "원달러", "달러 강세"],
        # 경쟁 관련
        "경쟁 심화": ["경쟁심화", "경쟁 심화", "가격경쟁", "중국업체 경쟁", "TCL", "하이센스"],
        # 물류/운임 관련
        "물류비/운임": ["물류비", "해상운임", "운임", "컨테이너 운임", "홍해 사태"],
        # 패널/부품 관련
        "패널/부품 가격": ["패널가격", "패널 가격", "디스플레이 가격", "OLED 패널", "LCD 패널", "부품비"],
        # 관세 관련
        "관세/무역": ["관세", "관세율", "수입관세", "트럼프 관세", "무역분쟁"],
    }

    # 분석 설정
    TOP_K_FACTORS = 10  # 상위 몇 개 요인만 상세 분석
    MIN_EVENT_SCORE = 0.5  # 이벤트 최소 매칭 점수
    REASONING_MODEL = "gpt-5.2-pro-2025-12-11"  # 추론 모델 (Responses API)

    def __init__(self, api_key: str = None, db_path: str = None):
        super().__init__(api_key)
        from config.settings import get_erp_db_path

        self.db_path = db_path or get_erp_db_path()

        # SQL 실행기 초기화
        self.sql_executor = SQLExecutor(self.db_path)

        # 하위 에이전트 초기화
        self.hypothesis_generator = HypothesisGenerator(api_key)
        self.hypothesis_validator = HypothesisValidator(api_key, self.db_path)
        self.event_matcher = EventMatcher(api_key)

        self.add_sub_agent(self.hypothesis_generator)
        self.add_sub_agent(self.hypothesis_validator)
        self.add_sub_agent(self.event_matcher)

    def analyze(
        self,
        question: str,
        period: Dict = None,
        region: str = None,
        company: str = "LGE",
        verbose: bool = True
    ) -> AnalysisResult:
        """
        KPI 변동 원인 분석 실행

        Args:
            question: 사용자 질문
            period: {"year": 2024, "quarter": 4}
            region: "NA", "EU", "KR" 등
            company: 회사 코드
            verbose: 상세 출력 여부
        """
        if verbose:
            print("=" * 60)
            print(f"질문: {question}")
            print("=" * 60)

        # 기본 기간 설정
        if not period:
            period = {"year": 2024, "quarter": 4}

        # Step 0: KPI 변동 계산 (매출/원가/수량 자체의 변동)
        if verbose:
            print("\n[Step 0] KPI 변동 계산 중...")

        kpi_change = self._calculate_kpi_change(question, period, region)

        if verbose and kpi_change:
            print(f"  {kpi_change.kpi_name} ({kpi_change.current_period}): {kpi_change.current_value:,.0f}")
            print(f"  QoQ: {kpi_change.qoq_previous_value:,.0f} → {kpi_change.current_value:,.0f} ({kpi_change.qoq_change_percent:+.1f}%)")
            print(f"  YoY: {kpi_change.yoy_previous_value:,.0f} → {kpi_change.current_value:,.0f} ({kpi_change.yoy_change_percent:+.1f}%)")

        # Step 1: 가설 생성
        if verbose:
            print("\n[Step 1] 가설 생성 중...")

        hypotheses = self.hypothesis_generator.generate(
            question=question,
            company=company,
            period=f"{period['year']}년 Q{period['quarter']}",
            region=region
        )

        if verbose:
            print(f"  생성된 가설: {len(hypotheses)}개")
            for h in hypotheses:
                print(f"    - [{h.id}] {h.description}")

        # Step 2: 가설 검증 (SHAP Analysis with Fallback)
        if verbose:
            print("\n[Step 2] 가설 검증 중...")

        # KPI ID 추출
        kpi_id = self._extract_kpi_id(question)
        kpi_name = self._extract_kpi_from_question(question)

        # 질문이 QoQ/YoY 중 어느 변화에 초점을 두는지 결정
        question_focus = self._detect_question_focus(question)

        # KPI QoQ가 부정적이면 무조건 QoQ 초점으로 강제 설정
        if kpi_change and kpi_change.qoq_change_percent < 0:
            question_focus = "qoq"
            if verbose:
                print(f"  KPI QoQ 감소({kpi_change.qoq_change_percent:+.1f}%) → question_focus='qoq'로 강제 설정")

        if verbose:
            focus_desc = {"qoq": "전분기 대비", "yoy": "전년 대비", "both": "전체"}
            print(f"  질문 초점: {focus_desc.get(question_focus, question_focus)}")

        # Confidence 기반 검증
        validation_result = self.hypothesis_validator.validate(
            hypotheses=hypotheses,
            kpi_id=kpi_id,
            period=period,
            verbose=verbose,
            question_focus=question_focus
        )

        # 결과 추출
        validated = validation_result.get("validated_hypotheses", [])
        contributions = validation_result.get("contributions", [])
        model_r_squared = validation_result.get("model_r_squared", 0.0)
        analysis_plan = validation_result.get("analysis_plan", {})
        interpretation = validation_result.get("interpretation", {})

        # SQL 쿼리 수집
        sql_queries = []
        if verbose:
            print(f"  검증된 가설: {len(validated)}개 (R²: {model_r_squared:.3f})")
            for h in validated:
                data = h.validation_data or {}
                contrib_pct = data.get("contribution_pct", 0)
                rank = data.get("rank", 999)
                print(f"    - [{h.id}] {h.factor}: 기여도 {contrib_pct:.1f}% (#{rank}위)")

        # Step 3: 이벤트 매칭 (Scoring Algorithm)
        if verbose:
            print("\n[Step 3] 이벤트 매칭 중 (Scoring Algorithm)...")

        matched_events = {}
        try:
            matched_events = self.event_matcher.match(
                hypotheses=validated,
                region=region,
                period=period,  # 시간 근접성 계산용
                min_score=0.3,  # 0-1 스케일
                top_k=5
            )

            if verbose:
                for h_id, events in matched_events.items():
                    print(f"  [{h_id}] 매칭된 이벤트: {len(events)}개")
                    for ev in events[:3]:
                        print(f"    - {ev.event_name} (Score: {ev.total_score:.1f})")
                        if ev.sources:
                            print(f"      출처: {ev.sources[0].get('title', '')[:50]}...")

        except Exception as e:
            if verbose:
                print(f"  이벤트 매칭 오류: {e}")

        # Step 4: 결과 종합
        if verbose:
            print("\n[Step 4] 결과 종합 중...")

        result = AnalysisResult(
            question=question,
            kpi_change=kpi_change,  # KPI 변동 정보 추가
            hypotheses=hypotheses,
            validated_hypotheses=validated,
            matched_events=matched_events,
            sql_queries=sql_queries,
            # 3-Stage 결과 추가
            analysis_plan=analysis_plan,
            interpretation=interpretation,
            contributions=contributions,
            model_r_squared=model_r_squared
        )

        # 상세 분석 결과 구성
        result.details = self._build_details(validated, matched_events, sql_queries)

        # Step 5: 추론 기반 요약 생성 (출처 포함)
        if verbose:
            print("\n[Step 5] 추론 기반 답변 생성 중...")

        summary_result = self._generate_summary(
            question=question,
            details=result.details,
            kpi_change=kpi_change,
            matched_events=matched_events,
            validated_hypotheses=validated
        )
        result.summary = summary_result["summary"]
        result.sources = summary_result["sources"]

        if verbose:
            print(f"  출처 수: {len(result.sources)}개")
            print("\n" + "=" * 60)
            print("분석 완료!")
            print("=" * 60)

        return result

    def _build_details(
        self,
        validated: List[Hypothesis],
        matched_events: Dict[str, List[MatchedEvent]],
        sql_queries: List[Dict]
    ) -> List[Dict]:
        """상세 분석 결과 구성 (SQL/Graph 검증 타입 구분)"""
        details = []

        # SQL 쿼리를 hypothesis_id로 매핑
        sql_map = {q["hypothesis_id"]: q["sql"] for q in sql_queries}

        for hypothesis in validated:
            h_data = hypothesis.validation_data or {}

            # 검증 타입 확인 (sql 또는 graph)
            validation_type = h_data.get("validation_type", "sql")
            graph_evidence = h_data.get("graph_evidence", {})

            prev_val = h_data.get("previous_value", 0)
            curr_val = h_data.get("current_value", 0)
            change_pct = h_data.get("change_percent", 0)

            # 데이터 방향성 해석 (SQL 검증된 경우만)
            if validation_type == "sql" and (prev_val != 0 or curr_val != 0):
                # 음수값: 비용/손실 → 값이 커지면(덜 음수) 개선, 작아지면(더 음수) 악화
                # 양수값: 매출/이익 → 값이 커지면 개선, 작아지면 악화
                if prev_val < 0 and curr_val < 0:
                    if curr_val > prev_val:
                        interpretation = "개선 (손실/비용 감소)"
                        impact_direction = "positive"
                    else:
                        interpretation = "악화 (손실/비용 증가)"
                        impact_direction = "negative"
                elif prev_val >= 0 and curr_val >= 0:
                    if curr_val > prev_val:
                        interpretation = "증가"
                        impact_direction = "positive"
                    else:
                        interpretation = "감소"
                        impact_direction = "negative"
                else:
                    if curr_val > prev_val:
                        interpretation = "개선 (적자→흑자 또는 손실 감소)"
                        impact_direction = "positive"
                    else:
                        interpretation = "악화 (흑자→적자 또는 손실 증가)"
                        impact_direction = "negative"
            else:
                # Graph 검증인 경우: 인과관계 경로에서 해석
                interpretation = h_data.get("details", hypothesis.description)
                impact_direction = hypothesis.direction  # increase/decrease

            # QoQ/YoY 수치 가져오기
            qoq_pct = h_data.get("qoq_delta_pct", h_data.get("qoq_change_pct", change_pct))
            yoy_pct = h_data.get("yoy_delta_pct", h_data.get("yoy_change_pct", 0))
            alignment_type = h_data.get("alignment_type", "both")
            alignment_type_kr = h_data.get("alignment_type_kr", "")

            # 상세 결과 구성
            detail = {
                "factor": hypothesis.factor,
                "category": hypothesis.category,
                "description": hypothesis.description,
                "validation_type": validation_type,  # "sql" or "graph"
                "change_percent": change_pct,
                "qoq_change_pct": qoq_pct,
                "yoy_change_pct": yoy_pct,
                "alignment_type": alignment_type,
                "alignment_type_kr": alignment_type_kr,
                "previous_value": prev_val,
                "current_value": curr_val,
                "direction": h_data.get("direction", hypothesis.direction),
                "interpretation": interpretation,
                "impact_direction": impact_direction,
                "sql_query": sql_map.get(hypothesis.id, "") if validation_type == "sql" else "",
                "matched_events": [],
                # Graph 검증 시 인과관계 경로 포함
                "graph_evidence": graph_evidence if validation_type == "graph" else {},
                "causal_chains": graph_evidence.get("causal_chains", []) if validation_type == "graph" else []
            }

            # 매칭된 이벤트 추가 (Scoring Algorithm 결과)
            events = matched_events.get(hypothesis.id, [])
            for ev in events[:5]:
                detail["matched_events"].append({
                    "name": ev.event_name,
                    "category": ev.event_category,
                    "severity": ev.severity,
                    "impact": ev.impact_type,
                    "score": ev.total_score,
                    "score_breakdown": ev.score_breakdown,
                    "sources": ev.sources[:2],
                    "evidence": ev.evidence[:200] if ev.evidence else ""
                })

            details.append(detail)

        # 정렬: SQL 검증(수치 있음)은 변화율 순, Graph 검증은 이벤트 수 순
        def sort_key(d):
            if d["validation_type"] == "sql" and d["change_percent"] != 0:
                return (0, abs(d["change_percent"]))  # SQL 검증 우선, 변화율 순
            else:
                return (1, len(d.get("matched_events", [])))  # Graph는 이벤트 수 순

        details.sort(key=sort_key, reverse=True)

        return details

    def _get_representative_factor(self, factor_name: str) -> str:
        """Factor의 대표 그룹명 반환"""
        factor_lower = factor_name.lower().strip()
        for group_name, members in self.FACTOR_GROUPS.items():
            for member in members:
                if member.lower() in factor_lower or factor_lower in member.lower():
                    return group_name
        return factor_name  # 그룹에 없으면 원래 이름 반환

    def _select_top_factors(
        self,
        details: List[Dict],
        top_k: int = None
    ) -> List[Dict]:
        """
        유사 Factor 그룹화 후 Top K 선정

        선정 기준:
        1. 그룹별 대표 Factor 선정 (가장 높은 변화율)
        2. 이벤트 매칭 품질 (고품질 이벤트가 있는 Factor 우선)
        3. 변화율 크기 순 정렬
        """
        if top_k is None:
            top_k = self.TOP_K_FACTORS

        if not details:
            return []

        # 1. 그룹별로 Factor 분류
        group_map = {}  # group_name -> [details]
        for d in details:
            factor = d["factor"]
            group = self._get_representative_factor(factor)
            if group not in group_map:
                group_map[group] = []
            group_map[group].append(d)

        # 2. 각 그룹에서 대표 Factor 선정 (변화율 + 이벤트 품질)
        representatives = []
        for group_name, group_details in group_map.items():
            # 그룹 내 정렬: 이벤트 품질 → 변화율
            def score_detail(d):
                change_score = abs(d["change_percent"])
                # 고품질 이벤트 보너스 (score >= MIN_EVENT_SCORE)
                high_quality_events = [
                    e for e in d.get("matched_events", [])
                    if e.get("score", 0) >= self.MIN_EVENT_SCORE
                ]
                event_bonus = len(high_quality_events) * 10
                return change_score + event_bonus

            group_details.sort(key=score_detail, reverse=True)
            best = group_details[0]

            # 그룹 정보 추가
            best["group_name"] = group_name
            best["group_size"] = len(group_details)
            if len(group_details) > 1:
                best["related_factors"] = [d["factor"] for d in group_details[1:]]
            else:
                best["related_factors"] = []

            representatives.append(best)

        # 3. 대표 Factor들 중 Top K 선정
        def final_score(d):
            change_score = abs(d["change_percent"])
            high_quality_events = [
                e for e in d.get("matched_events", [])
                if e.get("score", 0) >= self.MIN_EVENT_SCORE
            ]
            event_bonus = len(high_quality_events) * 15
            return change_score + event_bonus

        representatives.sort(key=final_score, reverse=True)

        return representatives[:top_k]

    def _generate_summary(
        self,
        question: str,
        details: List[Dict],
        kpi_change: KPIChange = None,
        matched_events: Dict[str, List] = None,
        validated_hypotheses: List = None
    ) -> Dict[str, Any]:
        """추론 모델 기반 분석 요약 생성 (v4: 요인별 개별 LLM 호출)"""
        if not details and not kpi_change:
            return {
                "summary": "검증된 원인을 찾지 못했습니다.",
                "sources": []
            }

        # 1. Top K Factor 선정
        top_factors = self._select_top_factors(details, self.TOP_K_FACTORS)
        top_k = len(top_factors)

        # Top Factor가 없으면 원본 details 사용 (최대 K개)
        if not top_factors and details:
            top_factors = details[:self.TOP_K_FACTORS]
            top_k = len(top_factors)

        # 2. Driver별 이벤트 매핑 생성
        driver_events_map = self._build_driver_events_map_v2(matched_events, validated_hypotheses)

        # 3. 그룹별 요인 분류
        grouped = self._group_factors_by_type(top_factors)

        # 4. 도입부 생성 (1회 LLM 호출)
        intro = self._generate_intro(kpi_change, grouped)

        # 5. 그룹별 요인 분석 (요인별 개별 LLM 호출)
        group_order = ["Mix", "Volume", "Price", "Cost"]
        group_names_kr = {
            "Mix": "믹스 요인",
            "Volume": "물량 요인",
            "Price": "가격 요인",
            "Cost": "비용 요인"
        }

        # 모든 이벤트를 먼저 수집하여 전역 출처 번호를 할당
        all_sources = []
        event_url_to_idx = {}  # URL → 전역 번호 매핑

        for group_type in group_order:
            factors = grouped.get(group_type, [])
            for factor in factors:
                factor_name = factor.get('factor', '')
                group_name = factor.get('group_name', factor_name)
                factor_events = self._get_factor_events(factor_name, driver_events_map)
                if not factor_events:
                    factor_events = self._get_factor_events(group_name, driver_events_map)

                for ev in factor_events[:3]:  # 최대 3개 이벤트
                    sources = getattr(ev, 'sources', [])
                    if sources:
                        src = sources[0]
                        url = src.get('url', src.get('link', ''))
                        if url and url not in event_url_to_idx:
                            all_sources.append({
                                "idx": len(all_sources) + 1,
                                "title": src.get('title', '제목 없음'),
                                "url": url,
                                "event": getattr(ev, 'event_name', '')
                            })
                            event_url_to_idx[url] = len(all_sources)

        summary_parts = []
        summary_parts.append(f"## 분석 개요\n\n{intro}\n")

        factor_count = 0
        for group_type in group_order:
            factors = grouped.get(group_type, [])
            if not factors:
                continue

            section_content = f"\n## {group_names_kr[group_type]}\n"

            for factor in factors:
                factor_name = factor.get('factor', '')
                group_name = factor.get('group_name', factor_name)
                qoq = factor.get('qoq_change_pct', factor.get('change_percent', 0))
                yoy = factor.get('yoy_change_pct', 0)

                # 해당 요인에 매칭된 이벤트 가져오기
                factor_events = self._get_factor_events(factor_name, driver_events_map)
                if not factor_events:
                    factor_events = self._get_factor_events(group_name, driver_events_map)

                factor_count += 1

                # 개별 요인 분석에는 전역 출처 번호를 함께 전달한다.
                factor_analysis = self._generate_factor_analysis(
                    factor=factor,
                    kpi_change=kpi_change,
                    factor_events=factor_events,
                    question=question,
                    event_url_to_idx=event_url_to_idx  # 전역 번호 매핑 전달
                )

                # 본문에는 사전에 수집한 전역 출처 번호만 노출한다.
                event_refs = []
                for ev in factor_events[:3]:
                    sources = getattr(ev, 'sources', [])
                    if sources:
                        url = sources[0].get('url', sources[0].get('link', ''))
                        global_idx = event_url_to_idx.get(url, 0)
                        if global_idx and url:
                            event_refs.append(f"[[{global_idx}]]({url})")

                # 요인 헤더 (QoQ/YoY 수치 포함)
                qoq_dir = "↑" if qoq > 0 else "↓"
                yoy_dir = "↑" if yoy > 0 else "↓"
                section_content += f"\n### {group_name} (QoQ {qoq:+.1f}%{qoq_dir}, YoY {yoy:+.1f}%{yoy_dir})\n\n"
                section_content += factor_analysis + "\n"

                # 관련 이벤트 출처 표시 (전역 번호 사용)
                if event_refs:
                    section_content += f"\n*관련 이벤트: {', '.join(event_refs)}*\n"

            summary_parts.append(section_content)

        # 6. 결론 생성 (1회 LLM 호출)
        conclusion = self._generate_conclusion(kpi_change, grouped)
        summary_parts.append(conclusion)

        # 7. 최종 조합
        summary = "\n".join(summary_parts)

        # 8. 출처 섹션 추가
        if all_sources:
            summary += "\n\n---\n**출처:**\n"
            for src in all_sources:  # 본문에서 사용된 모든 번호에 해당하는 출처 표시
                summary += f"- [{src['idx']}] [{src['title']}]({src['url']})\n"

        return {
            "summary": summary or "분석 결과를 생성하지 못했습니다.",
            "sources": all_sources
        }

    def run(self, context: AgentContext) -> Dict[str, Any]:
        """Agent 실행"""
        question = context.query
        metadata = context.metadata or {}

        result = self.analyze(
            question=question,
            period=metadata.get("period", {"year": 2024, "quarter": 4}),
            region=metadata.get("region"),
            company=metadata.get("company", "LGE"),
            verbose=metadata.get("verbose", True)
        )

        return {
            "question": result.question,
            "kpi_change": {
                "kpi_name": result.kpi_change.kpi_name if result.kpi_change else None,
                "current_value": result.kpi_change.current_value if result.kpi_change else None,
                "current_period": result.kpi_change.current_period if result.kpi_change else None,
                "qoq_change_percent": result.kpi_change.qoq_change_percent if result.kpi_change else None,
                "yoy_change_percent": result.kpi_change.yoy_change_percent if result.kpi_change else None,
            } if result.kpi_change else None,
            "hypotheses_count": len(result.hypotheses),
            "validated_count": len(result.validated_hypotheses),
            "sql_queries": result.sql_queries,
            "matched_events_count": sum(len(v) for v in result.matched_events.values()),
            "summary": result.summary,
            "sources": result.sources,
            "details": result.details
        }

    def _calculate_kpi_change(
        self,
        question: str,
        period: Dict,
        region: str = None
    ) -> Optional[KPIChange]:
        """
        질문에서 KPI 추출 후 QoQ + YoY 변동 계산

        Args:
            question: 사용자 질문
            period: {"year": 2024, "quarter": 4}
            region: 지역 코드

        Returns:
            KPIChange (QoQ + YoY 포함) 또는 None
        """
        # 1. 질문에서 KPI 추출
        kpi_name = self._extract_kpi_from_question(question)
        kpi_info = self.KPI_PATTERNS.get(kpi_name)

        if not kpi_info:
            return None

        # 2. 기간 계산
        year = period.get("year", 2024)
        quarter = period.get("quarter", 4)

        curr_start, curr_end = self._get_quarter_date_range(year, quarter)

        # QoQ: 전분기 계산
        if quarter == 1:
            qoq_prev_year, qoq_prev_quarter = year - 1, 4  # Q1 → 전년 Q4
        else:
            qoq_prev_year, qoq_prev_quarter = year, quarter - 1  # Q2/Q3/Q4 → 같은해 이전분기

        qoq_prev_start, qoq_prev_end = self._get_quarter_date_range(qoq_prev_year, qoq_prev_quarter)

        # YoY: 전년 동기 계산
        yoy_prev_year, yoy_prev_quarter = year - 1, quarter
        yoy_prev_start, yoy_prev_end = self._get_quarter_date_range(yoy_prev_year, yoy_prev_quarter)

        # 3. 지역 필터 생성 (ORG_ID 기반)
        region_filter = ""
        region_filter_sales = ""  # 영업이익 쿼리용 (s. alias)
        if region:
            subsidiaries = self.REGION_SUBSIDIARY_MAP.get(region.upper(), [])
            if not subsidiaries:
                subsidiaries = self.REGION_SUBSIDIARY_MAP.get(region, [])
            if subsidiaries:
                subs_str = ", ".join([f"'{s}'" for s in subsidiaries])
                region_filter = f"AND ORG_ID IN ({subs_str})"
                region_filter_sales = f"AND s.ORG_ID IN ({subs_str})"

        # 4. SQL 쿼리 생성 - QoQ용
        qoq_sql_query = kpi_info["query_template"].format(
            prev_start=qoq_prev_start,
            prev_end=qoq_prev_end,
            curr_start=curr_start,
            curr_end=curr_end,
            region_filter=region_filter,
            region_filter_sales=region_filter_sales
        )

        # YoY용 SQL 쿼리
        yoy_sql_query = kpi_info["query_template"].format(
            prev_start=yoy_prev_start,
            prev_end=yoy_prev_end,
            curr_start=curr_start,
            curr_end=curr_end,
            region_filter=region_filter,
            region_filter_sales=region_filter_sales
        )

        # 5. SQL 실행 - QoQ
        try:
            qoq_result = self.sql_executor.execute(qoq_sql_query)

            if not qoq_result.success or qoq_result.data is None:
                print(f"QoQ KPI SQL 실행 실패: {qoq_result.error}")
                return None

            qoq_data = qoq_result.data.to_dict('records')
            qoq_prev_row = next((r for r in qoq_data if r.get('PERIOD') == 'Previous'), None)
            qoq_curr_row = next((r for r in qoq_data if r.get('PERIOD') == 'Current'), None)

            if not qoq_prev_row or not qoq_curr_row:
                print(f"QoQ 데이터 없음: prev={qoq_prev_row}, curr={qoq_curr_row}")
                return None

            qoq_prev_value = float(qoq_prev_row.get('TOTAL_VALUE', 0) or 0)
            curr_value = float(qoq_curr_row.get('TOTAL_VALUE', 0) or 0)

            if qoq_prev_value == 0:
                qoq_change_percent = 100.0 if curr_value > 0 else 0.0
            else:
                qoq_change_percent = ((curr_value - qoq_prev_value) / abs(qoq_prev_value)) * 100
            qoq_change_amount = curr_value - qoq_prev_value

            # 6. SQL 실행 - YoY
            yoy_result = self.sql_executor.execute(yoy_sql_query)

            if not yoy_result.success or yoy_result.data is None:
                print(f"YoY KPI SQL 실행 실패: {yoy_result.error}")
                # YoY 실패해도 QoQ만으로 계속
                yoy_prev_value = 0.0
                yoy_change_percent = 0.0
                yoy_change_amount = 0.0
            else:
                yoy_data = yoy_result.data.to_dict('records')
                yoy_prev_row = next((r for r in yoy_data if r.get('PERIOD') == 'Previous'), None)

                if yoy_prev_row:
                    yoy_prev_value = float(yoy_prev_row.get('TOTAL_VALUE', 0) or 0)
                    if yoy_prev_value == 0:
                        yoy_change_percent = 100.0 if curr_value > 0 else 0.0
                    else:
                        yoy_change_percent = ((curr_value - yoy_prev_value) / abs(yoy_prev_value)) * 100
                    yoy_change_amount = curr_value - yoy_prev_value
                else:
                    yoy_prev_value = 0.0
                    yoy_change_percent = 0.0
                    yoy_change_amount = 0.0

            region_text = region.upper() if region else "전체"
            current_period = f"{year}년 Q{quarter}"
            qoq_period_info = f"{year}년 Q{quarter} vs {qoq_prev_year}년 Q{qoq_prev_quarter} ({region_text})"
            yoy_period_info = f"{year}년 Q{quarter} vs {yoy_prev_year}년 Q{yoy_prev_quarter} ({region_text})"

            return KPIChange(
                kpi_name=kpi_name,
                current_value=curr_value,
                current_period=current_period,
                # QoQ
                qoq_previous_value=qoq_prev_value,
                qoq_change_percent=round(qoq_change_percent, 1),
                qoq_change_amount=qoq_change_amount,
                qoq_period_info=qoq_period_info,
                # YoY
                yoy_previous_value=yoy_prev_value,
                yoy_change_percent=round(yoy_change_percent, 1),
                yoy_change_amount=yoy_change_amount,
                yoy_period_info=yoy_period_info,
                # 기타
                region=region or "",
                sql_query=qoq_sql_query
            )

        except Exception as e:
            print(f"KPI 계산 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_kpi_from_question(self, question: str) -> str:
        """질문에서 KPI 추출"""
        question_lower = question.lower()

        for kpi_name, info in self.KPI_PATTERNS.items():
            for keyword in info["keywords"]:
                if keyword in question_lower:
                    return kpi_name

        # 기본값: 매출
        return "매출"

    def _extract_kpi_id(self, question: str) -> str:
        """질문에서 KPI ID 추출 (whitelist와 동일한 한글 키 사용)"""
        kpi_name = self._extract_kpi_from_question(question)

        # whitelist와 동일한 한글 키 반환 (kpi_driver_whitelist.json의 키와 일치해야 함)
        valid_kpi_ids = ["매출", "영업이익", "영업이익률", "판매량", "평균판매가", "OLED비중", "프리미엄비중"]

        # 한글 KPI 이름 정규화 (다양한 표현 → whitelist 키로 매핑)
        kpi_name_map = {
            "원가": "영업이익",       # 원가 질문 → 영업이익 분석으로 매핑
            "판매수량": "판매량",     # 판매수량 → 판매량
            "asp": "평균판매가",
            "oled": "OLED비중",
            "oled 비중": "OLED비중",
            "프리미엄": "프리미엄비중",
            "프리미엄 비중": "프리미엄비중"
        }

        # 정규화 시도
        normalized = kpi_name_map.get(kpi_name.lower(), kpi_name)

        # valid_kpi_ids에 있으면 그대로 반환, 없으면 "매출" 기본값
        return normalized if normalized in valid_kpi_ids else "매출"

    def _detect_question_focus(self, question: str) -> str:
        """
        질문에서 초점(QoQ/YoY/both)을 감지

        Args:
            question: 사용자 질문

        Returns:
            "qoq": 전분기 대비에 초점 (단기 변화)
            "yoy": 전년 대비에 초점 (장기 변화)
            "both": 둘 다 또는 불명확
        """
        # 명시적 기간 키워드
        qoq_keywords = ["전분기", "전 분기", "직전 분기", "지난 분기", "QoQ", "qoq"]
        yoy_keywords = ["전년", "작년", "전년도", "YoY", "yoy", "동기", "전년 동기"]

        # 단기 변화를 암시하는 키워드 (QoQ 초점)
        # "감소", "하락" 등은 일반적으로 최근 분기 변화에 대한 질문
        short_term_keywords = ["감소", "하락", "줄었", "떨어", "낮아", "악화", "부진"]

        question_lower = question.lower()

        has_qoq = any(kw.lower() in question_lower for kw in qoq_keywords)
        has_yoy = any(kw.lower() in question_lower for kw in yoy_keywords)
        has_short_term = any(kw in question for kw in short_term_keywords)

        # 명시적 기간 키워드 우선
        if has_qoq and not has_yoy:
            return "qoq"
        elif has_yoy and not has_qoq:
            return "yoy"
        # "감소", "하락" 등의 키워드가 있으면 QoQ 초점 (최근 변화에 대한 질문)
        elif has_short_term and not has_yoy:
            return "qoq"
        else:
            return "both"

    def _get_driver_type(self, factor_name: str, category: str = "") -> tuple:
        """
        Driver의 유형과 expected_sign을 반환

        Args:
            factor_name: Driver 이름
            category: Driver 카테고리

        Returns:
            (driver_type, expected_sign)
            - driver_type: "Volume", "Mix", "Price", "Cost", "Unknown"
            - expected_sign: "+" or "-"
        """
        factor_lower = factor_name.lower().replace(" ", "")

        # Volume 계열: 판매량, 출하량
        if any(kw in factor_lower for kw in ["판매량", "출하량", "수량"]):
            return ("Volume", "+")

        # Mix 계열: OLED 비중, 프리미엄 비중
        if any(kw in factor_lower for kw in ["oled비중", "프리미엄비중", "비중"]):
            return ("Mix", "+")

        # Price 계열: ASP, 할인율
        if any(kw in factor_lower for kw in ["asp", "평균판매가", "할인율"]):
            return ("Price", "+")

        # Cost 계열: 프로모션, 마케팅, 물류비
        if any(kw in factor_lower for kw in ["프로모션", "마케팅", "비용", "물류비", "인건비"]):
            return ("Cost", "-")

        # 기본값
        return ("Unknown", "+")

    def _group_factors_by_type(self, factors: List[Dict]) -> Dict[str, List[Dict]]:
        """요인을 Driver Type별로 그룹화"""
        groups = {
            "Mix": [],
            "Volume": [],
            "Price": [],
            "Cost": [],
            "Unknown": []
        }

        for f in factors:
            driver_type, _ = self._get_driver_type(f.get('factor', ''), f.get('category', ''))
            groups[driver_type].append(f)

        return groups

    def _classify_pattern(self, qoq_pct: float, yoy_pct: float, driver_type: str) -> str:
        """QoQ/YoY 변화와 Driver Type에 따른 패턴 분류"""
        qoq_up = qoq_pct > 0
        yoy_up = yoy_pct > 0

        if driver_type == "Cost" and qoq_up and yoy_up:
            return "비용 압박 패턴"
        elif driver_type in ["Volume", "Mix", "Price"] and qoq_up and yoy_up:
            return "구조적 성장 패턴"
        elif not qoq_up and yoy_up:
            return "단기 조정 + 장기 회복"
        elif qoq_up and not yoy_up:
            return "일시적 변동"
        else:  # not qoq_up and not yoy_up
            return "구조적 하락 가능성"

    def _format_factor_for_prompt(self, f: Dict, driver_events_map: Dict = None) -> str:
        """프롬프트용 요인 포맷 (그룹별 요약에서 사용)"""
        name = f.get('group_name', f.get('factor', ''))
        qoq = f.get('qoq_change_pct', f.get('change_percent', 0))
        yoy = f.get('yoy_change_pct', 0)
        driver_type, _ = self._get_driver_type(f.get('factor', ''))

        # 패턴 분류
        pattern = self._classify_pattern(qoq, yoy, driver_type)

        # 관련 이벤트 찾기
        related_events = "없음"
        factor_name = f.get('factor', '')
        if driver_events_map:
            events = driver_events_map.get(factor_name, [])
            if not events:
                events = driver_events_map.get(name, [])
            if events:
                event_names = [getattr(e, 'event_name', '') for e in events[:2] if getattr(e, 'event_name', '')]
                if event_names:
                    related_events = ", ".join(event_names)

        return f"""
**{name}**
- 전분기 대비 (QoQ): {qoq:+.1f}%
- 전년 대비 (YoY): {yoy:+.1f}%
- 패턴: {pattern}
- 관련 이벤트: {related_events}
"""

    def _build_grouped_factors_summary(self, grouped: Dict[str, List], driver_events_map: Dict = None) -> str:
        """그룹별 요인 요약 생성"""
        group_names_kr = {
            "Mix": "믹스 요인",
            "Volume": "물량 요인",
            "Price": "가격 요인",
            "Cost": "비용 요인"
        }

        order = ["Mix", "Volume", "Price", "Cost"]
        summary = ""

        for group_type in order:
            factors = grouped.get(group_type, [])
            if not factors:
                continue

            summary += f"\n### {group_names_kr[group_type]}\n"
            for f in factors:
                summary += self._format_factor_for_prompt(f, driver_events_map)

        if not summary:
            summary = "(분석된 요인 없음)"

        return summary

    def _build_driver_events_map_v2(
        self,
        matched_events: Dict[str, List],
        validated_hypotheses: List = None
    ) -> Dict[str, List]:
        """Driver별 이벤트 매핑 생성."""
        driver_events_map = {}

        if not matched_events:
            return driver_events_map

        # hypothesis.id를 factor명으로 역추적해 Event 매칭 결과를 안정화한다.
        h_id_to_factor = {}
        if validated_hypotheses:
            for h in validated_hypotheses:
                h_id_to_factor[h.id] = getattr(h, 'factor', '')

        for h_id, events in matched_events.items():
            factor_from_hypothesis = h_id_to_factor.get(h_id, '')

            for ev in events:
                ev_matched_factor = getattr(ev, 'matched_factor', '')

                # 우선순위: 1) ev.matched_factor, 2) hypothesis.factor
                matched_factor = ev_matched_factor or factor_from_hypothesis

                if not matched_factor:
                    continue

                # 원본 키로 저장 (Driver 이름)
                if matched_factor not in driver_events_map:
                    driver_events_map[matched_factor] = []
                driver_events_map[matched_factor].append(ev)

                # 공백 제거 정규화 버전도 저장 (매칭 용이성)
                factor_normalized = matched_factor.lower().strip().replace(" ", "")
                if factor_normalized and factor_normalized not in driver_events_map:
                    driver_events_map[factor_normalized] = []
                if factor_normalized:
                    driver_events_map[factor_normalized].append(ev)

                # 가설 factor 이름으로도 저장해 이후 요인별 조회에서 누락을 줄인다.
                if factor_from_hypothesis and factor_from_hypothesis != matched_factor:
                    if factor_from_hypothesis not in driver_events_map:
                        driver_events_map[factor_from_hypothesis] = []
                    if ev not in driver_events_map[factor_from_hypothesis]:
                        driver_events_map[factor_from_hypothesis].append(ev)

                    # 가설 factor의 정규화 버전도 저장
                    hypothesis_factor_normalized = factor_from_hypothesis.lower().strip().replace(" ", "")
                    if hypothesis_factor_normalized and hypothesis_factor_normalized not in driver_events_map:
                        driver_events_map[hypothesis_factor_normalized] = []
                    if hypothesis_factor_normalized and ev not in driver_events_map[hypothesis_factor_normalized]:
                        driver_events_map[hypothesis_factor_normalized].append(ev)

        return driver_events_map

    def _get_factor_events(self, factor_name: str, driver_events_map: Dict) -> List:
        """요인명으로 매칭된 이벤트 찾기 (정규화 매칭 포함)"""
        # 1. 직접 매칭
        events = driver_events_map.get(factor_name, [])
        if events:
            return events

        # 2. 공백 제거 정규화 매칭
        factor_normalized = factor_name.lower().strip().replace(" ", "")
        events = driver_events_map.get(factor_normalized, [])
        if events:
            return events

        # 3. 부분 매칭
        for key in driver_events_map:
            key_normalized = key.lower().strip().replace(" ", "")
            if factor_normalized in key_normalized or key_normalized in factor_normalized:
                return driver_events_map[key]

        return []

    def _generate_factor_analysis(
        self,
        factor: Dict,
        kpi_change: KPIChange,
        factor_events: List,
        question: str,
        event_url_to_idx: Dict[str, int] = None
    ) -> str:
        """개별 요인에 대한 LLM 분석 생성 (5가지 관점)"""

        # 요인 정보 추출
        factor_name = factor.get('group_name', factor.get('factor', ''))
        qoq = factor.get('qoq_change_pct', factor.get('change_percent', 0))
        yoy = factor.get('yoy_change_pct', 0)
        driver_type, _ = self._get_driver_type(factor.get('factor', ''), factor.get('category', ''))
        pattern = self._classify_pattern(qoq, yoy, driver_type)

        # KPI 정보
        kpi_name = kpi_change.kpi_name if kpi_change else "KPI"
        kpi_qoq = kpi_change.qoq_change_percent if kpi_change else 0
        kpi_yoy = kpi_change.yoy_change_percent if kpi_change else 0

        # 이벤트 정보 포맷팅 (전역 번호 사용)
        events_info = ""
        if factor_events and event_url_to_idx:
            for ev in factor_events[:3]:
                event_name = getattr(ev, 'event_name', '')
                evidence = getattr(ev, 'evidence', '')[:200] if getattr(ev, 'evidence', '') else ''
                sources = getattr(ev, 'sources', [])
                if event_name and sources:
                    url = sources[0].get('url', sources[0].get('link', ''))
                    global_idx = event_url_to_idx.get(url, 0)
                    if global_idx:
                        events_info += f"[{global_idx}] {event_name}: {evidence}\n"
        elif factor_events:
            # Fallback: 전역 번호 없으면 로컬 번호 사용
            for i, ev in enumerate(factor_events[:3], 1):
                event_name = getattr(ev, 'event_name', '')
                evidence = getattr(ev, 'evidence', '')[:200] if getattr(ev, 'evidence', '') else ''
                if event_name:
                    events_info += f"[{i}] {event_name}: {evidence}\n"

        if not events_info:
            events_info = "(관련 이벤트 없음)"

        prompt = f"""당신은 LG전자 HE사업부 경영 분석 전문가입니다.

## 분석 대상 요인: {factor_name}
- 전분기 대비 (QoQ): {qoq:+.1f}%
- 전년 대비 (YoY): {yoy:+.1f}%
- 패턴 분류: {pattern}

## KPI 변동 맥락: {kpi_name}
- QoQ: {kpi_qoq:+.1f}%
- YoY: {kpi_yoy:+.1f}%

## 관련 시장 이벤트
{events_info}

---

## 작성 요청

이 요인에 대해 **5가지 관점**으로 **5문장 이상** 작성하세요:

1. **QoQ 변화 분석**: 전분기 대비 변화의 의미와 방향성
2. **YoY 변화 분석**: 전년 대비 변화의 의미와 장기 추세
3. **시장 맥락**: 업계 전반의 흐름과 어떻게 연결되는지
4. **경쟁사/이벤트 연결**: 관련 이벤트를 인용하여 맥락적 연결 (인과 단정 금지)
5. **전략적 시사점**: 향후 검토할 포인트

## 규칙
- 인과 단정 금지 ("~때문이다", "원인이다" 등)
- 허용 표현: "함께 움직이는 경향", "맥락적으로 유사한 흐름"
- 이벤트 인용 시 출처 번호 [1], [2] 사용
- 자연스러운 문단 형태로 작성

## 응답 (5문장 이상):
"""

        try:
            result = self._call_responses_api_sync(
                prompt=prompt,
                model=self.REASONING_MODEL,
                max_tokens=600
            )
            return result
        except Exception as e:
            print(f"[AnalysisAgent] 요인 분석 LLM 호출 실패: {e}")
            # Fallback: 간단한 설명 반환
            qoq_dir = "증가" if qoq > 0 else "감소"
            yoy_dir = "증가" if yoy > 0 else "감소"
            return f"{factor_name}은(는) 전분기 대비 {abs(qoq):.1f}% {qoq_dir}, 전년 대비 {abs(yoy):.1f}% {yoy_dir}하였습니다. 이 패턴은 {pattern}으로 분류됩니다."

    def _generate_intro(self, kpi_change: KPIChange, grouped: Dict[str, List]) -> str:
        """도입부 생성 (KPI 요약 + 전체 패턴)"""
        if not kpi_change:
            return ""

        count_mix = len(grouped.get('Mix', []))
        count_volume = len(grouped.get('Volume', []))
        count_price = len(grouped.get('Price', []))
        count_cost = len(grouped.get('Cost', []))
        total = count_mix + count_volume + count_price + count_cost

        prompt = f"""2025년 3분기 {kpi_change.kpi_name} 분석 도입부를 작성하세요.

KPI 변동:
- 전분기 대비 (QoQ): {kpi_change.qoq_change_percent:+.1f}%
- 전년 대비 (YoY): {kpi_change.yoy_change_percent:+.1f}%

검증된 요인 수 (총 {total}개):
- 믹스 요인: {count_mix}개
- 물량 요인: {count_volume}개
- 가격 요인: {count_price}개
- 비용 요인: {count_cost}개

요청: 2-3문장으로 전체 상황을 요약하세요. 인과 단정 금지. 자연스러운 비즈니스 언어로 작성."""

        try:
            result = self._call_responses_api_sync(
                prompt=prompt,
                model=self.REASONING_MODEL,
                max_tokens=300
            )
            return result
        except Exception as e:
            print(f"[AnalysisAgent] 도입부 생성 실패: {e}")
            qoq_dir = "증가" if kpi_change.qoq_change_percent > 0 else "감소"
            yoy_dir = "증가" if kpi_change.yoy_change_percent > 0 else "감소"
            return f"2025년 3분기 {kpi_change.kpi_name}은(는) 전분기 대비 {abs(kpi_change.qoq_change_percent):.1f}% {qoq_dir}, 전년 대비 {abs(kpi_change.yoy_change_percent):.1f}% {yoy_dir}하였습니다. 총 {total}개의 요인이 분석되었습니다."

    def _generate_conclusion(self, kpi_change: KPIChange, grouped: Dict[str, List]) -> str:
        """결론 생성 (패턴 기반 정리)"""
        if not kpi_change:
            return ""

        # 그룹별 패턴 요약
        patterns_summary = []
        for group_type, factors in grouped.items():
            if not factors or group_type == "Unknown":
                continue
            for f in factors:
                qoq = f.get('qoq_change_pct', f.get('change_percent', 0))
                yoy = f.get('yoy_change_pct', 0)
                driver_type, _ = self._get_driver_type(f.get('factor', ''), f.get('category', ''))
                pattern = self._classify_pattern(qoq, yoy, driver_type)
                patterns_summary.append(f"{f.get('group_name', f.get('factor', ''))}: {pattern}")

        prompt = f"""분석 결론을 작성하세요.

KPI: {kpi_change.kpi_name}
- QoQ: {kpi_change.qoq_change_percent:+.1f}%
- YoY: {kpi_change.yoy_change_percent:+.1f}%

요인별 패턴:
{chr(10).join(patterns_summary[:5])}

요청: 2-3문장으로 패턴 기반 시사점을 정리하세요. 인과 단정 금지. 향후 모니터링 포인트 언급."""

        try:
            result = self._call_responses_api_sync(
                prompt=prompt,
                model=self.REASONING_MODEL,
                max_tokens=300
            )
            return "\n### 결론\n\n" + result
        except Exception as e:
            print(f"[AnalysisAgent] 결론 생성 실패: {e}")
            return "\n### 결론\n\n위 요인들의 변화 패턴을 종합적으로 모니터링하여 향후 추세를 파악하는 것이 필요합니다."

    def _format_factor_entry(
        self,
        d: dict,
        idx: int,
        driver_events_map: dict,
        category_kr_map: dict,
        kpi_qoq_direction: str,
        kpi_yoy_direction: str
    ) -> str:
        """요인 항목을 포맷팅하여 문자열로 반환 (패턴 분류 포함)"""
        group_name = d.get('group_name', d['factor'])
        factor_name = d['factor']
        category_kr = category_kr_map.get(d['category'], d['category'])
        interpretation = d.get('interpretation', d.get('direction', ''))
        causal_chains = d.get('causal_chains', [])

        # QoQ/YoY 수치
        qoq_pct = d.get('qoq_change_pct', d['change_percent'])
        yoy_pct = d.get('yoy_change_pct', 0)

        driver_type, expected_sign = self._get_driver_type(factor_name, d.get('category', ''))

        qoq_up = qoq_pct > 0
        yoy_up = yoy_pct > 0

        if driver_type == "Cost" and qoq_up and yoy_up:
            # Cost 계열이 모두 증가 → 비용 압박 패턴
            pattern_desc = "비용 압박 패턴"
        elif expected_sign == "+" and qoq_up and yoy_up:
            # Volume/Mix/Price 계열이 모두 증가 → 구조적 성장 패턴
            pattern_desc = "구조적 성장 패턴"
        elif not qoq_up and yoy_up:
            pattern_desc = "단기 조정 + 장기 회복"
        elif qoq_up and not yoy_up:
            pattern_desc = "일시적 변동"
        else:  # not qoq_up and not yoy_up
            pattern_desc = "구조적 하락 가능성"

        # 방향 텍스트
        qoq_direction = "증가" if qoq_up else "감소"
        yoy_direction = "증가" if yoy_up else "감소"

        # 관련 이벤트 찾기
        driver_events = driver_events_map.get(factor_name, [])
        if not driver_events:
            driver_events = driver_events_map.get(group_name, [])
        if not driver_events:
            for ev in d.get('matched_events', []):
                driver_events.append(type('Event', (), {
                    'event_name': ev.get('name', ''),
                    'total_score': ev.get('score', 0)
                })())

        event_refs = ""
        if driver_events:
            top_events = sorted(driver_events, key=lambda e: getattr(e, 'total_score', 0), reverse=True)[:2]
            event_names = [getattr(e, 'event_name', '') for e in top_events if getattr(e, 'event_name', '')]
            if event_names:
                event_refs = ", ".join(event_names)

        # 포맷팅 (요인별 통합 패턴)
        result = f"""
### {idx}. {group_name}
- 분류: {category_kr}
- 전분기 대비 (QoQ): {qoq_pct:+.1f}% ({qoq_direction})
- 전년 대비 (YoY): {yoy_pct:+.1f}% ({yoy_direction})
- 패턴 분류: {pattern_desc}
"""
        if event_refs:
            result += f"- 관련 이벤트: {event_refs}\n"

        if causal_chains:
            result += "- 맥락:\n"
            for chain in causal_chains[:2]:
                chain_text = chain.get('chain_text', '')
                if chain_text:
                    result += f"  - {chain_text}\n"
        elif interpretation:
            result += f"- 맥락: {interpretation}\n"

        return result

    def _get_quarter_date_range(self, year: int, quarter: int) -> tuple:
        """분기 시작/종료 날짜 계산 (DATE 형식: YYYY-MM-DD)"""
        quarter_dates = {
            1: ("01-01", "03-31"),
            2: ("04-01", "06-30"),
            3: ("07-01", "09-30"),
            4: ("10-01", "12-31")
        }
        start_date, end_date = quarter_dates[quarter]
        return f"{year}-{start_date}", f"{year}-{end_date}"
