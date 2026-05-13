"""Driver 기반 검색 쿼리 생성기 - LLM으로 Driver별 뉴스 검색 쿼리 생성"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class DriverInfo:
    """Driver 정보"""
    id: str
    name: str
    name_kr: str
    description: str
    example_sentence: str
    tier: str
    category: str


@dataclass
class DriverQueryResult:
    """Driver 쿼리 생성 결과"""
    driver_id: str
    events_increase: List[str]  # 증가시키는 이벤트
    events_decrease: List[str]  # 감소시키는 이벤트
    queries: List[str]


class DriverQueryGenerator:
    """LLM 기반 Driver별 검색 쿼리 생성기 (이벤트 중심)"""

    QUERY_GENERATION_PROMPT = """당신은 LG전자 TV(HE) 사업 분석을 위한 뉴스 검색 전문가입니다.

**Driver 정보:**
- ID: {driver_id}
- 이름: {name_kr} ({name})
- 설명: {description}
- 예시: {example_sentence}
- 카테고리: {category}

**Task 1: 이벤트 식별**
이 Driver에 영향을 미치는 구체적인 이벤트/상황을 식별하세요:
- 증가시키는 이벤트 (3개): Driver 값을 올리는 사건/상황
- 감소시키는 이벤트 (3개): Driver 값을 낮추는 사건/상황

**Task 2: 검색 쿼리 생성**
식별된 이벤트를 기반으로 뉴스 검색 쿼리 {n}개를 생성하세요.

**쿼리 생성 규칙 (중요!):**
1. **필수 키워드**: "TV", "디스플레이", "패널", "가전", "LG전자", "삼성전자" 중 최소 1개 포함
2. 구체적인 이벤트/사건 키워드 포함 (가격 인상, 공급 부족, 파업, 관세 등)
3. **따옴표 구 검색 활용**: 핵심 구문은 따옴표로 묶기 (예: "LCD 패널" 가격)
4. 일반적 단어만으로 구성된 쿼리 금지 (급등, 전망, 투자 단독 사용 X)
5. 3-5개 키워드, 한글 검색 최적화

**좋은 쿼리 예시:**
- "LCD 패널" 가격 상승 TV
- OLED 패널 공급 부족 디스플레이
- TV 해상 운임 상승 물류
- "디스플레이 패널" 중국 공급 과잉
- LG전자 TV 관세 미국

**나쁜 쿼리 예시 (피해야 함!):**
- TV 패널 가격 급등 전망 (너무 일반적, "급등 전망"에 관련없는 기사 매칭됨)
- LG전자 물류 자동화 투자 ("물류 자동화"가 로봇 기사로 확장됨)
- 해상 운임 급등 (TV/패널 키워드 없음)

