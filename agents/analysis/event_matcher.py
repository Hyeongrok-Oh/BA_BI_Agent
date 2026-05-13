"""
Event Matcher Agent - 하이브리드 스코어링 (Vector + Graph)

개선된 버전:
- Factor-Event 직접 매칭 강화
- 가설별 고유 이벤트 우선
- 중복 이벤트 페널티
"""

import os
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field

from ..base import BaseAgent, AgentContext
from ..search_agent import SearchAgent
from .hypothesis_generator import Hypothesis


@dataclass
class MatchedEvent:
    """매칭된 이벤트"""
    event_id: str
    event_name: str
    event_category: str
    severity: str
    is_ongoing: bool
    # Driver 관계 (v2: AFFECTS 관계 기반)
    matched_factor: str       # driver_name
    driver_id: str = ""       # driver_id (v2)
    impact_type: str = ""     # INCREASES, DECREASES (polarity 기반 변환)
    polarity: int = 0         # +1 = INCREASES, -1 = DECREASES (v2)
    magnitude: str = "medium"
    weight: float = 0.5       # relationship weight (v2)
    # 매칭 점수
    total_score: float = 0.0
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    # 출처 (v2: 상세 정보 포함)
    sources: List[Dict] = field(default_factory=list)
    evidence: str = ""
    start_date: str = ""      # (v2)
    # Dimension 연결 (v2)
    target_regions: List[str] = field(default_factory=list)
    target_periods: List[str] = field(default_factory=list)  # (v2)
    dimensions: List[Dict] = field(default_factory=list)      # (v2)


# Magnitude 점수 매핑
MAGNITUDE_SCORES = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3
}

# Severity 점수 매핑
SEVERITY_SCORES = {
    "critical": 1.0,
    "high": 0.8,
    "medium": 0.5,
    "low": 0.2
}

# Factor → 관련 키워드 매핑 (정밀하게)
FACTOR_KEYWORD_MAP = {
    # 물류/운송
    "물류비": ["물류비", "물류"],
    "해상운임": ["해상운임", "운임", "해운"],
    "운송비": ["운송비", "운송"],
    # 원가
    "원재료비": ["원재료", "원자재", "재료비"],
    "패널가격": ["패널가격", "패널", "디스플레이"],
    "부품비": ["부품비", "부품"],
    # 가격/관세
    "관세": ["관세", "tariff", "section 232"],
    "환율": ["환율", "원달러", "달러"],
    "가격경쟁력": ["가격경쟁", "가격"],
    # 수요
    "TV수요": ["TV수요", "TV 수요", "가전수요"],
    "수요부진": ["수요부진", "수요 부진", "소비위축"],
    "소비심리": ["소비심리", "소비자심리"],
    # 경쟁
    "경쟁심화": ["경쟁심화", "경쟁 심화", "시장경쟁"],
    "시장점유율": ["점유율", "시장점유"],
    # 제품
    "OLED": ["OLED", "올레드"],
    "QNED": ["QNED", "퀴네드"],
    "프리미엄": ["프리미엄", "고급"],
    # 실적
    "실적": ["실적", "영업이익", "매출"],
    "수익성": ["수익성", "마진", "이익률"],
}


