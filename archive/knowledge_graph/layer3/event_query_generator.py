"""Driver 기반 검색 쿼리 생성기

v2.1: 40개 Driver별 검색 쿼리 정의
- 각 Driver에 대해 3~6개 검색 쿼리 템플릿
- news_searchable 플래그로 뉴스 검색 적합성 표시
- Tier 1/2/3 구분
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class DriverQueryInfo:
    """Driver 쿼리 정보"""
    driver_id: str
    name_kr: str
    description: str
    news_searchable: bool
    queries: List[str]


@dataclass
class QueryWithContext:
    """컨텍스트가 포함된 쿼리"""
    query: str
    driver_id: str
    driver_name: str
    news_searchable: bool


class DriverQueryGenerator:
    """Driver 기반 검색 쿼리 생성기"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path(__file__).parent / "search_queries_v2.yaml"
        self.config = self._load_config()
        self.drivers = self._parse_drivers()

    def _load_config(self) -> dict:
        """YAML 설정 로드"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _parse_drivers(self) -> Dict[str, DriverQueryInfo]:
        """Driver 정보 파싱"""
        drivers = {}
        for driver_id, data in self.config.get("drivers", {}).items():
            drivers[driver_id] = DriverQueryInfo(
                driver_id=driver_id,
                name_kr=data.get("name_kr", driver_id),
                description=data.get("description", ""),
                news_searchable=data.get("news_searchable", True),
                queries=data.get("queries", [])
            )
        return drivers

    def get_all_queries(self, news_searchable_only: bool = True) -> List[QueryWithContext]:
        """모든 Driver의 쿼리 반환 (컨텍스트 포함)

        Args:
            news_searchable_only: True면 news_searchable=True인 Driver만

        Returns:
            QueryWithContext 리스트 (query, driver_id, driver_name, news_searchable)
        """
        result = []
        for driver_id, info in self.drivers.items():
            if news_searchable_only and not info.news_searchable:
                continue
            for query in info.queries:
                result.append(QueryWithContext(
                    query=query,
                    driver_id=driver_id,
                    driver_name=info.name_kr,
                    news_searchable=info.news_searchable
                ))
        return result

    def get_queries_flat(self, news_searchable_only: bool = True) -> List[str]:
        """모든 쿼리를 flat 리스트로 반환"""
        return [q.query for q in self.get_all_queries(news_searchable_only)]

    def get_queries_by_driver(
        self,
        driver_ids: Optional[List[str]] = None,
        news_searchable_only: bool = True
    ) -> Dict[str, List[str]]:
        """Driver별 쿼리 반환

        Args:
            driver_ids: 특정 Driver만 (None이면 전체)
            news_searchable_only: True면 news_searchable=True인 Driver만

        Returns:
            {driver_id: [queries]}
        """
        result = {}
        target_drivers = driver_ids or list(self.drivers.keys())

        for driver_id in target_drivers:
            if driver_id in self.drivers:
                info = self.drivers[driver_id]
                if news_searchable_only and not info.news_searchable:
                    continue
                result[driver_id] = info.queries

        return result

    def get_searchable_drivers(self) -> List[str]:
        """뉴스 검색 가능한 Driver ID 목록"""
        return [
            driver_id
            for driver_id, info in self.drivers.items()
            if info.news_searchable
        ]

    def get_unsearchable_drivers(self) -> List[str]:
        """뉴스 검색 부적합한 Driver ID 목록"""
        return [
            driver_id
            for driver_id, info in self.drivers.items()
            if not info.news_searchable
        ]

    def get_filter_rules(self) -> dict:
        """필터링 규칙 반환"""
        return self.config.get("filter_rules", {})

    def summary(self) -> dict:
        """요약 정보 반환"""
        searchable = [d for d in self.drivers.values() if d.news_searchable]
        unsearchable = [d for d in self.drivers.values() if not d.news_searchable]
        total_queries_searchable = sum(len(d.queries) for d in searchable)
        total_queries_all = sum(len(d.queries) for d in self.drivers.values())

        return {
            "total_drivers": len(self.drivers),
            "searchable_drivers": len(searchable),
            "unsearchable_drivers": len(unsearchable),
            "total_queries_searchable": total_queries_searchable,
            "total_queries_all": total_queries_all,
            "drivers": list(self.drivers.keys())
        }

    def print_summary(self, show_queries: bool = False):
        """요약 정보 출력"""
        print("=== Driver 기반 쿼리 생성기 ===")
        summary = self.summary()
        print(f"전체 Driver: {summary['total_drivers']}개")
        print(f"  - 뉴스 검색 가능: {summary['searchable_drivers']}개")
        print(f"  - 뉴스 검색 부적합: {summary['unsearchable_drivers']}개")
        print(f"검색 가능 쿼리: {summary['total_queries_searchable']}개")

        if show_queries:
            print("\n--- Driver별 쿼리 ---")
            for driver_id, info in self.drivers.items():
                searchable_mark = "✓" if info.news_searchable else "✗"
                print(f"\n[{searchable_mark}] {driver_id} ({info.name_kr})")
                print(f"    설명: {info.description}")
                print(f"    쿼리 ({len(info.queries)}개):")
                for q in info.queries:
                    print(f"      - {q}")

        # 검색 부적합 Driver 목록
        unsearchable = self.get_unsearchable_drivers()
        if unsearchable:
            print(f"\n뉴스 검색 부적합 Driver ({len(unsearchable)}개):")
            for driver_id in unsearchable:
                info = self.drivers[driver_id]
                print(f"  - {driver_id} ({info.name_kr})")


# ============================================================================
# 하위 호환성을 위한 별칭
# ============================================================================

# 기존 EventQueryGenerator 이름도 유지 (하위 호환성)
EventQueryGenerator = DriverQueryGenerator
EventTypeInfo = DriverQueryInfo


def test_driver_query_generator():
    """테스트"""
    print("=== DriverQueryGenerator 테스트 ===\n")

    generator = DriverQueryGenerator()
    generator.print_summary(show_queries=False)

    print("\n" + "=" * 50)
    print("샘플 쿼리 (검색 가능 Driver에서 처음 15개)")
    print("=" * 50)
    for i, q in enumerate(generator.get_all_queries(news_searchable_only=True)[:15], 1):
        print(f"{i}. [{q.driver_id}] {q.query}")

    print("\n" + "=" * 50)
    print("Driver별 쿼리 수")
    print("=" * 50)
    by_driver = generator.get_queries_by_driver(news_searchable_only=False)
    for driver_id, queries in by_driver.items():
        info = generator.drivers[driver_id]
        mark = "✓" if info.news_searchable else "✗"
        print(f"  [{mark}] {driver_id}: {len(queries)}개")


if __name__ == "__main__":
    test_driver_query_generator()
