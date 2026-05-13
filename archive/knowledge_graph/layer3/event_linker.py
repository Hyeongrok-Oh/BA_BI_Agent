"""Event-Driver 연결 모듈

검색/추출과 분리된 별도의 LLM 단계에서 Event-Driver 연결을 결정합니다.
각 연결에는 구체적인 evidence(인과관계 설명)가 포함됩니다.
"""

import json
import os
import re
from typing import List, Dict, Optional
from dataclasses import dataclass

from .models import EventNode, EventFactorRelation, ImpactType
from .config import CORE_DRIVERS


EVENT_DRIVER_LINKING_PROMPT = """추출된 Event들이 어떤 Driver(비즈니스 지표)에 영향을 미치는지 분석하세요.

## Event 목록
{events}

## Driver 목록 (연결 대상)
{drivers}

## 연결 규칙
1. **Event는 외부 사건/상황 (원인)**, **Driver는 비즈니스 지표 (결과)**
2. **Event → Driver 방향만 유효** (Event가 Driver에 영향을 줌)
3. 하나의 Event가 여러 Driver에 영향을 줄 수 있음
4. 관련성이 명확한 경우에만 연결 (억지로 연결하지 말 것)

## Evidence 작성 가이드 (매우 중요)
- **왜** 이 Event가 이 Driver에 영향을 미치는지 **인과관계 메커니즘**을 설명
- 단순 결과 나열이 아닌, 원인 → 중간과정 → 결과 형태로 작성
- 예시:
  - "홍해 후티 반군 공격 → 수에즈 운하 우회 필요 → 해상 운송 거리/시간 증가 → 물류비 상승"
  - "BOE 8.6세대 OLED 생산라인 가동 → 대형 OLED 패널 공급 증가 → 공급 과잉으로 패널 가격 하락"
  - "미국 관세 인상 발표 → 수출 제품 가격 경쟁력 저하 → 북미 판매량 감소 예상"

## Confidence (연결 신뢰도) 판단 - 5단계
각 Event-Driver 연결의 신뢰도를 판단하세요:
- 1.0: 공식 발표에서 직접적으로 언급된 인과관계
- 0.8: 신뢰할 수 있는 출처에서 확인된 연결
- 0.6: 업계에서 일반적으로 인정되는 연결
- 0.4: 간접적이거나 추론에 의한 연결
- 0.2: 추측성 또는 약한 연결

## 응답 형식 (JSON)
```json
{{
  "links": [
    {{
      "event_id": "이벤트 ID",
      "event_name": "이벤트명 (확인용)",
      "driver_id": "Driver 한글명",
      "polarity": 1,
      "magnitude": "high",
      "confidence": 0.8,
      "confidence_reasoning": "연결 신뢰도 판단 근거",
      "evidence": "인과관계 설명"
    }}
  ]
}}
```

**필드 설명:**
- event_id: 위 Event 목록의 ID
- driver_id: Driver 한글명 (위 Driver 목록에서 선택)
- polarity: 1 (Driver 증가) 또는 -1 (Driver 감소)
- magnitude: "low" | "medium" | "high" (영향 크기)
- confidence: 0.2~1.0 (연결 신뢰도, 5단계)
- confidence_reasoning: 신뢰도 판단 근거
- evidence: 인과관계 메커니즘 설명 (필수, 상세하게)

연결이 없으면: {{"links": []}}
"""


@dataclass
class EventDriverLink:
    """Event-Driver 연결 정보"""
    event_id: str
    event_name: str
    driver_id: str
    polarity: int  # 1: 증가, -1: 감소
    magnitude: str  # low, medium, high
    evidence: str  # 연결 이유 (인과관계 설명)
    # v4: 연결 신뢰도 (5단계: 1.0/0.8/0.6/0.4/0.2)
    confidence: float = 0.8
    confidence_reasoning: str = ""


