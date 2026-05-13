"""Event 추출 - LLM 기반 Event-Factor 관계 추출"""

import json
import os
import re
from typing import List, Optional
from datetime import datetime, date
from dataclasses import dataclass

from .models import (
    EventNode, EventFactorRelation, EventDimensionRelation,
    EventSource, EventCategory, ImpactType, Severity, Layer3Graph
)
from .search_client import SearchResult
from .config import CORE_DRIVERS, DIMENSIONS


# Dimension ID 매핑 (LLM이 shorthand를 반환할 경우 정규 ID로 변환)
DIMENSION_ID_MAPPING = {
    # Region shorthand → 정규 ID
    "NA": "북미",
    "EU": "유럽",
    "ASIA": "아시아",
    "KR": "한국",
    "CN": "중국",
    "ME": "중동",
    "GLOBAL": "글로벌",
    # ProductCategory shorthand → 정규 ID
    "OLED": "OLED_TV",
    "LCD": "LCD_TV",
    "QNED": "LCD_TV",  # QNED는 LCD_TV로 매핑
    "PREMIUM": "프리미엄_TV",
    "LARGE": "대형_TV",
    # TimePeriod shorthand → 정규 ID (2025년 기준)
    "Q1": "2025Q1",
    "Q2": "2025Q2",
    "Q3": "2025Q3",
    "Q4": "2025Q4",
    "H1": "2025H1",
    "H2": "2025H2",
}


def normalize_dimension_id(dim_id: str, dim_type: str = None) -> str:
    """Shorthand Dimension ID를 정규 ID로 변환

    Args:
        dim_id: 원본 dimension ID (예: "NA", "OLED", "Q3")
        dim_type: dimension 타입 (Region, ProductCategory, TimePeriod) - 현재 미사용

    Returns:
        정규화된 dimension ID (예: "북미", "OLED_TV", "2025Q3")
    """
    if not dim_id:
        return dim_id
    return DIMENSION_ID_MAPPING.get(dim_id.upper(), dim_id)


