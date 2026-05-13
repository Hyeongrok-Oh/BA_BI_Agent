"""URL에서 뉴스 기사 본문을 추출하는 모듈

trafilatura 라이브러리를 사용하여 URL에서 기사 본문 텍스트를 추출합니다.
병렬 처리를 지원하며, 에러 발생 시 빈 문자열을 반환합니다.
"""

import logging
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import trafilatura

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Fetch 결과"""
    url: str
    content: str
    success: bool
    error: Optional[str] = None


class ContentFetcher:
    """URL에서 뉴스 기사 본문을 추출하는 클래스"""

    def __init__(
        self,
        max_content_length: int = 3000,
        timeout: int = 10,
        max_workers: int = 10
    ):
        """
        Args:
            max_content_length: 추출할 본문 최대 길이 (기본 3000자)
            timeout: HTTP 요청 타임아웃 (초)
            max_workers: 병렬 처리 워커 수
        """
        self.max_content_length = max_content_length
        self.timeout = timeout
        self.max_workers = max_workers

    def fetch(self, url: str) -> str:
        """단일 URL에서 기사 본문 추출

        Args:
            url: 뉴스 기사 URL

        Returns:
            추출된 본문 텍스트 (실패 시 빈 문자열)
        """
        try:
            # trafilatura로 본문 추출
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                logger.debug(f"Failed to download: {url}")
                return ""

            # 본문 텍스트 추출
            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False
            )

            if not text:
                logger.debug(f"Failed to extract content: {url}")
                return ""

            # 길이 제한
            if len(text) > self.max_content_length:
                text = text[:self.max_content_length] + "..."

            return text

        except Exception as e:
            logger.debug(f"Error fetching {url}: {e}")
            return ""

    def fetch_with_result(self, url: str) -> FetchResult:
        """단일 URL에서 기사 본문 추출 (상세 결과 반환)

        Args:
            url: 뉴스 기사 URL

        Returns:
            FetchResult (success, content, error)
        """
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return FetchResult(url=url, content="", success=False, error="Download failed")

            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False
            )

            if not text:
                return FetchResult(url=url, content="", success=False, error="Extraction failed")

            if len(text) > self.max_content_length:
                text = text[:self.max_content_length] + "..."

            return FetchResult(url=url, content=text, success=True)

        except Exception as e:
            return FetchResult(url=url, content="", success=False, error=str(e))

    def fetch_batch(
        self,
        urls: List[str],
        verbose: bool = True
    ) -> Dict[str, str]:
        """여러 URL에서 기사 본문 병렬 추출

        Args:
            urls: URL 리스트
            verbose: 진행 상황 출력

        Returns:
            {url: content} 딕셔너리
        """
        results = {}
        success_count = 0
        fail_count = 0

        if verbose:
            print(f"=== 기사 본문 추출 ({len(urls)}개) ===")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_url = {
                executor.submit(self.fetch_with_result, url): url
                for url in urls
            }

            # Collect results
            for future in as_completed(future_to_url):
                result = future.result()
                results[result.url] = result.content

                if result.success:
                    success_count += 1
                else:
                    fail_count += 1

                if verbose and (success_count + fail_count) % 10 == 0:
                    print(f"  진행: {success_count + fail_count}/{len(urls)} "
                          f"(성공: {success_count}, 실패: {fail_count})")

        if verbose:
            print(f"\n=== 추출 완료 ===")
            print(f"성공: {success_count}개")
            print(f"실패: {fail_count}개")

        return results


def test_content_fetcher():
    """테스트"""
    print("=== ContentFetcher 테스트 ===\n")

    fetcher = ContentFetcher(max_content_length=500)

    # 테스트 URL (한국 뉴스)
    test_urls = [
        "https://www.news1.kr/industry/general-industry/6009294",
        "https://www.thelec.kr/news/articleView.html?idxno=45032",
    ]

    for url in test_urls:
        print(f"\nURL: {url}")
        result = fetcher.fetch_with_result(url)
        print(f"성공: {result.success}")
        if result.success:
            print(f"본문 ({len(result.content)}자): {result.content[:200]}...")
        else:
            print(f"에러: {result.error}")


if __name__ == "__main__":
    test_content_fetcher()
