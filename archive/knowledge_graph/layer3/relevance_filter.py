"""검색 결과 관련성 필터링 모듈

검색 API가 반환한 결과 중 TV/디스플레이/가전 산업과 관련 없는 기사를 필터링합니다.
LLM을 사용하여 각 기사의 관련성을 판단합니다.
"""

import os
import json
import re
from typing import List, Optional
from dataclasses import dataclass

from .search_client import SearchResult


# 제목 기반 제외 패턴 (정규식)
EXCLUDE_TITLE_PATTERNS = [
    r"^\[Who Is",           # 인물 프로필
    r"시장 규모.*보고서",    # 시장 보고서
    r"전망.*\d{4}",         # 연도 전망 (예: 전망 2035)
    r"^\[.*리포트\]",       # 리서치 리포트
    r"주가.*전망",          # 주가 전망
    r"^\[주간.*\]",         # 주간 리포트
    r"^\[.*분석\]",         # 분석 리포트
    r"점유율.*보고서",      # 점유율 보고서
    r"성장.*보고서",        # 성장 보고서
]

# 스니펫 기반 제외 패턴
EXCLUDE_SNIPPET_PATTERNS = [
    r"시장 규모는.*예상",
    r"전망이.*나왔다",
    r"투자의견.*목표주가",
    r"증권사.*리포트",
    r"애널리스트.*전망",
]


# 배치 관련성 체크 프롬프트
BATCH_RELEVANCE_PROMPT = """다음 뉴스 기사들이 **TV/디스플레이/가전 산업**과 관련이 있고, **실제 발생한 사건**인지 판단하세요.

**관련성 기준:**
1. TV, 디스플레이, 패널, 가전 산업에 직접 관련된 기사
2. LG전자, 삼성전자 등 가전 기업의 TV/가전 사업 관련 기사
3. 물류비, 환율, 관세 등이 TV/가전 산업에 미치는 영향 기사
4. LCD, OLED 패널 시장, 가격, 공급 관련 기사

**관련 없는 기사 (relevant=false):**
- 은/금 가격 급등 (귀금속 시장)
- 홈로봇/AI 로봇 (TV/가전과 무관한 로봇)
- 일반 물류/운송 기사 (TV/가전 언급 없음)
- 부동산, 주식 시장 일반 기사
- 반도체 파운드리 (TV 패널과 무관)

**추측/전망 기사 (relevant=false):**
- 제목에 "전망", "예상", "예측", "계획", "논의", "검토" 포함
- "~할 것으로 보인다", "~할 가능성", "~할 수도"
- 애널리스트/전문가 예측 기사
- 미래 계획 발표 (실제 실행이 아닌 계획)

**실제 사건 기사 (relevant=true):**
- 실제 출시, 발표, 서명, 시행된 사건
- 가격 인상/인하 실제 발생
- 공장 가동, 양산 시작
- 실적 발표 (예상 아닌 실제)

**뉴스 기사 목록:**
{articles}

**응답 형식 (JSON):**
```json
{{
  "results": [
    {{"index": 1, "relevant": true, "reason": "LCD 패널 가격 실제 인상 기사"}},
    {{"index": 2, "relevant": false, "reason": "전망/예측 기사"}},
    {{"index": 3, "relevant": false, "reason": "TV/패널과 무관"}}
  ]
}}
```

각 기사에 대해 relevant (true/false)와 간단한 reason을 제공하세요.
"""


@dataclass
class FilterResult:
    """필터링 결과"""
    original_count: int
    filtered_count: int
    removed_count: int
    removed_articles: List[dict]  # 제거된 기사 정보