# Event 추출 프롬프트 (기본 - Driver 연결 포함)
EVENT_EXTRACTION_PROMPT = """다음 뉴스 검색 결과에서 LG전자 TV(HE) 사업에 영향을 미치는 **구체적인 이벤트**를 추출하세요.

**검색 결과:**
{search_results}

**추출 규칙:**
1. **이벤트 정의**: 구체적이고 시간이 특정된 외부 사건/상황만 추출
   - O: "홍해 후티 반군 공격", "트럼프 25% 보편관세 발표", "BOE 8.6세대 OLED 양산 시작"
   - X: "물류비 상승", "패널원가 증가", "경쟁 심화" (이것은 Driver/결과이지 Event가 아님)

2. **Event → Driver 인과관계 (매우 중요)**:
   - Event는 외부 사건/상황 (원인)
   - Driver는 비즈니스 지표 (결과)
   - **Event가 Driver에 영향을 주는 방향만 유효**

   ✅ 올바른 예시:
   - "홍해 후티 반군 공격" → 물류비 INCREASES (공격으로 우회 항로 → 물류비 증가)
   - "중국 LCD 패널 공급 과잉" → 패널원가 DECREASES (공급 과잉 → 가격 하락)
   - "BOE 8.6세대 OLED 양산" → 경쟁사점유율 INCREASES (경쟁사 생산 증가)

   ❌ 잘못된 예시 (추출하지 마세요):
   - "물류비 상승" → X (물류비 자체는 Driver, Event가 아님)
   - "패널원가 증가" → X (패널원가 자체는 Driver, Event가 아님)
   - "매출 감소" → X (매출은 KPI, Event가 아님)

3. TV/가전 사업에 직접/간접적으로 영향이 있는 이벤트만
4. **중요**: 각 이벤트의 출처가 된 검색 결과 번호를 source_indices에 명시

5. **Confidence (정보 출처 신뢰도) 판단 - 5단계:**
   - 1.0: 공식 발표, 정부 기관, 대형 언론사(로이터, 블룸버그, AP) 확인된 사실
   - 0.8: 신뢰할 수 있는 경제 전문지 (Bloomberg, Reuters, 한경, 매경, WSJ 등)
   - 0.6: 일반 뉴스 매체, 업계 소식
   - 0.4: 블로그, 소셜 미디어, 미확인 소식
   - 0.2: 추측성 기사, 루머, 익명 소스

**영향 받는 Driver 후보:**
{drivers}

**타겟 Dimension (반드시 아래 정확한 ID 사용, 축약형 금지!):**
- Region: "북미", "유럽", "아시아", "한국", "중국", "중동", "글로벌" (NA/EU/ASIA 사용 금지)
- ProductCategory: "OLED_TV", "LCD_TV", "프리미엄_TV", "대형_TV", "TV_전체" (OLED/LCD 사용 금지)
- TimePeriod: "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2025H1", "2025H2", "2025" (Q3/Q4 사용 금지)

**응답 형식 (JSON):**
```json
{{
  "events": [
    {{
      "name": "이벤트명 (한글, 구체적 사건)",
      "name_en": "Event name (English)",
      "category": "geopolitical|policy|market|company|macro_economy|technology|natural",
      "start_date": "YYYY-MM-DD 또는 null",
      "is_ongoing": true/false,
      "severity": "low|medium|high|critical",
      "confidence": 0.8,
      "confidence_reasoning": "출처 신뢰도 판단 근거 (예: Bloomberg 보도, 공식 발표 인용)",
      "source_indices": [1, 3],
      "affected_drivers": [
        {{"driver": "Driver명", "impact": "INCREASES|DECREASES", "magnitude": "low|medium|high", "reasoning": "인과관계 설명"}}
      ],
      "target_dimensions": [
        {{"dimension_id": "북미", "dimension_type": "Region", "specificity": "high|medium|low"}},
        {{"dimension_id": "OLED_TV", "dimension_type": "ProductCategory", "specificity": "high|medium|low"}},
        {{"dimension_id": "2025Q3", "dimension_type": "TimePeriod", "specificity": "high|medium|low"}}
      ],
      "evidence": "영향 근거 (뉴스 snippet에서 발췌)"
    }}
  ]
}}
```

**source_indices 작성 규칙 (필수):**
1. 각 이벤트마다 반드시 source_indices를 명시해야 합니다
2. 정수 배열만 허용: [1, 3] (문자열 "1", 실수 1.0 금지)
3. 범위: 1부터 검색결과 개수까지만 유효
4. 해당 뉴스가 없으면 빈 배열: []
5. **이벤트 내용이 실제로 해당 뉴스에 있는지 반드시 확인**

**예시:**
- 뉴스 [1], [3]에서 같은 이벤트 추출: "source_indices": [1, 3]
- 뉴스 [2]에만 해당: "source_indices": [2]
- 뉴스에 없으면: "source_indices": []

이벤트가 없으면: {{"events": []}}
"""

