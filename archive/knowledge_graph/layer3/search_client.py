"""검색 클라이언트 - Serper API 기반 뉴스 수집

v2: Brave Search API → Serper API 전환
- Google 뉴스 검색 결과 제공
- POST 요청 방식
- tbs 파라미터로 시간 필터링
"""

import os
import time
import yaml
import requests
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# freshness → tbs 매핑
FRESHNESS_TO_TBS = {
    "pd": "qdr:d",   # past day
    "pw": "qdr:w",   # past week
    "pm": "qdr:m",   # past month
    "py": "qdr:y",   # past year
}


def build_date_range_tbs(start_date: str, end_date: str) -> str:
    """특정 날짜 범위를 위한 tbs 파라미터 생성

    Google Search 날짜 범위 형식:
    tbs=cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY

    Args:
        start_date: 시작일 (YYYY-MM-DD 형식)
        end_date: 종료일 (YYYY-MM-DD 형식)

    Returns:
        tbs 파라미터 값
    """
    from datetime import datetime as dt

    start = dt.strptime(start_date, "%Y-%m-%d")
    end = dt.strptime(end_date, "%Y-%m-%d")

    # MM/DD/YYYY 형식으로 변환
    start_str = start.strftime("%m/%d/%Y")
    end_str = end.strftime("%m/%d/%Y")

    return f"cdr:1,cd_min:{start_str},cd_max:{end_str}"


@dataclass
class SearchResult:
    """검색 결과"""
    title: str
    link: str
    snippet: str
    date: Optional[str] = None
    source: Optional[str] = None
    query: Optional[str] = None
    source_driver: Optional[str] = None  # 원본 Driver ID (Driver 기반 검색시)
    full_content: Optional[str] = None   # v4: 기사 전체 본문
    content_fetched: bool = False        # v4: 본문 fetch 여부

    def to_dict(self) -> dict:
        result = {
            "title": self.title,
            "link": self.link,
            "snippet": self.snippet,
            "date": self.date,
            "source": self.source,
            "query": self.query
        }
        if self.source_driver:
            result["source_driver"] = self.source_driver
        if self.full_content:
            result["full_content"] = self.full_content
        result["content_fetched"] = self.content_fetched
        return result


class SerperSearchClient:
    """Serper API 클라이언트 (Google Search)

    v2: Brave Search API → Serper API 전환
    """

    BASE_URL = "https://google.serper.dev"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self.api_key:
            raise ValueError("SERPER_API_KEY가 설정되지 않았습니다")

        self.headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        self.request_count = 0
        self.last_request_time = None

    def search_news(
        self,
        query: str,
        count: int = 20,
        freshness: str = "pm",  # pd=past day, pw=past week, pm=past month, py=past year
        date_range: Optional[tuple] = None  # (start_date, end_date) YYYY-MM-DD 형식
    ) -> List[SearchResult]:
        """뉴스 검색 (Serper API)

        Args:
            query: 검색어
            count: 결과 수 (num 파라미터)
            freshness: 시간 필터 (pd/pw/pm/py → tbs 변환), date_range 지정시 무시됨
            date_range: 특정 날짜 범위 (start_date, end_date) 튜플
        """
        url = f"{self.BASE_URL}/news"

        # 날짜 범위가 지정된 경우 해당 tbs 사용, 아니면 freshness 사용
        if date_range:
            tbs = build_date_range_tbs(date_range[0], date_range[1])
        else:
            tbs = FRESHNESS_TO_TBS.get(freshness)

        payload = {
            "q": query,
            "num": min(count, 100),  # Serper는 최대 100개
            "gl": "kr",   # 한국
            "hl": "ko"    # 한국어
        }
        if tbs:
            payload["tbs"] = tbs

        self._rate_limit()

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()

            self.request_count += 1
            results = []

            for item in data.get("news", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    link=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    date=item.get("date"),
                    source=item.get("source"),
                    query=query
                ))

            return results

        except requests.exceptions.RequestException as e:
            print(f"검색 오류 ({query}): {e}")
            return []

    def search_web(
        self,
        query: str,
        count: int = 10,
        freshness: str = "pm"
    ) -> List[SearchResult]:
        """일반 웹 검색 (Serper API)"""
        url = f"{self.BASE_URL}/search"

        # freshness → tbs 변환
        tbs = FRESHNESS_TO_TBS.get(freshness)

        payload = {
            "q": query,
            "num": min(count, 100),
            "gl": "kr",
            "hl": "ko"
        }
        if tbs:
            payload["tbs"] = tbs

        self._rate_limit()

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            data = response.json()

            self.request_count += 1
            results = []

            for item in data.get("organic", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    link=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    query=query
                ))

            return results

        except requests.exceptions.RequestException as e:
            print(f"검색 오류 ({query}): {e}")
            return []

    def _rate_limit(self, min_interval: float = 0.5):
        """Rate limiting (Serper는 더 관대함)"""
        if self.last_request_time:
            elapsed = time.time() - self.last_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self.last_request_time = time.time()