class EventMatcher(BaseAgent):
    """개선된 하이브리드 이벤트 매칭 에이전트

    v4: 3-Layer Hybrid Search 구조
    - Layer 1: Graph Filter (KPI/Driver/Region/Period 기반 필터링)
    - Layer 2: Vector Search (embedding cosine similarity)
    - Layer 3: Re-ranking (text_similarity + graph_score + time_proximity)
    """

    name = "event_matcher"
    description = "3-Layer Hybrid Search: Graph Filter → Vector Search → Re-ranking"

    # v7: 2-Layer Scoring + Direction Bonus
    RERANK_WEIGHTS = {
        "text_similarity": 0.70,  # Vector cosine similarity (70%)
        "graph_score": 0.30,      # 0.7×impact + 0.3×confidence (30%)
        "time_proximity": 0.00,   # 시간적 근접성 제외
    }
    DIRECTION_BONUS = 0.15  # 방향 일치 시 보너스 (+15%)

    # Legacy 호환용 가중치 (deprecated)
    WEIGHTS = {
        "semantic": 0.45,
        "graph": 0.35,
        "factor_match": 0.20,
    }

    def __init__(self, api_key: str = None):
        super().__init__(api_key)
        self.search_agent = SearchAgent(api_key)
        self.add_sub_agent(self.search_agent)
        self._openai_client = None
        self._used_events: Set[str] = set()  # 이미 사용된 이벤트 추적

    @property
    def openai_client(self):
        """Lazy OpenAI client initialization"""
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._openai_client

    def match(
        self,
        hypotheses: List[Hypothesis],
        region: str = None,
        period: Dict = None,  # v2: {"year": 2024, "quarter": 4}
        min_score: float = 0.3,
        top_k: int = 5
    ) -> Dict[str, List[MatchedEvent]]:
        """
        검증된 가설들에 대한 Event 매칭 (v2: AFFECTS 관계 기반)

        v2 개선사항:
        1. AFFECTS 관계 기반 Driver-Event 직접 매칭
        2. TARGETS 관계 기반 Region/TimePeriod 필터
        3. polarity (+1/-1) 기반 방향 매칭
        4. 가설별 고유 이벤트 우선 (중복 페널티)
        """
        results = {}
        self._used_events = set()  # 초기화

        # period를 TimePeriod ID로 변환 (예: "2025Q3")
        period_id = None
        if period:
            year = period.get("year")
            quarter = period.get("quarter")
            if year and quarter:
                period_id = f"{year}Q{quarter}"

        for hypothesis in hypotheses:
            if not hypothesis.validated:
                continue

            matched_events = self._match_single(hypothesis, region, period_id, min_score, top_k)
            if matched_events:
                results[hypothesis.id] = matched_events

                # 사용된 이벤트 기록
                for ev in matched_events:
                    self._used_events.add(ev.event_id)

        return results

    def _match_single(
        self,
        hypothesis: Hypothesis,
        region: str = None,
        period_id: str = None,  # v2: "2025Q3" 형식
        min_score: float = 0.3,
        top_k: int = 5
    ) -> List[MatchedEvent]:
        """단일 가설에 대한 Event 매칭 (v2: AFFECTS 관계 기반)"""

        # 1. Factor 키워드 추출 (정밀)
        factor_keywords = self._extract_factor_keywords_precise(hypothesis.factor)

        # 2. Graph Search: Driver와 직접 연결된 Event 검색 (v2: AFFECTS 관계)
        graph_results = self._graph_search_direct(hypothesis, factor_keywords, region, period_id)

        # 3. Vector Search: 항상 실행 (cosine similarity 계산용)
        hypothesis_embedding = self._get_embedding(hypothesis.description)
        vector_results = self._vector_search(hypothesis_embedding, top_k=15, region=region, period_id=period_id)

        # 4. 병합 및 스코어 계산
        all_events = self._merge_and_score_improved(
            hypothesis,
            factor_keywords,
            graph_results,
            vector_results,
            hypothesis_embedding,  # 직접 similarity 계산용
            region,
            period_id
        )

        # 5. 필터링, 중복 페널티 적용, 정렬
        scored_events = self._apply_uniqueness_bonus(all_events)
        filtered = [e for e in scored_events if e.total_score >= min_score]
        filtered.sort(key=lambda x: x.total_score, reverse=True)

        return filtered[:top_k]

    def _build_search_query(
        self,
        hypothesis: Hypothesis,
        region: str = None,
        period_id: str = None
    ) -> str:
        """Vector Search용 쿼리 문장 생성

        가설 + Driver + 기간 + 지역을 조합하여
        의미적으로 풍부한 검색 쿼리 생성

        예시 출력:
        "2025Q1 북미 지역에서 물류비가 증가하여 물류비 상승으로 인한 수익성 악화"
        """
        parts = []

        # 기간 정보
        if period_id:
            parts.append(f"{period_id}")

        # 지역 정보
        if region and region != "글로벌":
            parts.append(f"{region} 지역에서")

        # Driver/Factor 정보 + 방향
        if hypothesis.factor:
            direction = "증가" if hypothesis.direction == "increase" else "감소"
            parts.append(f"{hypothesis.factor}이(가) {direction}하여")

        # 가설 설명
        parts.append(hypothesis.description)

        return " ".join(parts)

    def _extract_factor_keywords_precise(self, factor: str) -> List[str]:
        """Factor에서 정밀한 검색 키워드 추출"""
        keywords = []
        factor_lower = factor.lower()

        # 정확한 매핑 우선
        for key, values in FACTOR_KEYWORD_MAP.items():
            if key.lower() in factor_lower or factor_lower in key.lower():
                keywords.extend(values)

        # 매핑에 없으면 원본 사용
        if not keywords:
            keywords = [factor]

        # 중복 제거
        return list(set(keywords))

    def _graph_search_direct(
        self,
        hypothesis: Hypothesis,
        factor_keywords: List[str],
        region: str = None,
        period_id: str = None  # v2: "2025Q3"
    ) -> List[Dict]:
        """Driver와 직접 연결된 Event 검색 (v2: AFFECTS 관계 기반)"""

        # v2: Region 필터 - 새로운 Dimension ID 사용 ("북미", "유럽" 등)
        region_filter = ""
        if region:
            normalized = self._normalize_region(region)
            if normalized:
                region_filter = f"""
                AND (
                    size(target_regions) = 0
                    OR '{normalized}' IN target_regions
                    OR '글로벌' IN target_regions
                )
                """

        # v2: Period 필터 - TimePeriod Dimension 사용
        period_filter = ""
        if period_id:
            period_filter = f"""
            AND (
                size(target_periods) = 0
                OR '{period_id}' IN target_periods
            )
            """

        # v2: AFFECTS 관계 기반 쿼리 (Driver 노드 사용)
        query = f"""
        MATCH (e:Event)-[r:AFFECTS]->(d:Driver)
        WHERE d.id IN $keywords
           OR any(kw IN $keywords WHERE toLower(d.name_kr) CONTAINS toLower(kw))
           OR any(kw IN $keywords WHERE toLower(d.id) CONTAINS toLower(kw))

        // Dimension 연결 조회 (Region, TimePeriod)
        OPTIONAL MATCH (e)-[:TARGETS]->(dim)
        WITH e, r, d,
             collect(DISTINCT CASE WHEN 'Region' IN labels(dim) OR dim.id IN ['북미', '유럽', '아시아', '한국', '중국', '중동', '글로벌'] THEN dim.id END) as target_regions,
             collect(DISTINCT CASE WHEN dim.id STARTS WITH '202' THEN dim.id END) as target_periods,
             collect(DISTINCT {{type: labels(dim)[0], id: dim.id}}) as dimensions
        WHERE true {region_filter} {period_filter}

        RETURN
            e.id as event_id,
            e.name as event_name,
            e.category as event_category,
            e.severity as event_severity,
            e.is_ongoing as is_ongoing,
            e.evidence as evidence,
            e.start_date as start_date,
            e.source_urls as source_urls,
            e.source_titles as source_titles,
            e.sources as sources,
            d.id as driver_id,
            d.name_kr as driver_name,
            r.polarity as polarity,
            r.weight as weight,
            CASE WHEN r.polarity > 0 THEN 'INCREASES' ELSE 'DECREASES' END as impact_type,
            COALESCE(r.weight, 0.5) as magnitude_weight,
            // v4: confidence 관련 필드 추가
            COALESCE(e.source_confidence, 0.8) as event_confidence,
            COALESCE(r.confidence, 0.8) as relation_confidence,
            COALESCE(r.impact_score, 0.5) as impact_score,
            target_regions,
            target_periods,
            dimensions,
            1.0 as factor_match_score,
            e.embedding as event_embedding
        ORDER BY
            CASE e.severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            abs(r.weight) DESC
        LIMIT 20
        """

        params = {"keywords": factor_keywords}

        try:
            result = self.search_agent.graph_tool.execute(query, params)
            if result.success and result.data:
                return result.data
        except Exception:
            pass

        return []

    def _get_embedding(self, text: str) -> List[float]:
        """텍스트를 embedding으로 변환"""
        try:
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return response.data[0].embedding
        except Exception:
            return []

    def _vector_search(
        self,
        query_embedding: List[float],
        top_k: int = 15,
        region: str = None,
        period_id: str = None  # v2
    ) -> List[Dict]:
        """Neo4j Vector Index로 유사 Event 검색 (v2: AFFECTS 관계 기반)"""
        if not query_embedding:
            return []

        # v2: Region 필터 조건 (새 Dimension ID 사용)
        region_filter = ""
        if region:
            normalized = self._normalize_region(region)
            if normalized:
                region_filter = f"""
                WHERE size(target_regions) = 0
                   OR '{normalized}' IN target_regions
                   OR '글로벌' IN target_regions
                """

        # v2: AFFECTS 관계 기반 Vector Search
        query = f"""
        CALL db.index.vector.queryNodes('event_embedding', $top_k, $embedding)
        YIELD node, score
        MATCH (node)-[r:AFFECTS]->(d:Driver)

        // Dimension 연결 조회
        OPTIONAL MATCH (node)-[:TARGETS]->(dim)
        WITH node, score, r, d,
             collect(DISTINCT CASE WHEN dim.id IN ['북미', '유럽', '아시아', '한국', '중국', '중동', '글로벌'] THEN dim.id END) as target_regions,
             collect(DISTINCT CASE WHEN dim.id STARTS WITH '202' THEN dim.id END) as target_periods
        {region_filter}
        RETURN
            node.id as event_id,
            node.name as event_name,
            node.category as event_category,
            node.severity as event_severity,
            node.is_ongoing as is_ongoing,
            node.evidence as evidence,
            node.start_date as start_date,
            node.source_urls as source_urls,
            node.source_titles as source_titles,
            node.sources as sources,
            d.id as driver_id,
            d.name_kr as driver_name,
            r.polarity as polarity,
            r.weight as weight,
            CASE WHEN r.polarity > 0 THEN 'INCREASES' ELSE 'DECREASES' END as impact_type,
            score as vector_score,
            // v4: confidence 관련 필드 추가
            COALESCE(node.source_confidence, 0.8) as event_confidence,
            COALESCE(r.confidence, 0.8) as relation_confidence,
            COALESCE(r.impact_score, 0.5) as impact_score,
            target_regions,
            target_periods
        """

        params = {
            "embedding": query_embedding,
            "top_k": top_k
        }

        try:
            result = self.search_agent.graph_tool.execute(query, params)
            if result.success and result.data:
                return result.data
        except Exception:
            pass

        return []

    def _merge_and_score_improved(
        self,
        hypothesis: Hypothesis,
        factor_keywords: List[str],
        graph_results: List[Dict],
        vector_results: List[Dict],
        hypothesis_embedding: List[float] = None,  # 직접 similarity 계산용
        region: str = None,
        period_id: str = None  # v2: "2025Q3" 형식
    ) -> List[MatchedEvent]:
        """개선된 병합 및 스코어 계산 (v2: AFFECTS 관계 기반)"""

        events_map = {}

        # Vector 결과를 먼저 맵으로 변환 (event_id → vector_score)
        vector_scores = {}
        for vr in vector_results:
            event_id = vr.get("event_id", "")
            if event_id:
                vector_scores[event_id] = vr.get("vector_score", 0)

        # Graph 결과 추가 (Vector score 병합 또는 직접 계산)
        for gr in graph_results:
            event_id = gr.get("event_id", "")
            if event_id:
                # Vector Search에서 찾았으면 그 점수 사용
                actual_vector_score = vector_scores.get(event_id, 0)

                # Vector에서 못 찾았으면 직접 cosine similarity 계산
                if actual_vector_score == 0 and hypothesis_embedding:
                    event_embedding = gr.get("event_embedding")
                    if event_embedding:
                        actual_vector_score = self._cosine_similarity(
                            hypothesis_embedding, event_embedding
                        )

                events_map[event_id] = {
                    **gr,
                    "from_graph": True,
                    "factor_match_score": 1.0,  # 직접 매칭
                    "vector_score": actual_vector_score  # 계산된 값 사용
                }

        # Vector 결과 추가 (Graph에 없는 것만)
        for vr in vector_results:
            event_id = vr.get("event_id", "")
            if event_id and event_id not in events_map:
                # v2: Driver 키워드 매칭 확인
                driver_name = vr.get("driver_name", "").lower()
                driver_match = any(kw.lower() in driver_name for kw in factor_keywords)

                events_map[event_id] = {
                    **vr,
                    "from_graph": False,
                    "factor_match_score": 0.7 if driver_match else 0.2,
                    "vector_score": vr.get("vector_score", 0)
                }

        # 각 이벤트에 대해 스코어 계산
        matched_events = []
        for event_id, event_data in events_map.items():
            score, breakdown = self._calculate_improved_score(
                hypothesis,
                event_data,
                region,
                period_id
            )

            # sources 구성
            sources = self._build_sources(event_data)

            # v2: polarity에서 magnitude 계산
            weight = event_data.get("weight", 0.5)
            magnitude = "high" if abs(weight) >= 0.7 else ("medium" if abs(weight) >= 0.4 else "low")

            matched_events.append(MatchedEvent(
                event_id=event_id,
                event_name=event_data.get("event_name", ""),
                event_category=event_data.get("event_category", ""),
                severity=event_data.get("event_severity", "medium"),
                is_ongoing=event_data.get("is_ongoing", False),
                # v2: driver_name 사용 (factor_name 대신)
                matched_factor=event_data.get("driver_name", "") or event_data.get("factor_name", ""),
                driver_id=event_data.get("driver_id", ""),
                impact_type=event_data.get("impact_type", ""),
                polarity=event_data.get("polarity", 0),
                magnitude=magnitude,
                weight=weight,
                total_score=score,
                score_breakdown=breakdown,
                sources=sources,
                evidence=event_data.get("evidence", ""),
                start_date=event_data.get("start_date", ""),
                target_regions=event_data.get("target_regions", []),
                target_periods=event_data.get("target_periods", []),
                dimensions=event_data.get("dimensions", [])
            ))

        return matched_events

    def _calculate_improved_score(
        self,
        hypothesis: Hypothesis,
        event_data: Dict,
        region: str = None,
        period_id: str = None  # v2: "2025Q3" 형식
    ) -> tuple:
        """
        v4: 3-Layer Hybrid Search 스코어 계산

        Final Score = 0.45 × Text_Similarity + 0.35 × Graph_Score + 0.20 × Time_Proximity

        Graph Score = 0.7 × Impact_Score + 0.3 × Confidence
        """
        breakdown = {}

        # === 1. Text Similarity (65%) - Vector cosine similarity ===
        vector_score = event_data.get("vector_score", 0)
        # Graph에서 왔지만 Vector Search에서 못 찾은 경우
        if vector_score == 0 and event_data.get("from_graph"):
            # Graph 직접 매칭은 factor_match_score 기반으로 추정
            factor_match = event_data.get("factor_match_score", 0.5)
            vector_score = factor_match * 0.8  # 직접 매칭 = 높은 관련성
        breakdown["text_similarity"] = round(vector_score, 3)

        # === 2. Graph Score (35%) = 0.7 × Impact + 0.3 × Confidence ===
        impact_score = self._calc_impact_score(event_data)
        confidence_score = self._calc_confidence_score(event_data)
        graph_score = 0.7 * impact_score + 0.3 * confidence_score
        breakdown["impact_score"] = round(impact_score, 3)
        breakdown["confidence"] = round(confidence_score, 3)
        breakdown["graph_score"] = round(graph_score, 3)

        # === 3. Direction Match - Polarity 일치 여부 ===
        direction_score = self._calc_direction_score(hypothesis, event_data)
        breakdown["direction_match"] = round(direction_score, 3)

        # === 4. Final Score (v7: Base + Direction Bonus) ===
        base_score = (
            vector_score * self.RERANK_WEIGHTS["text_similarity"] +
            graph_score * self.RERANK_WEIGHTS["graph_score"]
        )

        # 방향 일치 시 보너스 추가
        direction_bonus = self.DIRECTION_BONUS if direction_score >= 0.8 else 0
        final_score = min(base_score + direction_bonus, 1.0)  # 최대 1.0

        breakdown["base_score"] = round(base_score, 3)
        breakdown["direction_bonus"] = round(direction_bonus, 3)
        breakdown["final"] = round(final_score, 3)

        # Legacy breakdown 호환 (디버깅/로깅용)
        breakdown["semantic"] = breakdown["text_similarity"]
        breakdown["graph"] = breakdown["graph_score"]

        return final_score, breakdown

    def _calc_impact_score(self, event_data: Dict) -> float:
        """
        v4: Impact Score 계산

        impact_score = severity_weight × magnitude_weight
        - DB에 저장된 impact_score 우선 사용
        - 없으면 severity × weight로 계산
        """
        # DB에서 미리 계산된 impact_score가 있으면 사용
        stored_impact = event_data.get("impact_score", 0)
        if stored_impact and stored_impact > 0:
            return min(stored_impact, 1.0)

        # 없으면 직접 계산
        severity = event_data.get("event_severity", "medium")
        severity_weight = SEVERITY_SCORES.get(severity, 0.5)

        weight = abs(event_data.get("weight", 0.5))
        magnitude_weight = min(weight, 1.0)

        return severity_weight * magnitude_weight

    def _calc_confidence_score(self, event_data: Dict) -> float:
        """
        v4: Confidence Score 계산 (정보 출처 신뢰도)

        - relation_confidence: Event-Driver 연결의 신뢰도
        - event_confidence: Event 자체의 출처 신뢰도
        - 둘의 평균 또는 relation_confidence 우선
        """
        relation_conf = event_data.get("relation_confidence", 0.8)
        event_conf = event_data.get("event_confidence", 0.8)

        # relation_confidence가 있으면 우선 사용
        if relation_conf and relation_conf > 0:
            return min(relation_conf, 1.0)

        # 없으면 event_confidence 사용
        if event_conf and event_conf > 0:
            return min(event_conf, 1.0)

        return 0.8  # 기본값

    def _calc_time_proximity(self, event_data: Dict, analysis_period: str) -> float:
        """
        v4: 시간적 근접성 계산

        - 분석 기간 내 발생: 1.0
        - 1분기 전/후: 0.8
        - 2분기 전/후: 0.5
        - 그 외: 0.2
        """
        if not analysis_period:
            return 0.5  # 기간 미지정 시 중간값

        target_periods = event_data.get("target_periods", [])
        # None 필터링
        target_periods = [p for p in target_periods if p]

        if not target_periods:
            return 0.5  # 이벤트에 기간 지정 없음

        # 정확한 기간 일치 (예: "2025Q3")
        if analysis_period in target_periods:
            return 1.0

        # 인접 분기 체크
        try:
            if len(analysis_period) >= 5:  # "2025Q3" 형식
                year = int(analysis_period[:4])
                quarter = int(analysis_period[5])

                for tp in target_periods:
                    if tp and len(tp) >= 5:
                        tp_year = int(tp[:4])
                        tp_quarter = int(tp[5])

                        # 분기 차이 계산
                        total_quarters = (year - tp_year) * 4 + (quarter - tp_quarter)
                        abs_diff = abs(total_quarters)

                        if abs_diff == 1:
                            return 0.8  # 1분기 전/후
                        elif abs_diff == 2:
                            return 0.5  # 2분기 전/후
                        elif abs_diff <= 4:
                            return 0.3  # 1년 이내
        except (ValueError, IndexError):
            pass

        # 연도만 일치하는 경우
        if analysis_period and len(analysis_period) >= 4:
            year = analysis_period[:4]
            for tp in target_periods:
                if tp and tp.startswith(year):
                    return 0.6  # 같은 연도

        return 0.2  # 불일치

    def _apply_uniqueness_bonus(self, events: List[MatchedEvent]) -> List[MatchedEvent]:
        """
        이미 다른 가설에서 사용된 이벤트에 페널티 적용
        새로운 이벤트에 보너스 적용
        """
        for event in events:
            if event.event_id in self._used_events:
                # 중복 이벤트: 15% 페널티
                event.total_score *= 0.85
                event.score_breakdown["uniqueness_penalty"] = -0.15
            else:
                # 고유 이벤트: 10% 보너스
                event.total_score *= 1.10
                event.total_score = min(event.total_score, 1.0)  # 최대 1.0
                event.score_breakdown["uniqueness_bonus"] = 0.10

        return events

    def _calc_direction_score(self, hypothesis: Hypothesis, event_data: Dict) -> float:
        """방향 일치 점수 계산 (v3: 실제 관측 방향 기반)"""
        # v3: 실제 관측된 방향 사용 (validation_data에서)
        validation_data = hypothesis.validation_data or {}
        delta_pct = validation_data.get("delta_pct", 0)

        # 실제 변화 방향 결정
        if delta_pct > 0:
            actual_direction = "increase"
        elif delta_pct < 0:
            actual_direction = "decrease"
        else:
            actual_direction = hypothesis.direction.lower()  # fallback

        # 방향 매칭 (간소화)
        polarity = event_data.get("polarity", 0)

        if actual_direction == "increase":
            # Driver가 실제 증가 → 증가시키는 이벤트 매칭
            return 1.0 if polarity > 0 else 0.0
        elif actual_direction == "decrease":
            # Driver가 실제 감소 → 감소시키는 이벤트 매칭
            return 1.0 if polarity < 0 else 0.0

        return 0.5  # polarity가 0이거나 알 수 없는 경우

    def _calc_region_score(self, event_data: Dict, region: str) -> float:
        """지역 일치 점수 계산 (v2: 한글 Dimension ID 사용)"""
        if not region:
            return 0.7  # 지역 미지정 시 중간 점수

        target_regions = event_data.get("target_regions", [])
        # None 필터링
        target_regions = [r for r in target_regions if r]

        if not target_regions:
            return 0.5  # 이벤트에 지역 지정 없음 = 글로벌/미지정

        normalized_region = self._normalize_region(region)
        if not normalized_region:
            return 0.5

        # v2: 한글 Dimension ID로 직접 비교 (북미, 유럽, 글로벌 등)
        if normalized_region in target_regions:
            return 1.0

        # 글로벌은 모든 지역과 부분 일치
        if "글로벌" in target_regions:
            return 0.7

        return 0.2  # 불일치

    def _calc_period_score(self, event_data: Dict, period_id: str) -> float:
        """시간 일치 점수 계산 (v2: TimePeriod Dimension 사용)"""
        if not period_id:
            return 0.7  # 기간 미지정 시 중간 점수

        target_periods = event_data.get("target_periods", [])
        # None 필터링
        target_periods = [p for p in target_periods if p]

        if not target_periods:
            return 0.5  # 이벤트에 기간 지정 없음

        # 정확한 기간 일치 (예: "2025Q3")
        if period_id in target_periods:
            return 1.0

        # 연도 또는 반기 단위 부분 일치
        # 예: "2025Q3"는 "2025H2", "2025"와 부분 일치
        if period_id and len(period_id) >= 4:
            year = period_id[:4]
            # 연도 일치 체크
            for tp in target_periods:
                if tp and tp.startswith(year):
                    return 0.7  # 같은 연도

        return 0.3  # 불일치

    def _normalize_region(self, region: str) -> Optional[str]:
        """지역 코드 정규화 (v2: 새 Dimension ID 사용)"""
        if not region:
            return None

        region_upper = region.upper()
        # v2: 새 Dimension ID로 매핑 ("북미", "유럽" 등)
        mapping = {
            "NA": "북미", "NORTH AMERICA": "북미", "북미": "북미",
            "EU": "유럽", "EUROPE": "유럽", "유럽": "유럽",
            "KR": "한국", "KOREA": "한국", "한국": "한국",
            "ASIA": "아시아", "아시아": "아시아",
            "CN": "중국", "CHINA": "중국", "중국": "중국",
            "ME": "중동", "MIDDLE EAST": "중동", "중동": "중동",
            "GLOBAL": "글로벌", "글로벌": "글로벌",
        }
        return mapping.get(region_upper, region)

    def _build_sources(self, event_data: Dict) -> List[Dict]:
        """출처 정보 구성"""
        sources = []
        source_urls = event_data.get("source_urls", []) or []
        source_titles = event_data.get("source_titles", []) or []
        event_name = event_data.get("event_name", "")

        for i, url in enumerate(source_urls[:3]):
            if url:
                title = source_titles[i] if i < len(source_titles) else event_name
                sources.append({"url": url, "title": title, "link": url})

        return sources

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """코사인 유사도 계산"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        import math
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def run(self, context: AgentContext) -> Dict[str, Any]:
        """Agent 실행 (v2: period 파라미터 추가)"""
        hypotheses = context.metadata.get("validated_hypotheses", [])
        region = context.metadata.get("region")
        period = context.metadata.get("period")  # v2: {"year": 2024, "quarter": 4}
        min_score = context.metadata.get("min_score", 0.3)
        top_k = context.metadata.get("top_k", 5)

        matched = self.match(
            hypotheses=hypotheses,
            region=region,
            period=period,
            min_score=min_score,
            top_k=top_k
        )

        # MatchedEvent를 직렬화 가능한 형태로 변환 (v2: 필드 추가)
        serialized = {}
        for h_id, events in matched.items():
            serialized[h_id] = [
                {
                    "event_id": ev.event_id,
                    "event_name": ev.event_name,
                    "event_category": ev.event_category,
                    "severity": ev.severity,
                    "impact_type": ev.impact_type,
                    "polarity": ev.polarity,
                    "matched_factor": ev.matched_factor,
                    "driver_id": ev.driver_id,
                    "weight": ev.weight,
                    "total_score": ev.total_score,
                    "score_breakdown": ev.score_breakdown,
                    "sources": ev.sources[:2],
                    "evidence": ev.evidence[:200] if ev.evidence else "",
                    "start_date": ev.start_date,
                    "target_regions": ev.target_regions,
                    "target_periods": ev.target_periods
                }
                for ev in events
            ]

        result = {
            "matched_events": matched,
            "matched_serialized": serialized,
            "hypothesis_count": len(matched),
            "total_events": sum(len(v) for v in matched.values())
        }

        context.add_step("event_matching", {
            "hypothesis_count": len(matched),
            "total_events": sum(len(v) for v in matched.values())
        })

        return result