# 순수 Event 추출 프롬프트 (Driver 연결 없이)
PURE_EVENT_EXTRACTION_PROMPT = """다음 뉴스 검색 결과에서 LG전자 TV(HE) 사업에 영향을 미칠 수 있는 **실제 발생한 이벤트**를 추출하세요.

**검색 결과:**
{search_results}

**추출 규칙 (매우 중요!):**

1. **실제 일어난 일만 추출**:
   ✅ 추출 대상 (실제 발생한 사건):
   - "삼성전자, CES 2025에서 마이크로LED TV 출시" (실제 출시)
   - "홍해 후티 반군, 화물선 공격" (실제 사건)
   - "중국 BOE, 8.6세대 OLED 양산 시작" (실제 양산)
   - "트럼프, 25% 관세 부과 행정명령 서명" (실제 서명)
   - "해상운임 20% 상승" (실제 상승)

   ❌ 제외 대상 (추측/논의/계획):
   - "~할 전망", "~할 것으로 예상", "~할 계획"
   - "~에 대해 논의", "~를 검토 중", "~를 추진 중"
   - "~할 가능성", "~할 수도 있다", "~할 것으로 보인다"
   - 애널리스트/전문가 예측, 시장 전망 기사
   - "~를 발표할 예정", "~를 준비 중"

2. **날짜 필수**: 이벤트 발생 날짜가 명확해야 함 (start_date 필수)

3. TV/가전 사업에 직접/간접적으로 영향이 있는 이벤트만

4. 각 이벤트의 출처가 된 검색 결과 번호를 source_indices에 명시

5. **Confidence (정보 출처 신뢰도) 판단 - 5단계:**
   - 1.0: 공식 발표, 정부 기관, 대형 언론사(로이터, 블룸버그, AP) 확인된 사실
   - 0.8: 신뢰할 수 있는 경제 전문지 (Bloomberg, Reuters, 한경, 매경, WSJ 등)
   - 0.6: 일반 뉴스 매체, 업계 소식
   - 0.4: 블로그, 소셜 미디어, 미확인 소식
   - 0.2: 추측성 기사, 루머, 익명 소스

**타겟 Dimension (반드시 아래 정확한 ID 사용, 축약형 금지!):**
- Region: "북미", "유럽", "아시아", "한국", "중국", "중동", "글로벌" (NA/EU/ASIA 사용 금지)
- ProductCategory: "OLED_TV", "LCD_TV", "프리미엄_TV", "대형_TV", "TV_전체" (OLED/LCD 사용 금지)
- TimePeriod: "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2025H1", "2025H2", "2025" (Q3/Q4 사용 금지)

**응답 형식 (JSON):**
```json
{{
  "events": [
    {{
      "name": "이벤트명 (한글, 실제 발생한 사건)",
      "name_en": "Event name (English)",
      "category": "geopolitical|policy|market|company|macro_economy|technology|natural",
      "start_date": "YYYY-MM-DD (필수!)",
      "is_ongoing": true/false,
      "severity": "low|medium|high|critical",
      "confidence": 0.8,
      "confidence_reasoning": "출처 신뢰도 판단 근거 (예: Bloomberg 보도, 공식 발표 인용)",
      "source_indices": [1, 3],
      "target_dimensions": [
        {{"dimension_id": "북미", "dimension_type": "Region", "specificity": "high|medium|low"}},
        {{"dimension_id": "OLED_TV", "dimension_type": "ProductCategory", "specificity": "high|medium|low"}},
        {{"dimension_id": "2025Q3", "dimension_type": "TimePeriod", "specificity": "high|medium|low"}}
      ],
      "evidence": "실제 발생한 내용 요약 (뉴스 snippet에서 발췌)"
    }}
  ]
}}
```

**주의**:
- Driver 연결은 별도 단계에서 수행됩니다.
- 추측/전망/논의 기사는 절대 추출하지 마세요.
- 날짜가 불명확한 이벤트는 추출하지 마세요.

이벤트가 없으면: {{"events": []}}
"""