# 하위 호환성을 위한 별칭
BraveSearchClient = SerperSearchClient


class QueryLoader:
    """검색 쿼리 로더"""

    def __init__(self, queries_path: Optional[Path] = None):
        self.queries_path = queries_path or Path(__file__).parent / "search_queries.yaml"
        self.queries = self._load_queries()

    def _load_queries(self) -> Dict:
        """YAML에서 쿼리 로드"""
        with open(self.queries_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_all_queries(self) -> List[str]:
        """모든 쿼리 반환"""
        all_queries = []

        # 카테고리별 쿼리
        for category, queries in self.queries.get("categories", {}).items():
            all_queries.extend(queries)

        # 지역별 쿼리
        for region, queries in self.queries.get("regions", {}).items():
            all_queries.extend(queries)

        # 제품별 쿼리
        all_queries.extend(self.queries.get("products", []))

        return all_queries

    def get_queries_by_category(self, category: str) -> List[str]:
        """카테고리별 쿼리"""
        return self.queries.get("categories", {}).get(category, [])

    def get_queries_by_region(self, region: str) -> List[str]:
        """지역별 쿼리"""
        return self.queries.get("regions", {}).get(region, [])

    @property
    def total_queries(self) -> int:
        return len(self.get_all_queries())


class NewsCollector:
    """뉴스 수집기"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        queries_path: Optional[Path] = None
    ):
        self.client = BraveSearchClient(api_key)
        self.query_loader = QueryLoader(queries_path)
        self.results: List[SearchResult] = []

    def collect_all(
        self,
        count_per_query: int = 20,
        freshness: str = "pm",
        verbose: bool = True,
        date_range: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """모든 쿼리에 대해 뉴스 수집

        Args:
            date_range: 월별 날짜 리스트 (예: ["2025년 6월", "2025년 7월"])
                       지정시 각 쿼리에 날짜 추가
        """
        queries = self.query_loader.get_all_queries()

        # 날짜 범위 적용
        if date_range:
            dated_queries = []
            for q in queries:
                for month in date_range:
                    dated_queries.append(f"{q} {month}")
            queries = dated_queries
            if verbose:
                print(f"날짜 범위 적용: {date_range}")

        total = len(queries)

        if verbose:
            print(f"=== 뉴스 수집 시작 ===")
            print(f"총 쿼리: {total}개")
            print(f"쿼리당 결과: {count_per_query}개")
            print(f"예상 총 결과: ~{total * count_per_query}개")
            print()

        self.results = []

        for i, query in enumerate(queries, 1):
            results = self.client.search_news(
                query=query,
                count=count_per_query,
                freshness=freshness
            )
            self.results.extend(results)

            if verbose and i % 10 == 0:
                print(f"  진행: {i}/{total} ({len(self.results)}개 수집)")

        # 중복 제거 (URL 기준)
        unique_results = self._deduplicate()

        if verbose:
            print(f"\n=== 수집 완료 ===")
            print(f"총 검색 결과: {len(self.results)}개")
            print(f"중복 제거 후: {len(unique_results)}개")
            print(f"API 호출 횟수: {self.client.request_count}회")

        self.results = unique_results
        return unique_results

    def collect_with_queries(
        self,
        queries: List[str],
        count_per_query: int = 20,
        freshness: str = "pm",
        verbose: bool = True
    ) -> List[SearchResult]:
        """커스텀 쿼리 리스트로 뉴스 수집"""
        total = len(queries)

        if verbose:
            print(f"=== 뉴스 수집 시작 (커스텀 쿼리) ===")
            print(f"총 쿼리: {total}개")
            print(f"쿼리당 결과: {count_per_query}개")
            print(f"예상 총 결과: ~{total * count_per_query}개")
            print()

        self.results = []

        for i, query in enumerate(queries, 1):
            results = self.client.search_news(
                query=query,
                count=count_per_query,
                freshness=freshness
            )
            self.results.extend(results)

            if verbose and i % 10 == 0:
                print(f"  진행: {i}/{total} ({len(self.results)}개 수집)")

        # 중복 제거 (URL 기준)
        unique_results = self._deduplicate()

        if verbose:
            print(f"\n=== 수집 완료 ===")
            print(f"총 검색 결과: {len(self.results)}개")
            print(f"중복 제거 후: {len(unique_results)}개")
            print(f"API 호출 횟수: {self.client.request_count}회")

        self.results = unique_results
        return unique_results

    def collect_by_category(
        self,
        category: str,
        count_per_query: int = 20,
        freshness: str = "pm",
        verbose: bool = True
    ) -> List[SearchResult]:
        """카테고리별 뉴스 수집"""
        queries = self.query_loader.get_queries_by_category(category)

        if verbose:
            print(f"카테고리 '{category}' 검색: {len(queries)}개 쿼리")

        results = []
        for query in queries:
            query_results = self.client.search_news(
                query=query,
                count=count_per_query,
                freshness=freshness
            )
            results.extend(query_results)

        return self._deduplicate(results)

    def collect_by_driver(
        self,
        driver_queries: Dict[str, List[str]],
        count_per_query: int = 20,
        freshness: str = "pm",
        verbose: bool = True,
        date_range: Optional[tuple] = None  # (start_date, end_date) YYYY-MM-DD 형식
    ) -> List[SearchResult]:
        """Driver별 쿼리로 뉴스 수집 (원본 Driver 추적)

        Args:
            driver_queries: {driver_id: [쿼리 리스트]}
            count_per_query: 쿼리당 결과 수
            freshness: 검색 기간
            verbose: 진행 상황 출력
            date_range: 특정 날짜 범위 (start_date, end_date) 튜플

        Returns:
            source_driver가 설정된 SearchResult 리스트
        """
        # 전체 쿼리 수 계산
        total_queries = sum(len(q) for q in driver_queries.values())
        total_drivers = len(driver_queries)

        if verbose:
            print(f"=== Driver 기반 뉴스 수집 ===")
            print(f"대상 Driver: {total_drivers}개")
            print(f"총 쿼리: {total_queries}개")
            print(f"쿼리당 결과: {count_per_query}개")
            if date_range:
                print(f"날짜 범위: {date_range[0]} ~ {date_range[1]}")
            print(f"예상 총 결과: ~{total_queries * count_per_query}개")
            print()

        self.results = []
        query_count = 0

        for driver_id, queries in driver_queries.items():
            for query in queries:
                query_count += 1
                results = self.client.search_news(
                    query=query,
                    count=count_per_query,
                    freshness=freshness,
                    date_range=date_range
                )

                # 각 결과에 source_driver 설정
                for r in results:
                    r.source_driver = driver_id

                self.results.extend(results)

                if verbose and query_count % 20 == 0:
                    print(f"  진행: {query_count}/{total_queries} ({len(self.results)}개 수집)")

        # 중복 제거 (URL 기준, source_driver 유지)
        unique_results = self._deduplicate_with_driver()

        if verbose:
            print(f"\n=== 수집 완료 ===")
            print(f"총 검색 결과: {len(self.results)}개")
            print(f"중복 제거 후: {len(unique_results)}개")
            print(f"API 호출 횟수: {self.client.request_count}회")

            # Driver별 결과 수 출력
            driver_counts = {}
            for r in unique_results:
                driver_counts[r.source_driver] = driver_counts.get(r.source_driver, 0) + 1
            print(f"\nDriver별 결과 수:")
            for d, c in sorted(driver_counts.items(), key=lambda x: -x[1])[:10]:
                print(f"  {d}: {c}개")

        self.results = unique_results
        return unique_results

    def _deduplicate_with_driver(self) -> List[SearchResult]:
        """URL 기준 중복 제거 (source_driver 유지, 첫 번째 Driver 우선)"""
        seen_urls = {}
        unique = []

        for r in self.results:
            if r.link not in seen_urls:
                seen_urls[r.link] = r
                unique.append(r)
            # 같은 URL이 여러 Driver에서 검색된 경우, 첫 번째 유지

        return unique

    def _deduplicate(self, results: Optional[List[SearchResult]] = None) -> List[SearchResult]:
        """URL 기준 중복 제거"""
        results = results or self.results
        seen_urls = set()
        unique = []

        for r in results:
            if r.link not in seen_urls:
                seen_urls.add(r.link)
                unique.append(r)

        return unique

    def fetch_content_for_results(
        self,
        results: Optional[List[SearchResult]] = None,
        verbose: bool = True
    ) -> List[SearchResult]:
        """검색 결과의 URL에서 기사 본문을 가져옴

        Args:
            results: 검색 결과 리스트 (None이면 self.results 사용)
            verbose: 진행 상황 출력

        Returns:
            full_content가 채워진 SearchResult 리스트
        """
        from .content_fetcher import ContentFetcher

        results = results or self.results
        if not results:
            return []

        if verbose:
            print(f"\n=== 기사 본문 추출 시작 ({len(results)}개) ===")

        # URL 리스트 추출
        urls = [r.link for r in results]

        # 병렬 fetch
        fetcher = ContentFetcher(max_content_length=3000, max_workers=10)
        content_map = fetcher.fetch_batch(urls, verbose=verbose)

        # 결과에 본문 추가
        success_count = 0
        for result in results:
            content = content_map.get(result.link, "")
            if content:
                result.full_content = content
                result.content_fetched = True
                success_count += 1
            else:
                result.content_fetched = False

        if verbose:
            print(f"본문 추출 성공: {success_count}/{len(results)}개")

        self.results = results
        return results

    def save_results(self, output_path: Path) -> None:
        """결과 저장"""
        import json
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "collected_at": datetime.now().isoformat(),
                    "total_results": len(self.results),
                    "results": [r.to_dict() for r in self.results]
                },
                f,
                ensure_ascii=False,
                indent=2
            )
        print(f"저장 완료: {output_path}")


def test_brave_search():
    """Brave Search API 테스트"""
    print("=== Brave Search API 테스트 ===\n")

    client = BraveSearchClient()

    # 테스트 쿼리
    test_queries = [
        "홍해 사태 해운",
        "LCD 패널 가격",
        "트럼프 관세 TV"
    ]

    for query in test_queries:
        print(f"쿼리: '{query}'")
        results = client.search_news(query, count=5, freshness="pm")
        print(f"  결과: {len(results)}개")
        for r in results[:2]:
            print(f"  - {r.title[:50]}...")
            print(f"    {r.date} | {r.source}")
        print()


if __name__ == "__main__":
    test_brave_search()