class RelevanceFilter:
    """검색 결과 관련성 필터"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY 또는 GEMINI_API_KEY 필요")

    def _pre_filter_by_pattern(
        self,
        search_results: List[SearchResult],
        verbose: bool = True
    ) -> tuple[List[SearchResult], List[dict]]:
        """패턴 기반 사전 필터링 (LLM 호출 전)

        제목/스니펫 패턴 매칭으로 명확하게 관련 없는 기사 제거
        """
        passed = []
        removed = []

        for result in search_results:
            excluded = False
            reason = ""

            # 제목 패턴 체크
            for pattern in EXCLUDE_TITLE_PATTERNS:
                if re.search(pattern, result.title):
                    excluded = True
                    reason = f"제목 패턴 매칭: {pattern}"
                    break

            # 스니펫 패턴 체크
            if not excluded:
                for pattern in EXCLUDE_SNIPPET_PATTERNS:
                    if re.search(pattern, result.snippet):
                        excluded = True
                        reason = f"스니펫 패턴 매칭: {pattern}"
                        break

            if excluded:
                removed.append({
                    "title": result.title,
                    "query": result.query,
                    "reason": reason
                })
            else:
                passed.append(result)

        if verbose and removed:
            print(f"패턴 기반 사전 필터링: {len(removed)}개 제거")

        return passed, removed

    def filter_results(
        self,
        search_results: List[SearchResult],
        batch_size: int = 20,
        verbose: bool = True
    ) -> tuple[List[SearchResult], FilterResult]:
        """관련 없는 검색 결과 필터링

        Args:
            search_results: 검색 결과 리스트
            batch_size: 한 번에 처리할 기사 수
            verbose: 진행 상황 출력

        Returns:
            (필터링된 결과 리스트, 필터링 통계)
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("google-generativeai 패키지 필요: pip install google-generativeai")

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        if verbose:
            print(f"=== 검색 결과 관련성 필터링 ===")
            print(f"입력 기사: {len(search_results)}개")

        # 1단계: 패턴 기반 사전 필터링
        search_results, pattern_removed = self._pre_filter_by_pattern(
            search_results, verbose=verbose
        )

        if verbose:
            print(f"패턴 필터링 후: {len(search_results)}개")
            print(f"배치 크기: {batch_size}개")

        filtered_results = []
        removed_articles = list(pattern_removed)  # 패턴으로 제거된 것 포함

        # 배치 단위로 처리
        for i in range(0, len(search_results), batch_size):
            batch = search_results[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(search_results) + batch_size - 1) // batch_size

            if verbose:
                print(f"  [{batch_num}/{total_batches}] {len(batch)}개 기사 검사 중...")

            try:
                relevance_results = self._check_batch_relevance(model, batch)

                for j, result in enumerate(batch):
                    if j < len(relevance_results):
                        if relevance_results[j].get("relevant", True):
                            filtered_results.append(result)
                        else:
                            removed_articles.append({
                                "title": result.title,
                                "query": result.query,
                                "reason": relevance_results[j].get("reason", "관련 없음")
                            })
                    else:
                        # 결과가 없으면 기본적으로 포함
                        filtered_results.append(result)

            except Exception as e:
                if verbose:
                    print(f"       필터링 오류: {e}, 배치 전체 포함")
                filtered_results.extend(batch)

        filter_result = FilterResult(
            original_count=len(search_results),
            filtered_count=len(filtered_results),
            removed_count=len(removed_articles),
            removed_articles=removed_articles
        )

        if verbose:
            print(f"\n=== 필터링 완료 ===")
            print(f"원본: {filter_result.original_count}개")
            print(f"유지: {filter_result.filtered_count}개")
            print(f"제거: {filter_result.removed_count}개")
            if removed_articles:
                print(f"\n제거된 기사:")
                for article in removed_articles[:5]:  # 최대 5개만 출력
                    print(f"  - {article['title'][:50]}...")
                    print(f"    이유: {article['reason']}")
                if len(removed_articles) > 5:
                    print(f"  ... 외 {len(removed_articles) - 5}개")

        return filtered_results, filter_result

    def _check_batch_relevance(
        self,
        model,
        batch: List[SearchResult]
    ) -> List[dict]:
        """배치 단위로 관련성 검사"""
        # 기사 목록 포맷팅
        articles_str = self._format_articles(batch)

        prompt = BATCH_RELEVANCE_PROMPT.format(articles=articles_str)

        response = model.generate_content(prompt)
        return self._parse_response(response.text, len(batch))

    def _format_articles(self, batch: List[SearchResult]) -> str:
        """기사 목록 포맷팅"""
        lines = []
        for i, result in enumerate(batch, 1):
            lines.append(f"[{i}] 제목: {result.title}")
            lines.append(f"    내용: {result.snippet[:200]}...")
            lines.append(f"    검색쿼리: {result.query}")
            lines.append("")
        return "\n".join(lines)

    def _parse_response(self, response: str, expected_count: int) -> List[dict]:
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
                # 파싱 실패시 모두 관련있다고 가정
                return [{"relevant": True, "reason": "파싱 실패"} for _ in range(expected_count)]

        # JSON 정리
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)

        try:
            data = json.loads(json_str)
            results = data.get("results", [])

            # 인덱스별로 정렬
            sorted_results = [{"relevant": True, "reason": ""}] * expected_count
            for r in results:
                idx = r.get("index", 0) - 1  # 1-based to 0-based
                if 0 <= idx < expected_count:
                    sorted_results[idx] = {
                        "relevant": r.get("relevant", True),
                        "reason": r.get("reason", "")
                    }

            return sorted_results

        except json.JSONDecodeError:
            return [{"relevant": True, "reason": "JSON 파싱 실패"} for _ in range(expected_count)]


def test_filter():
    """필터 테스트"""
    print("=== 관련성 필터 테스트 ===\n")

    # 테스트용 더미 데이터
    test_results = [
        SearchResult(
            title="LCD 패널 가격 상승세 지속",
            link="http://test.com/1",
            snippet="TV용 LCD 패널 가격이 상승세를 이어가고 있다.",
            date="2025-01-01",
            source="테스트",
            query="LCD 패널 가격"
        ),
        SearchResult(
            title="은 가격 급등, 투자자 주목",
            link="http://test.com/2",
            snippet="귀금속 시장에서 은 가격이 급등하고 있다.",
            date="2025-01-01",
            source="테스트",
            query="TV 패널 가격 급등"
        ),
    ]

    filter = RelevanceFilter()
    filtered, stats = filter.filter_results(test_results, verbose=True)

    print(f"\n결과: {len(filtered)}개 유지")


if __name__ == "__main__":
    test_filter()