# Driver 기반 검색용 프롬프트 (source_driver 활용)
DRIVER_BASED_EXTRACTION_PROMPT = """다음 뉴스 검색 결과에서 LG전자 TV(HE) 사업에 영향을 미치는 **구체적인 이벤트**를 추출하세요.

**중요**: 이 뉴스들은 "{source_driver}" Driver 관련 검색으로 수집되었습니다.

**검색 결과:**
{search_results}

**추출 규칙:**
1. **이벤트 정의**: 구체적이고 시간이 특정된 외부 사건/상황만 추출
   - O: "홍해 후티 반군 공격", "트럼프 25% 보편관세 발표", "BOE 8.6세대 OLED 양산 시작"
   - X: "물류비 상승", "패널원가 증가", "경쟁 심화" (이것은 Driver/결과이지 Event가 아님)

2. **Event → Driver 인과관계 (매우 중요)**:
   - Event는 외부 사건/상황 (원인)
   - Driver는 비즈니스 지표 (결과)
   - **Event가 Driver에 영향을 주는 방향만 유효**

   ✅ 올바른 예시:
   - "홍해 후티 반군 공격" → 물류비 INCREASES (공격으로 우회 항로 → 물류비 증가)
   - "중국 LCD 패널 공급 과잉" → 패널원가 DECREASES (공급 과잉 → 가격 하락)
   - "BOE 8.6세대 OLED 양산" → 경쟁사점유율 INCREASES (경쟁사 생산 증가)

   ❌ 잘못된 예시 (추출하지 마세요):
   - "물류비 상승" → X (물류비 자체는 Driver, Event가 아님)
   - "패널원가 증가" → X (패널원가 자체는 Driver, Event가 아님)
   - "매출 감소" → X (매출은 KPI, Event가 아님)

3. TV/가전 사업에 직접/간접적으로 영향이 있는 이벤트만
4. **중요**: 각 이벤트의 출처가 된 검색 결과 번호를 source_indices에 명시

5. **Confidence (정보 출처 신뢰도) 판단 - 5단계:**
   - 1.0: 공식 발표, 정부 기관, 대형 언론사(로이터, 블룸버그, AP) 확인된 사실
   - 0.8: 신뢰할 수 있는 경제 전문지 (Bloomberg, Reuters, 한경, 매경, WSJ 등)
   - 0.6: 일반 뉴스 매체, 업계 소식
   - 0.4: 블로그, 소셜 미디어, 미확인 소식
   - 0.2: 추측성 기사, 루머, 익명 소스

**영향 받는 Driver 후보:**
{drivers}

**타겟 Dimension (반드시 아래 정확한 ID 사용, 축약형 금지!):**
- Region: "북미", "유럽", "아시아", "한국", "중국", "중동", "글로벌" (NA/EU/ASIA 사용 금지)
- ProductCategory: "OLED_TV", "LCD_TV", "프리미엄_TV", "대형_TV", "TV_전체" (OLED/LCD 사용 금지)
- TimePeriod: "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2025H1", "2025H2", "2025" (Q3/Q4 사용 금지)

**응답 형식 (JSON):**
```json
{{
  "events": [
    {{
      "name": "이벤트명 (한글, 구체적 사건)",
      "name_en": "Event name (English)",
      "category": "geopolitical|policy|market|company|macro_economy|technology|natural",
      "start_date": "YYYY-MM-DD 또는 null",
      "is_ongoing": true/false,
      "severity": "low|medium|high|critical",
      "confidence": 0.8,
      "confidence_reasoning": "출처 신뢰도 판단 근거 (예: Bloomberg 보도, 공식 발표 인용)",
      "source_indices": [1, 3],
      "affected_drivers": [
        {{"driver": "Driver명", "impact": "INCREASES|DECREASES", "magnitude": "low|medium|high", "reasoning": "인과관계 설명"}}
      ],
      "target_dimensions": [
        {{"dimension_id": "북미", "dimension_type": "Region", "specificity": "high|medium|low"}},
        {{"dimension_id": "OLED_TV", "dimension_type": "ProductCategory", "specificity": "high|medium|low"}},
        {{"dimension_id": "2025Q3", "dimension_type": "TimePeriod", "specificity": "high|medium|low"}}
      ],
      "evidence": "영향 근거 (뉴스 snippet에서 발췌)"
    }}
  ]
}}
```

**source_indices 작성 규칙 (필수):**
1. 각 이벤트마다 반드시 source_indices를 명시해야 합니다
2. 정수 배열만 허용: [1, 3] (문자열 "1", 실수 1.0 금지)
3. 범위: 1부터 검색결과 개수까지만 유효
4. 해당 뉴스가 없으면 빈 배열: []
5. **이벤트 내용이 실제로 해당 뉴스에 있는지 반드시 확인**

**예시:**
- 뉴스 [1], [3]에서 같은 이벤트 추출: "source_indices": [1, 3]
- 뉴스 [2]에만 해당: "source_indices": [2]
- 뉴스에 없으면: "source_indices": []

이벤트가 없으면: {{"events": []}}
"""


@dataclass
class ExtractedEvent:
    """추출된 이벤트"""
    name: str
    name_en: Optional[str]
    category: str
    start_date: Optional[str]
    is_ongoing: bool
    severity: str
    source_indices: List[int]  # 출처 검색결과 인덱스
    affected_drivers: List[dict]
    target_dimensions: List[dict]
    evidence: str
    source_driver: Optional[str] = None  # 원본 Driver ID (Driver 기반 검색시)
    # v4: 정보 출처 신뢰도 (5단계: 1.0/0.8/0.6/0.4/0.2)
    confidence: float = 0.8
    confidence_reasoning: str = ""