class EventDriverLinker:
    """Event-Driver 연결 담당

    추출된 Event와 전체 Driver 목록을 받아서
    LLM이 어떤 Event가 어떤 Driver에 영향을 미치는지 판단합니다.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY 또는 GEMINI_API_KEY 필요")

    def link_events_to_drivers(
        self,
        events: List[EventNode],
        drivers: List[str] = None,
        batch_size: int = 10,
        verbose: bool = True
    ) -> Dict[str, List[EventFactorRelation]]:
        """Event들을 Driver에 연결

        Args:
            events: 추출된 Event 노드 목록
            drivers: Driver ID 목록 (기본값: CORE_DRIVERS)
            batch_size: 한 번에 처리할 Event 수
            verbose: 진행 상황 출력 여부

        Returns:
            {event_id: [EventFactorRelation, ...]} 형태의 딕셔너리
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        drivers = drivers or CORE_DRIVERS

        if verbose:
            print(f"=== Event-Driver 연결 시작 ===")
            print(f"총 Event: {len(events)}개")
            print(f"대상 Driver: {len(drivers)}개")
            print(f"배치 크기: {batch_size}개")
            print()

        all_links: Dict[str, List[EventFactorRelation]] = {}

        # 배치 단위로 처리
        for i in range(0, len(events), batch_size):
            batch = events[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(events) + batch_size - 1) // batch_size

            if verbose:
                print(f"  [{batch_num}/{total_batches}] {len(batch)}개 Event 처리 중...")

            try:
                links = self._link_batch(model, batch, drivers)

                # 결과를 event_id별로 그룹화
                for link in links:
                    if link.event_id not in all_links:
                        all_links[link.event_id] = []

                    # EventFactorRelation으로 변환
                    try:
                        impact_type = ImpactType.INCREASES if link.polarity > 0 else ImpactType.DECREASES
                    except:
                        impact_type = ImpactType.AFFECTS

                    relation = EventFactorRelation(
                        factor_name=link.driver_id,
                        factor_id=link.driver_id,
                        impact_type=impact_type,
                        magnitude=link.magnitude,
                        confidence=link.confidence,  # v4: 연결 신뢰도
                        confidence_reasoning=link.confidence_reasoning,  # v4: 신뢰도 판단 근거
                        evidence=link.evidence,
                        polarity=link.polarity,
                        weight={"high": 1.0, "medium": 0.6, "low": 0.3}.get(link.magnitude, 0.6)
                    )
                    all_links[link.event_id].append(relation)

                if verbose:
                    print(f"       연결: {len(links)}개")

            except Exception as e:
                print(f"       연결 오류: {e}")
                continue

        if verbose:
            total_links = sum(len(v) for v in all_links.values())
            events_with_links = len(all_links)
            print(f"\n=== 연결 완료 ===")
            print(f"연결된 Event: {events_with_links}개 / {len(events)}개")
            print(f"총 연결: {total_links}개")

        return all_links

    def _link_batch(
        self,
        model,
        events: List[EventNode],
        drivers: List[str]
    ) -> List[EventDriverLink]:
        """배치 단위로 Event-Driver 연결"""
        # Event 포맷팅
        events_str = self._format_events(events)
        drivers_str = self._format_drivers(drivers)

        prompt = EVENT_DRIVER_LINKING_PROMPT.format(
            events=events_str,
            drivers=drivers_str
        )

        response = model.generate_content(prompt)
        return self._parse_response(response.text, events)

    def _format_events(self, events: List[EventNode]) -> str:
        """Event 목록 포맷팅"""
        lines = []
        for e in events:
            lines.append(f"[{e.id}] {e.name}")
            lines.append(f"    카테고리: {e.category.value}")
            lines.append(f"    심각도: {e.severity.value}")
            if e.evidence:
                lines.append(f"    내용: {e.evidence[:200]}...")
            lines.append("")
        return "\n".join(lines)

    def _format_drivers(self, drivers: List[str]) -> str:
        """Driver 목록 포맷팅"""
        # Driver 설명 추가 (선택사항)
        driver_descriptions = {
            "물류비": "해상/항공 운송 비용, 물류 관련 비용",
            "패널원가": "LCD/OLED 패널 구매 단가",
            "환율": "달러/원 환율, 환율 변동",
            "글로벌TV수요": "전세계 TV 시장 수요",
            "프리미엄비중": "프리미엄 TV 제품 비중",
            "OLED비중": "OLED TV 제품 비중",
            "출하량": "TV 출하 대수",
            "경쟁사점유율": "삼성, TCL, 하이센스 등 경쟁사 시장점유율",
            "ASP": "평균 판매가격",
            "원재료비": "원자재, 부품 비용",
        }

        lines = []
        for d in drivers:
            desc = driver_descriptions.get(d, "")
            if desc:
                lines.append(f"- {d}: {desc}")
            else:
                lines.append(f"- {d}")
        return "\n".join(lines)

    def _parse_response(
        self,
        response: str,
        events: List[EventNode]
    ) -> List[EventDriverLink]:
        """LLM 응답 파싱"""
        # JSON 블록 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match2 = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match2:
                json_str = json_match2.group(0)
            else:
                json_str = response

        # JSON 정리
        json_str = self._clean_json(json_str)

        try:
            data = json.loads(json_str)
            links_data = data.get("links", [])

            # Event ID 검증을 위한 ID 세트
            valid_event_ids = {e.id for e in events}

            links = []
            for l in links_data:
                event_id = l.get("event_id", "")

                # Event ID 검증
                if event_id not in valid_event_ids:
                    # 이름으로 매칭 시도
                    event_name = l.get("event_name", "")
                    matched_event = next(
                        (e for e in events if e.name == event_name),
                        None
                    )
                    if matched_event:
                        event_id = matched_event.id
                    else:
                        continue  # 유효하지 않은 연결 건너뛰기

                links.append(EventDriverLink(
                    event_id=event_id,
                    event_name=l.get("event_name", ""),
                    driver_id=l.get("driver_id", ""),
                    polarity=l.get("polarity", 1),
                    magnitude=l.get("magnitude", "medium"),
                    evidence=l.get("evidence", ""),
                    # v4: 연결 신뢰도
                    confidence=l.get("confidence", 0.8),
                    confidence_reasoning=l.get("confidence_reasoning", "")
                ))

            return links

        except json.JSONDecodeError as ex:
            print(f"JSON 파싱 오류: {ex}")
            print(f"JSON 내용 (처음 300자): {json_str[:300]}")
            return []

    def _clean_json(self, json_str: str) -> str:
        """LLM 출력 JSON 정리"""
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        return json_str


def apply_links_to_events(
    events: List[EventNode],
    links: Dict[str, List[EventFactorRelation]]
) -> None:
    """연결 결과를 Event에 적용

    기존 factor_relations를 새로운 연결로 교체합니다.
    """
    for event in events:
        if event.id in links:
            event.factor_relations = links[event.id]
            # Impact Score 재계산
            event.calculate_impact_scores()
