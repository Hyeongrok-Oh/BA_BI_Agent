"""Layer 3 메인 실행 파일"""

import json
import argparse
from pathlib import Path
from datetime import datetime

from .search_client import NewsCollector
from .event_extractor import Layer3Builder
from .normalizer import normalize_layer3
from .vector_store import process_layer3_vectors
from .neo4j_loader import load_layer3_to_neo4j
from .models import Layer3Graph
from .query_expander import UpstreamQueryExpander
from .driver_query_generator import DriverQueryGenerator
from .event_query_generator import DriverQueryGenerator as TemplateQueryGenerator
from .relevance_filter import RelevanceFilter


def build_layer3(
    max_queries: int = 60,
    results_per_query: int = 20,
    freshness: str = "pm",  # past month
    skip_vectors: bool = False,
    date_range: list = None,
    verbose: bool = True
) -> Layer3Graph:
    """Layer 3 전체 파이프라인 실행"""
    layer3_dir = Path(__file__).parent

    # 1. 뉴스 수집
    if verbose:
        print("=" * 50)
        print("Phase 1: 뉴스 수집")
        print("=" * 50)

    collector = NewsCollector()
    all_queries = collector.query_loader.get_all_queries()[:max_queries]

    # 쿼리 제한
    collector.query_loader.queries["categories"] = {
        k: v[:max_queries // 6] for k, v in
        collector.query_loader.queries.get("categories", {}).items()
    }

    search_results = collector.collect_all(
        count_per_query=results_per_query,
        freshness=freshness,
        verbose=verbose,
        date_range=date_range
    )

    # 중간 결과 저장
    search_output = layer3_dir / "search_results.json"
    collector.save_results(search_output)

    # 2. Event 추출
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 2: Event 추출")
        print("=" * 50)

    builder = Layer3Builder()
    graph = builder.build_from_search_results(
        search_results,
        batch_size=10,
        verbose=verbose
    )

    # 3. 정규화
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 3: Event 정규화")
        print("=" * 50)

    graph = normalize_layer3(graph)

    # 4. Vector 처리
    if not skip_vectors:
        if verbose:
            print("\n" + "=" * 50)
            print("Phase 4: Vector Embedding 생성")
            print("=" * 50)

        graph = process_layer3_vectors(graph, verbose=verbose)

    # 결과 저장
    output_path = layer3_dir / "layer3_result.json"
    save_layer3_result(graph, output_path)

    return graph


def build_layer3_from_driver(
    queries_per_driver: int = 3,
    results_per_query: int = 20,
    freshness: str = "pm",  # past month
    skip_vectors: bool = False,
    date_range: list = None,  # 예: ["2025년 6월", "2025년 7월"] - 쿼리 텍스트에 추가
    start_date: str = None,  # 검색 시작일 (YYYY-MM-DD 형식)
    end_date: str = None,  # 검색 종료일 (YYYY-MM-DD 형식)
    driver_ids: list = None,  # 특정 Driver만 처리 (None이면 전체)
    verbose: bool = True
) -> Layer3Graph:
    """Driver 기반 Layer 3 파이프라인 실행 (v5: 분리 연결 모드)

    1. Driver별 검색 쿼리 생성 (LLM)
    2. 뉴스 검색 & 수집
    3. Event 추출 (Driver 연결 없이)
    4. Event-Driver 연결 (별도 LLM 단계, evidence 포함)
    5. 정규화 & Vector 처리
    """
    layer3_dir = Path(__file__).parent

    # 1. LLM으로 Driver별 쿼리 생성
    if verbose:
        print("=" * 50)
        print("Phase 1: Driver 기반 검색 쿼리 생성")
        print("=" * 50)
        if start_date and end_date:
            print(f"검색 날짜 범위: {start_date} ~ {end_date}")
        if date_range:
            print(f"쿼리 텍스트 날짜: {date_range}")

    generator = DriverQueryGenerator()
    driver_queries = generator.generate_queries(
        queries_per_driver=queries_per_driver,
        driver_ids=driver_ids,
        verbose=verbose
    )

    # 날짜 범위 적용
    if date_range:
        driver_queries = generator.apply_date_range(driver_queries, date_range)
        if verbose:
            total_queries = sum(len(r.queries) for r in driver_queries.values())
            print(f"\n날짜 범위 적용 후 총 쿼리: {total_queries}개")

    # DriverQueryResult → Dict[str, List[str]] 변환 (collect_by_driver용)
    queries_dict = generator.get_queries_dict(driver_queries)

    # 2. Driver별 뉴스 수집
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 2: 뉴스 수집")
        print("=" * 50)

    collector = NewsCollector()

    # 날짜 범위 튜플 생성 (start_date, end_date 둘 다 있을 때만)
    api_date_range = None
    if start_date and end_date:
        api_date_range = (start_date, end_date)

    search_results = collector.collect_by_driver(
        driver_queries=queries_dict,
        count_per_query=results_per_query,
        freshness=freshness,
        verbose=verbose,
        date_range=api_date_range
    )

    # 중간 결과 저장
    search_output = layer3_dir / "search_results_driver.json"
    collector.save_results(search_output)

    # 2.5. 검색 결과 필터링 (관련 없는 기사 제거)
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 2.5: 검색 결과 필터링")
        print("=" * 50)

    relevance_filter = RelevanceFilter()
    search_results, filter_stats = relevance_filter.filter_results(
        search_results,
        batch_size=20,
        verbose=verbose
    )

    # 3. Event 추출 + Driver 연결 (분리 모드)
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 3: Event 추출 (Driver 연결 분리)")
        print("=" * 50)

    builder = Layer3Builder()
    graph = builder.build_with_separate_linking(
        search_results,
        batch_size=10,
        verbose=verbose
    )

    # 4. 정규화
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 4: Event 정규화")
        print("=" * 50)

    graph = normalize_layer3(graph)

    # 5. Vector 처리
    if not skip_vectors:
        if verbose:
            print("\n" + "=" * 50)
            print("Phase 5: Vector Embedding 생성")
            print("=" * 50)

        graph = process_layer3_vectors(graph, verbose=verbose)

    # 결과 저장
    output_path = layer3_dir / "layer3_result_driver.json"
    save_layer3_result(graph, output_path)

    return graph


def build_layer3_from_event(
    results_per_query: int = 5,
    freshness: str = "pm",  # past month
    skip_vectors: bool = False,
    start_date: str = None,  # 검색 시작일 (YYYY-MM-DD 형식)
    end_date: str = None,  # 검색 종료일 (YYYY-MM-DD 형식)
    driver_ids: list = None,  # 특정 Driver만 처리 (None이면 전체)
    fetch_content: bool = False,  # v4: URL에서 기사 본문 fetch
    verbose: bool = True
) -> Layer3Graph:
    """Driver 템플릿 기반 Layer 3 파이프라인 실행 (v2.1: Driver별 쿼리 템플릿)

    1. 사전 정의된 Driver별 검색 쿼리 템플릿 사용
    2. 뉴스 검색 & 수집
    2.5. (옵션) URL에서 기사 본문 fetch
    3. 검색 결과 필터링
    4. Event 추출 + Driver 연결 (분리 모드)
    5. 정규화 & Vector 처리
    """
    layer3_dir = Path(__file__).parent

    # 1. Driver 기반 쿼리 로드
    if verbose:
        print("=" * 50)
        print("Phase 1: Driver 템플릿 기반 검색 쿼리 로드")
        print("=" * 50)
        if start_date and end_date:
            print(f"검색 날짜 범위: {start_date} ~ {end_date}")

    generator = TemplateQueryGenerator()

    if verbose:
        summary = generator.summary()
        print(f"전체 Driver: {summary['total_drivers']}개")
        print(f"  - 뉴스 검색 가능: {summary['searchable_drivers']}개")
        print(f"  - 뉴스 검색 부적합: {summary['unsearchable_drivers']}개")
        print(f"검색 가능 쿼리: {summary['total_queries_searchable']}개")

    # Driver별 쿼리 가져오기 (news_searchable=True인 것만)
    queries_by_driver = generator.get_queries_by_driver(
        driver_ids=driver_ids,
        news_searchable_only=True
    )

    if verbose:
        print(f"\n대상 Driver: {len(queries_by_driver)}개")
        total_queries = sum(len(qs) for qs in queries_by_driver.values())
        print(f"총 쿼리: {total_queries}개")

        if driver_ids:
            print(f"\n필터링된 Driver:")
            for driver_id, queries in queries_by_driver.items():
                print(f"  [{driver_id}] {len(queries)}개 쿼리")

    # 2. 뉴스 수집
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 2: 뉴스 수집")
        print("=" * 50)

    collector = NewsCollector()

    # 날짜 범위 튜플 생성
    api_date_range = None
    if start_date and end_date:
        api_date_range = (start_date, end_date)

    # 모든 쿼리를 flat 리스트로
    all_queries = generator.get_queries_flat(news_searchable_only=True)
    if driver_ids:
        # 특정 Driver만 필터링
        all_queries = []
        for driver_id in driver_ids:
            if driver_id in queries_by_driver:
                all_queries.extend(queries_by_driver[driver_id])

    if verbose:
        print(f"실행할 쿼리: {len(all_queries)}개")

    # 날짜 범위가 있으면 API 레벨에서 필터링
    if api_date_range:
        if verbose:
            print(f"날짜 범위 적용: {start_date} ~ {end_date}")

        search_results = []
        for i, query in enumerate(all_queries):
            results = collector.client.search_news(
                query=query,
                count=results_per_query,
                freshness=freshness,
                date_range=api_date_range
            )
            search_results.extend(results)
            if verbose and (i + 1) % 10 == 0:
                print(f"  진행: {i + 1}/{len(all_queries)} ({len(search_results)}개 수집)")
    else:
        # 날짜 범위 없이 수집
        search_results = collector.collect_with_queries(
            queries=all_queries,
            count_per_query=results_per_query,
            freshness=freshness,
            verbose=verbose
        )

    # 중복 제거
    seen_urls = set()
    unique_results = []
    for r in search_results:
        if r.link not in seen_urls:
            seen_urls.add(r.link)
            unique_results.append(r)
    search_results = unique_results

    if verbose:
        print(f"중복 제거 후: {len(search_results)}개")

    # 2.3. (옵션) 기사 본문 fetch
    if fetch_content:
        if verbose:
            print("\n" + "=" * 50)
            print("Phase 2.3: 기사 본문 추출")
            print("=" * 50)

        collector.results = search_results
        search_results = collector.fetch_content_for_results(
            search_results,
            verbose=verbose
        )

        # 본문 fetch 성공률 출력
        if verbose:
            fetched_count = sum(1 for r in search_results if r.content_fetched)
            print(f"본문 추출 성공: {fetched_count}/{len(search_results)}개")

    # 중간 결과 저장
    collector.results = search_results
    search_output = layer3_dir / "search_results_event.json"
    collector.save_results(search_output)

    # 2.5. 검색 결과 필터링
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 2.5: 검색 결과 필터링")
        print("=" * 50)

    relevance_filter = RelevanceFilter()
    search_results, filter_stats = relevance_filter.filter_results(
        search_results,
        batch_size=20,
        verbose=verbose
    )

    # 3. Event 추출 + Driver 연결 (분리 모드)
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 3: Event 추출 (Driver 연결 분리)")
        print("=" * 50)

    builder = Layer3Builder()
    graph = builder.build_with_separate_linking(
        search_results,
        batch_size=10,
        verbose=verbose
    )

    # 4. 정규화
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 4: Event 정규화")
        print("=" * 50)

    graph = normalize_layer3(graph)

    # 5. Vector 처리
    if not skip_vectors:
        if verbose:
            print("\n" + "=" * 50)
            print("Phase 5: Vector Embedding 생성")
            print("=" * 50)

        graph = process_layer3_vectors(graph, verbose=verbose)

    # 결과 저장
    output_path = layer3_dir / "layer3_result_event.json"
    save_layer3_result(graph, output_path)

    return graph


def build_layer3_from_upstream(
    max_queries: int = 100,
    results_per_query: int = 20,
    freshness: str = "pm",  # past month
    skip_vectors: bool = False,
    date_range: list = None,  # 예: ["2025년 6월", "2025년 7월"]
    verbose: bool = True
) -> Layer3Graph:
    """Upstream Factor 기반 Layer 3 파이프라인 실행

    Neo4j의 Upstream → Core Factor 관계를 기반으로
    동적으로 검색 쿼리를 생성하여 뉴스 수집 및 Event 추출
    """
    layer3_dir = Path(__file__).parent

    # 1. 동적 쿼리 생성
    if verbose:
        print("=" * 50)
        print("Phase 1: Upstream Factor 기반 쿼리 생성")
        print("=" * 50)
        if date_range:
            print(f"날짜 범위: {date_range}")

    with UpstreamQueryExpander() as expander:
        queries = expander.expand_queries(max_queries=max_queries, date_range=date_range)

    if verbose:
        print(f"생성된 쿼리: {len(queries)}개")
        print(f"샘플 쿼리:")
        for q in queries[:5]:
            print(f"  - {q}")
        print()

    # 2. 뉴스 수집
    if verbose:
        print("=" * 50)
        print("Phase 2: 뉴스 수집")
        print("=" * 50)

    collector = NewsCollector()
    search_results = collector.collect_with_queries(
        queries=queries,
        count_per_query=results_per_query,
        freshness=freshness,
        verbose=verbose
    )

    # 중간 결과 저장
    search_output = layer3_dir / "search_results_upstream.json"
    collector.save_results(search_output)

    # 3. Event 추출
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 3: Event 추출")
        print("=" * 50)

    builder = Layer3Builder()
    graph = builder.build_from_search_results(
        search_results,
        batch_size=10,
        verbose=verbose
    )

    # 4. 정규화
    if verbose:
        print("\n" + "=" * 50)
        print("Phase 4: Event 정규화")
        print("=" * 50)

    graph = normalize_layer3(graph)

    # 5. Vector 처리
    if not skip_vectors:
        if verbose:
            print("\n" + "=" * 50)
            print("Phase 5: Vector Embedding 생성")
            print("=" * 50)

        graph = process_layer3_vectors(graph, verbose=verbose)

    # 결과 저장
    output_path = layer3_dir / "layer3_result_upstream.json"
    save_layer3_result(graph, output_path)

    return graph


def save_layer3_result(graph: Layer3Graph, output_path: Path) -> None:
    """Layer 3 결과 저장"""
    result = {
        "generated_at": datetime.now().isoformat(),
        "summary": graph.summary(),
        "events": [e.to_dict() for e in graph.events],
        "chunks": [c.to_dict() for c in graph.chunks] if graph.chunks else []
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {output_path}")


def load_and_process(input_path: Path, skip_vectors: bool = False) -> Layer3Graph:
    """저장된 결과 로드 및 처리"""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Layer3Graph 재구성
    from .models import (
        EventNode, EventCategory, Severity, ImpactType,
        EventFactorRelation, EventDimensionRelation, EventSource
    )

    graph = Layer3Graph()

    for e_data in data.get("events", []):
        # Factor 관계 파싱
        factor_relations = []
        for fr in e_data.get("factor_relations", []):
            factor_relations.append(EventFactorRelation(
                factor_name=fr.get("factor", ""),
                factor_id=fr.get("factor_id", fr.get("factor", "")),  # v4: factor_id 유지
                impact_type=ImpactType(fr.get("impact", "INCREASES")),
                magnitude=fr.get("magnitude", "medium"),
                polarity=fr.get("polarity", 0),
                weight=fr.get("weight", 1.0),
                evidence=fr.get("evidence", ""),
            ))

        # Dimension 관계 파싱
        dimension_relations = []
        for dr in e_data.get("dimension_relations", []):
            dimension_relations.append(EventDimensionRelation(
                dimension_name=dr.get("dimension", ""),
                dimension_type=dr.get("type", "Region"),
                dimension_id=dr.get("dimension_id", ""),
            ))

        # Sources 파싱 (v4: search_query 포함)
        sources = []
        for s in e_data.get("sources", []):
            sources.append(EventSource(
                url=s.get("url", ""),
                title=s.get("title", ""),
                snippet=s.get("snippet", ""),
                source_name=s.get("source_name", ""),
                search_query=s.get("search_query", ""),  # v4: 검색 쿼리
            ))

        event = EventNode(
            id=e_data.get("id", ""),
            name=e_data.get("name", ""),
            name_en=e_data.get("name_en"),
            category=EventCategory(e_data.get("category", "market")),
            severity=Severity(e_data.get("severity", "medium")),
            is_ongoing=e_data.get("is_ongoing", False),
            factor_relations=factor_relations,
            dimension_relations=dimension_relations,
            sources=sources,  # v4: sources 추가
            evidence=e_data.get("evidence", ""),
            source_driver=e_data.get("source_driver"),  # v3: source_driver
        )

        graph.events.append(event)

    # Vector 처리
    if not skip_vectors and not graph.chunks:
        graph = process_layer3_vectors(graph, verbose=True)

    return graph


def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(description="Layer 3 Event 추출 및 적재")
    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # build 명령어
    build_parser = subparsers.add_parser("build", help="뉴스 수집 및 Event 추출")
    build_parser.add_argument("--max-queries", type=int, default=60, help="최대 쿼리 수")
    build_parser.add_argument("--results-per-query", type=int, default=20, help="쿼리당 결과 수")
    build_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    build_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    build_parser.add_argument("--date-range", type=str, nargs="+", help="월별 날짜 범위 (예: '2025년 6월' '2025년 7월')")

    # build-upstream 명령어 (신규)
    upstream_parser = subparsers.add_parser("build-upstream", help="Upstream Factor 기반 Event 추출")
    upstream_parser.add_argument("--max-queries", type=int, default=100, help="최대 쿼리 수")
    upstream_parser.add_argument("--results-per-query", type=int, default=20, help="쿼리당 결과 수")
    upstream_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    upstream_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    upstream_parser.add_argument("--date-range", type=str, nargs="+", help="월별 날짜 범위 (예: '2025년 6월' '2025년 7월')")

    # load 명령어
    load_parser = subparsers.add_parser("load", help="Neo4j에 적재")
    load_parser.add_argument("--input", type=str, default="layer3_result.json", help="입력 파일")
    load_parser.add_argument("--no-clear", action="store_true", help="기존 데이터 유지")

    # full 명령어 (build + load)
    full_parser = subparsers.add_parser("full", help="전체 파이프라인 (build + load)")
    full_parser.add_argument("--max-queries", type=int, default=60, help="최대 쿼리 수")
    full_parser.add_argument("--results-per-query", type=int, default=20, help="쿼리당 결과 수")
    full_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    full_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    full_parser.add_argument("--date-range", type=str, nargs="+", help="월별 날짜 범위 (예: '2025년 6월' '2025년 7월')")

    # full-upstream 명령어 (신규)
    full_upstream_parser = subparsers.add_parser("full-upstream", help="Upstream 기반 전체 파이프라인")
    full_upstream_parser.add_argument("--max-queries", type=int, default=100, help="최대 쿼리 수")
    full_upstream_parser.add_argument("--results-per-query", type=int, default=20, help="쿼리당 결과 수")
    full_upstream_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")

    # build-driver 명령어 (v3: Driver 기반 검색)
    driver_parser = subparsers.add_parser("build-driver", help="Driver 기반 Event 추출 (LLM 쿼리 생성)")
    driver_parser.add_argument("--queries-per-driver", type=int, default=3, help="Driver당 쿼리 수")
    driver_parser.add_argument("--results-per-query", type=int, default=20, help="쿼리당 결과 수")
    driver_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    driver_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    driver_parser.add_argument("--date-range", type=str, nargs="+", help="월별 날짜 범위 (예: '2025년 6월' '2025년 7월') - 쿼리에 추가됨")
    driver_parser.add_argument("--start-date", type=str, help="검색 시작일 (YYYY-MM-DD 형식, 예: 2025-06-01)")
    driver_parser.add_argument("--end-date", type=str, help="검색 종료일 (YYYY-MM-DD 형식, 예: 2025-09-30)")
    driver_parser.add_argument("--drivers", type=str, nargs="+", help="특정 Driver만 처리 (예: '물류비' '패널원가')")

    # full-driver 명령어 (v3: Driver 기반 전체 파이프라인)
    full_driver_parser = subparsers.add_parser("full-driver", help="Driver 기반 전체 파이프라인 (build + load)")
    full_driver_parser.add_argument("--queries-per-driver", type=int, default=3, help="Driver당 쿼리 수")
    full_driver_parser.add_argument("--results-per-query", type=int, default=20, help="쿼리당 결과 수")
    full_driver_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    full_driver_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    full_driver_parser.add_argument("--date-range", type=str, nargs="+", help="월별 날짜 범위 (예: '2025년 6월' '2025년 7월') - 쿼리에 추가됨")
    full_driver_parser.add_argument("--start-date", type=str, help="검색 시작일 (YYYY-MM-DD 형식, 예: 2025-06-01)")
    full_driver_parser.add_argument("--end-date", type=str, help="검색 종료일 (YYYY-MM-DD 형식, 예: 2025-09-30)")
    full_driver_parser.add_argument("--drivers", type=str, nargs="+", help="특정 Driver만 처리 (예: '물류비' '패널원가')")

    # build-event 명령어 (v2.1: Driver 템플릿 기반)
    event_parser = subparsers.add_parser("build-event", help="Driver 템플릿 기반 Event 추출 (40개 Driver별 쿼리)")
    event_parser.add_argument("--results-per-query", type=int, default=5, help="쿼리당 결과 수")
    event_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    event_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    event_parser.add_argument("--start-date", type=str, help="검색 시작일 (YYYY-MM-DD 형식, 예: 2025-06-01)")
    event_parser.add_argument("--end-date", type=str, help="검색 종료일 (YYYY-MM-DD 형식, 예: 2025-09-30)")
    event_parser.add_argument("--drivers", type=str, nargs="+", help="특정 Driver만 (예: '패널원가' '물류비' '경쟁사점유율')")
    event_parser.add_argument("--fetch-content", action="store_true", help="URL에서 기사 본문 추출 (정확도 향상, 시간 증가)")

    # full-event 명령어 (v2.1: Driver 템플릿 기반 전체 파이프라인)
    full_event_parser = subparsers.add_parser("full-event", help="Driver 템플릿 기반 전체 파이프라인 (build + load)")
    full_event_parser.add_argument("--results-per-query", type=int, default=5, help="쿼리당 결과 수")
    full_event_parser.add_argument("--skip-vectors", action="store_true", help="Vector 생성 건너뛰기")
    full_event_parser.add_argument("--freshness", type=str, default="pm", help="검색 기간 (pd/pw/pm/py)")
    full_event_parser.add_argument("--start-date", type=str, help="검색 시작일 (YYYY-MM-DD 형식, 예: 2025-06-01)")
    full_event_parser.add_argument("--end-date", type=str, help="검색 종료일 (YYYY-MM-DD 형식, 예: 2025-09-30)")
    full_event_parser.add_argument("--drivers", type=str, nargs="+", help="특정 Driver만 (예: '패널원가' '물류비' '경쟁사점유율')")
    full_event_parser.add_argument("--fetch-content", action="store_true", help="URL에서 기사 본문 추출 (정확도 향상, 시간 증가)")

    args = parser.parse_args()

    if args.command == "build":
        graph = build_layer3(
            max_queries=args.max_queries,
            results_per_query=args.results_per_query,
            skip_vectors=args.skip_vectors,
            freshness=args.freshness,
            date_range=args.date_range
        )
        print(f"\n빌드 완료: {graph.summary()}")

    elif args.command == "build-upstream":
        graph = build_layer3_from_upstream(
            max_queries=args.max_queries,
            results_per_query=args.results_per_query,
            freshness=args.freshness,
            skip_vectors=args.skip_vectors,
            date_range=args.date_range
        )
        print(f"\nUpstream 빌드 완료: {graph.summary()}")

    elif args.command == "load":
        layer3_dir = Path(__file__).parent
        input_path = layer3_dir / args.input

        if not input_path.exists():
            print(f"파일 없음: {input_path}")
            return

        graph = load_and_process(input_path)
        load_layer3_to_neo4j(graph, clear_existing=not args.no_clear)

    elif args.command == "full":
        # Build
        graph = build_layer3(
            max_queries=args.max_queries,
            results_per_query=args.results_per_query,
            skip_vectors=args.skip_vectors,
            freshness=args.freshness,
            date_range=args.date_range
        )

        # Load
        load_layer3_to_neo4j(graph, clear_existing=True)

    elif args.command == "full-upstream":
        # Upstream Build
        graph = build_layer3_from_upstream(
            max_queries=args.max_queries,
            results_per_query=args.results_per_query,
            skip_vectors=args.skip_vectors
        )

        # Load
        load_layer3_to_neo4j(graph, clear_existing=True)

    elif args.command == "build-driver":
        # Driver 기반 Build
        graph = build_layer3_from_driver(
            queries_per_driver=args.queries_per_driver,
            results_per_query=args.results_per_query,
            freshness=args.freshness,
            skip_vectors=args.skip_vectors,
            date_range=args.date_range,
            start_date=args.start_date,
            end_date=args.end_date,
            driver_ids=args.drivers
        )
        print(f"\nDriver 기반 빌드 완료: {graph.summary()}")

    elif args.command == "full-driver":
        # Driver 기반 Build + Load
        graph = build_layer3_from_driver(
            queries_per_driver=args.queries_per_driver,
            results_per_query=args.results_per_query,
            freshness=args.freshness,
            skip_vectors=args.skip_vectors,
            date_range=args.date_range,
            start_date=args.start_date,
            end_date=args.end_date,
            driver_ids=args.drivers
        )

        # Load
        print("\n" + "=" * 50)
        print("Phase 6: Neo4j 적재")
        print("=" * 50)
        load_layer3_to_neo4j(graph, clear_existing=True)

    elif args.command == "build-event":
        # Driver 템플릿 기반 Build
        graph = build_layer3_from_event(
            results_per_query=args.results_per_query,
            freshness=args.freshness,
            skip_vectors=args.skip_vectors,
            start_date=args.start_date,
            end_date=args.end_date,
            driver_ids=args.drivers,
            fetch_content=args.fetch_content  # v4: 기사 본문 fetch
        )
        print(f"\nDriver 템플릿 기반 빌드 완료: {graph.summary()}")

    elif args.command == "full-event":
        # Driver 템플릿 기반 Build + Load
        graph = build_layer3_from_event(
            results_per_query=args.results_per_query,
            freshness=args.freshness,
            skip_vectors=args.skip_vectors,
            start_date=args.start_date,
            end_date=args.end_date,
            driver_ids=args.drivers,
            fetch_content=args.fetch_content  # v4: 기사 본문 fetch
        )

        # Load
        print("\n" + "=" * 50)
        print("Phase 6: Neo4j 적재")
        print("=" * 50)
        load_layer3_to_neo4j(graph, clear_existing=True)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