class EventExtractor:
    """LLM 기반 Event 추출 (v2: Gemini 모델 사용)"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY 또는 GEMINI_API_KEY 필요")

    def extract_from_results_by_driver(
        self,
        search_results: List[SearchResult],
        batch_size: int = 10
    ) -> List[ExtractedEvent]:
        """Driver별로 그룹화된 검색 결과에서 Event 추출 (v3: Driver 기반)

        source_driver가 같은 결과끼리 그룹화하여 해당 Driver 맥락으로 추출
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # Driver별로 그룹화
        driver_groups = {}
        for r in search_results:
            driver_id = r.source_driver or "unknown"
            if driver_id not in driver_groups:
                driver_groups[driver_id] = []
            driver_groups[driver_id].append(r)

        all_events = []
        for driver_id, results in driver_groups.items():
            # 배치 단위로 처리
            for i in range(0, len(results), batch_size):
                batch = results[i:i + batch_size]
                events = self._extract_with_driver_context(
                    model, batch, driver_id, batch_size
                )
                # source_driver 설정
                for e in events:
                    e.source_driver = driver_id
                all_events.extend(events)

        return all_events

    def _extract_with_driver_context(
        self,
        model,
        search_results: List[SearchResult],
        source_driver: str,
        batch_size: int
    ) -> List[ExtractedEvent]:
        """특정 Driver 맥락으로 Event 추출"""
        formatted_results = self._format_results(search_results[:batch_size])
        drivers_str = ", ".join(CORE_DRIVERS)

        prompt = DRIVER_BASED_EXTRACTION_PROMPT.format(
            source_driver=source_driver,
            search_results=formatted_results,
            drivers=drivers_str
        )

        response = model.generate_content(prompt)
        return self._parse_response(response.text)

    def extract_from_results(
        self,
        search_results: List[SearchResult],
        batch_size: int = 10
    ) -> List[ExtractedEvent]:
        """검색 결과에서 Event 추출 (v2: Gemini 모델)"""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel("gemini-3-flash-preview")

        # 검색 결과 포맷팅
        formatted_results = self._format_results(search_results[:batch_size])
        drivers_str = ", ".join(CORE_DRIVERS)

        prompt = EVENT_EXTRACTION_PROMPT.format(
            search_results=formatted_results,
            drivers=drivers_str
        )

        response = model.generate_content(prompt)

        response_text = response.text
        return self._parse_response(response_text)

    def extract_events_only(
        self,
        search_results: List[SearchResult],
        batch_size: int = 10
    ) -> List[ExtractedEvent]:
        """순수 Event만 추출 (Driver 연결 없이)

        Driver 연결은 별도의 EventDriverLinker에서 수행합니다.
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        all_events = []

        # 배치 단위로 처리
        for i in range(0, len(search_results), batch_size):
            batch = search_results[i:i + batch_size]
            formatted_results = self._format_results(batch)

            prompt = PURE_EVENT_EXTRACTION_PROMPT.format(
                search_results=formatted_results
            )

            try:
                response = model.generate_content(prompt)
                events = self._parse_response(response.text)
                all_events.extend(events)
            except Exception as e:
                print(f"  추출 오류: {e}")
                continue

        return all_events

    def _format_results(self, results: List[SearchResult], max_content_length: int = 2000) -> str:
        """검색 결과 포맷팅

        Args:
            results: 검색 결과 리스트
            max_content_length: 본문 최대 길이 (LLM context 제한)
        """
        lines = []
        total = len(results)
        lines.append(f"총 {total}개의 검색 결과:")
        lines.append("")

        for i, r in enumerate(results, 1):
            # v2: 더 명확한 번호 표시
            lines.append(f"━━━━━ 검색결과 [{i}] (source_indices에 이 번호 사용) ━━━━━")
            lines.append(f"제목: {r.title}")
            lines.append(f"출처: {r.source or 'N/A'} | 날짜: {r.date or 'N/A'}")

            # v4: full_content 우선, 없으면 snippet fallback
            if hasattr(r, 'full_content') and r.full_content:
                content = r.full_content[:max_content_length]
                if len(r.full_content) > max_content_length:
                    content += "..."
            else:
                content = r.snippet

            lines.append(f"내용: {content}")
            lines.append("")
        return "\n".join(lines)

    def _parse_response(self, response: str) -> List[ExtractedEvent]:
        """LLM 응답 파싱"""
        # JSON 블록 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 직접 JSON 객체 찾기
            json_match2 = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match2:
                json_str = json_match2.group(0)
            else:
                json_str = response

        # JSON 정리 (LLM 출력 오류 수정)
        json_str = self._clean_json(json_str)

        try:
            data = json.loads(json_str)
            events = data.get("events", [])
            return [
                ExtractedEvent(
                    name=e.get("name", ""),
                    name_en=e.get("name_en"),
                    category=e.get("category", "market"),
                    start_date=e.get("start_date"),
                    is_ongoing=e.get("is_ongoing", False),
                    severity=e.get("severity", "medium"),
                    source_indices=e.get("source_indices", []),
                    affected_drivers=e.get("affected_drivers", []),
                    target_dimensions=e.get("target_dimensions", []),
                    evidence=e.get("evidence", ""),
                    # v4: 정보 출처 신뢰도
                    confidence=e.get("confidence", 0.8),
                    confidence_reasoning=e.get("confidence_reasoning", "")
                )
                for e in events
            ]
        except json.JSONDecodeError as ex:
            print(f"JSON 파싱 오류: {ex}")
            print(f"JSON 내용 (처음 300자): {json_str[:300]}")
            return []

    def _clean_json(self, json_str: str) -> str:
        """LLM 출력 JSON 정리"""
        # Trailing comma 제거: }, ] 또는 }, } 앞의 쉼표
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        # null 값 처리
        json_str = json_str.replace(': null', ': null')
        return json_str


class Layer3Builder:
    """Layer 3 그래프 빌더"""

    def __init__(self):
        self.extractor = EventExtractor()
        self.graph = Layer3Graph()
        self._event_id_counter = 0

    def build_from_search_results(
        self,
        search_results: List[SearchResult],
        batch_size: int = 10,
        verbose: bool = True
    ) -> Layer3Graph:
        """검색 결과에서 Event 추출 및 그래프 구축"""
        total = len(search_results)
        processed = 0

        if verbose:
            print(f"=== Event 추출 시작 ===")
            print(f"총 검색 결과: {total}개")
            print(f"배치 크기: {batch_size}개")

        # 배치 단위로 처리
        for i in range(0, total, batch_size):
            batch = search_results[i:i + batch_size]
            processed += len(batch)

            try:
                extracted = self.extractor.extract_from_results(batch, batch_size)

                for event_data in extracted:
                    event = self._create_event_node(event_data, batch)
                    self.graph.add_event(event)

                if verbose:
                    print(f"  진행: {processed}/{total} - 추출: {len(extracted)}개 이벤트")

            except Exception as e:
                print(f"  추출 오류: {e}")
                continue

        if verbose:
            print(f"\n=== 추출 완료 ===")
            print(f"총 Event: {len(self.graph.events)}개")
            summary = self.graph.summary()
            print(f"Factor 관계: {summary['total_factor_relations']}개")
            print(f"Dimension 관계: {summary['total_dimension_relations']}개")

        return self.graph

    def build_from_driver_search_results(
        self,
        search_results: List[SearchResult],
        batch_size: int = 10,
        verbose: bool = True
    ) -> Layer3Graph:
        """Driver 기반 검색 결과에서 Event 추출 및 그래프 구축

        source_driver별로 그룹화하여 해당 Driver 맥락으로 추출
        """
        # Driver별로 그룹화
        driver_groups = {}
        for r in search_results:
            driver_id = r.source_driver or "unknown"
            if driver_id not in driver_groups:
                driver_groups[driver_id] = []
            driver_groups[driver_id].append(r)

        total_drivers = len(driver_groups)
        total_results = len(search_results)

        if verbose:
            print(f"=== Driver 기반 Event 추출 시작 ===")
            print(f"총 검색 결과: {total_results}개")
            print(f"대상 Driver: {total_drivers}개")
            print(f"배치 크기: {batch_size}개")
            print()

        driver_count = 0
        for driver_id, results in driver_groups.items():
            driver_count += 1

            if verbose:
                print(f"  [{driver_count}/{total_drivers}] {driver_id}: {len(results)}개 결과")

            # 배치 단위로 처리
            for i in range(0, len(results), batch_size):
                batch = results[i:i + batch_size]

                try:
                    extracted = self.extractor._extract_with_driver_context(
                        self._get_model(), batch, driver_id, batch_size
                    )

                    for event_data in extracted:
                        event_data.source_driver = driver_id
                        event = self._create_event_node(event_data, batch)
                        self.graph.add_event(event)

                    if verbose and len(extracted) > 0:
                        print(f"       추출: {len(extracted)}개 이벤트")

                except Exception as e:
                    print(f"       추출 오류: {e}")
                    continue

        if verbose:
            print(f"\n=== 추출 완료 ===")
            print(f"총 Event: {len(self.graph.events)}개")
            summary = self.graph.summary()
            print(f"Factor 관계: {summary['total_factor_relations']}개")
            print(f"Dimension 관계: {summary['total_dimension_relations']}개")

        return self.graph

    def build_with_separate_linking(
        self,
        search_results: List[SearchResult],
        batch_size: int = 10,
        verbose: bool = True
    ) -> Layer3Graph:
        """검색 → Event 추출 → Driver 연결을 분리하여 수행

        1. 뉴스에서 순수 Event만 추출 (Driver 연결 없이)
        2. 추출된 Event를 별도 LLM 단계에서 Driver에 연결
        3. 각 연결에 구체적인 evidence(인과관계 설명) 포함
        """
        from .event_linker import EventDriverLinker, apply_links_to_events

        total = len(search_results)

        if verbose:
            print(f"=== Event 추출 시작 (분리 연결 모드) ===")
            print(f"총 검색 결과: {total}개")
            print(f"배치 크기: {batch_size}개")
            print()

        # Phase 1: 순수 Event 추출
        if verbose:
            print("Phase 1: Event 추출 (Driver 연결 없이)")

        extracted = self.extractor.extract_events_only(search_results, batch_size)

        if verbose:
            print(f"  추출된 Event: {len(extracted)}개")
            print()

        # EventNode로 변환
        for event_data in extracted:
            event = self._create_event_node(event_data, search_results)
            self.graph.add_event(event)

        # Phase 2: Event-Driver 연결
        if verbose:
            print("Phase 2: Event-Driver 연결")

        linker = EventDriverLinker()
        links = linker.link_events_to_drivers(
            self.graph.events,
            batch_size=batch_size,
            verbose=verbose
        )

        # 연결 결과 적용
        apply_links_to_events(self.graph.events, links)

        if verbose:
            print(f"\n=== 처리 완료 ===")
            print(f"총 Event: {len(self.graph.events)}개")
            summary = self.graph.summary()
            print(f"Factor 관계: {summary['total_factor_relations']}개")
            print(f"Dimension 관계: {summary['total_dimension_relations']}개")

        return self.graph

    def _get_model(self):
        """Gemini 모델 반환"""
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.extractor.api_key)
        return genai.GenerativeModel("gemini-2.0-flash")

    def _create_event_node(
        self,
        event_data: ExtractedEvent,
        source_results: List[SearchResult]
    ) -> EventNode:
        """ExtractedEvent를 EventNode로 변환"""
        # ID 생성
        self._event_id_counter += 1
        event_id = self._generate_event_id(event_data.name)

        # 카테고리 파싱
        try:
            category = EventCategory(event_data.category)
        except ValueError:
            category = EventCategory.MARKET

        # 심각도 파싱
        try:
            severity = Severity(event_data.severity)
        except ValueError:
            severity = Severity.MEDIUM

        # 날짜 파싱
        start_date = None
        if event_data.start_date:
            try:
                start_date = datetime.strptime(event_data.start_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Driver 관계 생성
        driver_relations = []
        for d in event_data.affected_drivers:
            driver_name = d.get("driver", "")
            driver_id = driver_name  # V3 스키마: 한글 ID 그대로 사용
            try:
                impact = ImpactType(d.get("impact", "INCREASES"))
            except ValueError:
                impact = ImpactType.INCREASES

            driver_relations.append(EventFactorRelation(
                factor_name=driver_name,
                factor_id=driver_id,
                impact_type=impact,
                magnitude=d.get("magnitude", "medium"),
                evidence=event_data.evidence
            ))

        # Dimension 관계 생성 (v5: shorthand → 정규 ID 매핑)
        dimension_relations = []
        for d in event_data.target_dimensions:
            # v4 형식: dimension_id, dimension_type, specificity
            raw_dim_id = d.get("dimension_id") or d.get("dimension", "")
            dim_type = d.get("dimension_type") or d.get("type", "Region")
            specificity = d.get("specificity", "medium")

            # v5: shorthand ID를 정규 ID로 변환 (예: "NA" → "북미", "OLED" → "OLED_TV")
            dim_id = normalize_dimension_id(raw_dim_id, dim_type)

            if dim_id:
                dimension_relations.append(EventDimensionRelation(
                    dimension_name=dim_id,  # dimension_name은 display용
                    dimension_type=dim_type,
                    dimension_id=dim_id,
                    specificity=specificity
                ))

        # Source 생성 - LLM이 지정한 source_indices 사용
        sources = []
        batch_size = len(source_results)

        # source_indices 정규화 및 검증 (v2: 타입 변환 + 범위 검증)
        source_indices = []
        invalid_indices = []

        for item in event_data.source_indices:
            idx = None
            # 타입 변환 시도
            if isinstance(item, int):
                idx = item
            elif isinstance(item, str) and item.strip().isdigit():
                idx = int(item)
                print(f"    경고: source_indices '{item}' → {idx} 변환")
            elif isinstance(item, float) and item == int(item):
                idx = int(item)
            elif isinstance(item, list):
                # 중첩 리스트 flatten
                for sub in item:
                    if isinstance(sub, int) and 1 <= sub <= batch_size:
                        source_indices.append(sub)
                continue

            # 범위 검증
            if idx is not None:
                if 1 <= idx <= batch_size:
                    source_indices.append(idx)
                else:
                    invalid_indices.append(idx)

        # 중복 제거 (순서 유지)
        source_indices = list(dict.fromkeys(source_indices))

        if invalid_indices:
            print(f"    경고: Event '{event_data.name}' - 유효하지 않은 source_indices: {invalid_indices} (범위: 1~{batch_size})")

        for idx in source_indices:
            # 인덱스는 1부터 시작 (LLM 프롬프트에서 [1], [2]로 표시)
            actual_idx = idx - 1
            if 0 <= actual_idx < batch_size:
                r = source_results[actual_idx]
                sources.append(EventSource(
                    url=r.link,
                    title=r.title,
                    snippet=r.snippet,
                    published_date=None,
                    source_name=r.source,
                    search_query=r.query
                ))

        # v2: Fallback 제거 - 잘못된 출처 매핑 방지
        if not sources:
            if source_results:
                print(f"    ⚠️ Event '{event_data.name}': source_indices 매핑 실패, 출처 없이 저장")
            else:
                print(f"    ⚠️ Event '{event_data.name}': 검색 결과 없음")

        event = EventNode(
            id=event_id,
            name=event_data.name,
            name_en=event_data.name_en,
            category=category,
            start_date=start_date,
            is_ongoing=event_data.is_ongoing,
            severity=severity,
            sources=sources,
            factor_relations=driver_relations,
            dimension_relations=dimension_relations,
            evidence=event_data.evidence,
            source_driver=getattr(event_data, 'source_driver', None),  # v3: 원본 Driver ID
            # v4: 정보 출처 신뢰도
            source_confidence=getattr(event_data, 'confidence', 0.8),
            source_confidence_reasoning=getattr(event_data, 'confidence_reasoning', "")
        )

        # v3: Impact Score 계산
        event.calculate_impact_scores()

        return event

    def _generate_event_id(self, name: str) -> str:
        """Event ID 생성"""
        # 한글/영어 이름에서 ID 생성
        clean_name = re.sub(r'[^\w\s]', '', name.lower())
        clean_name = clean_name.replace(" ", "_")[:30]
        return f"event_{clean_name}_{self._event_id_counter}"


def test_extraction():
    """추출 테스트"""
    from .search_client import BraveSearchClient

    print("=== Event 추출 테스트 ===\n")

    # 검색
    client = BraveSearchClient()
    results = client.search_news("홍해 사태 해운", count=10)
    print(f"검색 결과: {len(results)}개\n")

    # 추출
    builder = Layer3Builder()
    graph = builder.build_from_search_results(results, batch_size=10)

    print(f"\n추출된 Event:")
    for event in graph.events:
        print(f"- {event.name}")
        for r in event.factor_relations:
            print(f"  → {r.impact_type.value} {r.factor_name}")


if __name__ == "__main__":
    test_extraction()