**응답 형식 (JSON만 출력):**
```json
{{
  "driver_id": "{driver_id}",
  "events": {{
    "increase": ["이벤트1", "이벤트2", "이벤트3"],
    "decrease": ["이벤트1", "이벤트2", "이벤트3"]
  }},
  "queries": [
    "검색 쿼리 1",
    "검색 쿼리 2"
  ]
}}
```
"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY 또는 GEMINI_API_KEY 필요")

        self.drivers = self._load_drivers()

    def _load_drivers(self) -> List[DriverInfo]:
        """driver_definitions.json에서 Driver 로드"""
        schema_dir = Path(__file__).parent.parent / "schema"
        definitions_path = schema_dir / "driver_definitions.json"

        with open(definitions_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        drivers = []
        for tier_key, tier_data in data.get("drivers", {}).items():
            for d in tier_data.get("drivers", []):
                drivers.append(DriverInfo(
                    id=d.get("id", ""),
                    name=d.get("name", ""),
                    name_kr=d.get("name_kr", ""),
                    description=d.get("description", ""),
                    example_sentence=d.get("example_sentence", ""),
                    tier=tier_key,
                    category=d.get("category", "")
                ))

        return drivers

    def generate_queries(
        self,
        queries_per_driver: int = 3,
        driver_ids: Optional[List[str]] = None,
        verbose: bool = True
    ) -> Dict[str, DriverQueryResult]:
        """모든 Driver에 대해 검색 쿼리 생성 (이벤트 중심)

        Args:
            queries_per_driver: Driver당 생성할 쿼리 수
            driver_ids: 특정 Driver만 처리 (None이면 전체)
            verbose: 진행 상황 출력

        Returns:
            {driver_id: DriverQueryResult}
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # 처리할 Driver 선택
        target_drivers = self.drivers
        if driver_ids:
            target_drivers = [d for d in self.drivers if d.id in driver_ids]

        if verbose:
            print(f"=== Driver 기반 쿼리 생성 ===")
            print(f"대상 Driver: {len(target_drivers)}개")
            print(f"Driver당 쿼리: {queries_per_driver}개")
            print(f"예상 총 쿼리: {len(target_drivers) * queries_per_driver}개")
            print()

        result = {}
        for i, driver in enumerate(target_drivers, 1):
            try:
                query_result = self._generate_for_driver(model, driver, queries_per_driver)
                result[driver.id] = query_result

                if verbose:
                    print(f"  [{i}/{len(target_drivers)}] {driver.id}: {len(query_result.queries)}개 쿼리")
                    if query_result.events_increase:
                        print(f"       이벤트(↑): {', '.join(query_result.events_increase[:3])}")
                    if query_result.events_decrease:
                        print(f"       이벤트(↓): {', '.join(query_result.events_decrease[:3])}")
                    for q in query_result.queries:
                        print(f"       - {q}")

            except Exception as e:
                if verbose:
                    print(f"  [{i}/{len(target_drivers)}] {driver.id}: 오류 - {e}")
                result[driver.id] = self._fallback_query_result(driver)

        if verbose:
            total = sum(len(r.queries) for r in result.values())
            print(f"\n=== 생성 완료: 총 {total}개 쿼리 ===")

        return result

    def _generate_for_driver(
        self,
        model,
        driver: DriverInfo,
        queries_per_driver: int
    ) -> DriverQueryResult:
        """단일 Driver에 대한 쿼리 생성 (이벤트 중심)"""
        prompt = self.QUERY_GENERATION_PROMPT.format(
            n=queries_per_driver,
            driver_id=driver.id,
            name=driver.name,
            name_kr=driver.name_kr,
            description=driver.description,
            example_sentence=driver.example_sentence,
            category=driver.category
        )

        response = model.generate_content(prompt)
        return self._parse_response(response.text, driver.id)

    def _parse_response(self, response: str, driver_id: str) -> DriverQueryResult:
        """LLM 응답 파싱 (이벤트 + 쿼리)"""
        # JSON 블록 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match2 = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match2:
                json_str = json_match2.group(0)
            else:
                return DriverQueryResult(
                    driver_id=driver_id,
                    events_increase=[],
                    events_decrease=[],
                    queries=[]
                )

        try:
            data = json.loads(json_str)
            events = data.get("events", {})
            return DriverQueryResult(
                driver_id=driver_id,
                events_increase=events.get("increase", []),
                events_decrease=events.get("decrease", []),
                queries=data.get("queries", [])
            )
        except json.JSONDecodeError:
            return DriverQueryResult(
                driver_id=driver_id,
                events_increase=[],
                events_decrease=[],
                queries=[]
            )

    def _fallback_query_result(self, driver: DriverInfo) -> DriverQueryResult:
        """LLM 실패시 기본 쿼리 생성"""
        return DriverQueryResult(
            driver_id=driver.id,
            events_increase=[f"{driver.name_kr} 증가"],
            events_decrease=[f"{driver.name_kr} 감소"],
            queries=[
                f"{driver.name_kr} TV 가전",
                f"{driver.name_kr} 상승 하락",
                f"{driver.name_kr} 영향"
            ]
        )

    def apply_date_range(
        self,
        driver_queries: Dict[str, DriverQueryResult],
        date_range: List[str]
    ) -> Dict[str, DriverQueryResult]:
        """쿼리에 날짜 범위 적용

        Args:
            driver_queries: {driver_id: DriverQueryResult}
            date_range: ["2025년 6월", "2025년 7월", ...]

        Returns:
            날짜가 추가된 DriverQueryResult 딕셔너리
        """
        result = {}
        for driver_id, query_result in driver_queries.items():
            dated_queries = []
            for query in query_result.queries:
                for month in date_range:
                    dated_queries.append(f"{query} {month}")
            result[driver_id] = DriverQueryResult(
                driver_id=driver_id,
                events_increase=query_result.events_increase,
                events_decrease=query_result.events_decrease,
                queries=dated_queries
            )

        return result

    def get_all_queries_flat(
        self,
        driver_queries: Dict[str, DriverQueryResult]
    ) -> List[tuple]:
        """Driver-쿼리 매핑을 flat 리스트로 변환

        Returns:
            [(driver_id, query), ...]
        """
        result = []
        for driver_id, query_result in driver_queries.items():
            for query in query_result.queries:
                result.append((driver_id, query))
        return result

    def get_queries_dict(
        self,
        driver_queries: Dict[str, DriverQueryResult]
    ) -> Dict[str, List[str]]:
        """DriverQueryResult를 {driver_id: [queries]} 형태로 변환 (하위 호환)"""
        return {
            driver_id: query_result.queries
            for driver_id, query_result in driver_queries.items()
        }


def test_query_generation():
    """쿼리 생성 테스트 (이벤트 중심)"""
    print("=== Driver 쿼리 생성 테스트 (이벤트 중심) ===\n")

    generator = DriverQueryGenerator()

    # 일부 Driver만 테스트
    test_drivers = ["물류비", "패널원가"]
    results = generator.generate_queries(
        queries_per_driver=3,
        driver_ids=test_drivers,
        verbose=True
    )

    print("\n" + "=" * 50)
    print("상세 결과")
    print("=" * 50)
    for driver_id, result in results.items():
        print(f"\n[{driver_id}]")
        print(f"  이벤트 (증가): {', '.join(result.events_increase)}")
        print(f"  이벤트 (감소): {', '.join(result.events_decrease)}")
        print(f"  쿼리:")
        for q in result.queries:
            print(f"    • {q}")


if __name__ == "__main__":
    test_query_generation()
