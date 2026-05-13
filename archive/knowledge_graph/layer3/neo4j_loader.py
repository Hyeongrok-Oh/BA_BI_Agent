"""Neo4j 로더 - Event 노드와 관계 적재

v3 개선사항:
- Event → Driver 관계 (V3 스키마)
- 관계에 polarity/weight 속성 추가
- Driver 노드와 직접 연결 (한글 ID 사용)
"""

import os
from typing import List, Optional
from neo4j import GraphDatabase

from .models import EventNode, EventChunk, Layer3Graph
from .config import Layer3Config


class Layer3Neo4jLoader:
    """Layer 3 Neo4j 로더"""

    def __init__(self, config: Optional[Layer3Config] = None):
        self.config = config or Layer3Config()
        self.driver = GraphDatabase.driver(
            self.config.neo4j_uri,
            auth=(self.config.neo4j_user, self.config.neo4j_password)
        )

    def close(self):
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def setup_constraints(self):
        """Constraint 및 Index 설정"""
        queries = [
            "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE",
            "CREATE INDEX event_category IF NOT EXISTS FOR (e:Event) ON (e.category)",
            "CREATE INDEX event_date IF NOT EXISTS FOR (e:Event) ON (e.start_date)",
            "CREATE INDEX event_ongoing IF NOT EXISTS FOR (e:Event) ON (e.is_ongoing)",
        ]

        with self.driver.session(database=self.config.neo4j_database) as session:
            for query in queries:
                try:
                    session.run(query)
                except Exception as e:
                    print(f"  Constraint 설정 오류: {e}")

    def clear_layer3_data(self):
        """기존 Layer 3 데이터 삭제 (v3: Event→Driver AFFECTS 관계)"""
        queries = [
            # v3: Event→Driver AFFECTS 관계 삭제
            "MATCH (:Event)-[r:AFFECTS]->(:Driver) DELETE r",
            # 하위 호환: 기존 Factor 관계도 삭제
            "MATCH (:Event)-[r:AFFECTS]->(:Factor) DELETE r",
            "MATCH (:Event)-[r:TARGETS]->(:Dimension) DELETE r",
            "MATCH (e:Event) DETACH DELETE e",
        ]

        with self.driver.session(database=self.config.neo4j_database) as session:
            for query in queries:
                result = session.run(query)
                summary = result.consume()
                deleted = summary.counters.relationships_deleted + summary.counters.nodes_deleted
                if deleted > 0:
                    print(f"  삭제: {deleted}개")

    def load_events(self, events: List[EventNode]) -> int:
        """Event 노드 적재 (v5: source_confidence 추가)"""
        query = """
        UNWIND $events AS event
        MERGE (e:Event {id: event.id})
        SET e.name = event.name,
            e.name_en = event.name_en,
            e.category = event.category,
            e.start_date = CASE WHEN event.start_date IS NOT NULL
                           THEN date(event.start_date) ELSE null END,
            e.end_date = CASE WHEN event.end_date IS NOT NULL
                         THEN date(event.end_date) ELSE null END,
            e.is_ongoing = event.is_ongoing,
            e.severity = event.severity,
            e.region_scope = event.region_scope,
            e.aliases = event.aliases,
            e.evidence = event.evidence,
            e.source_count = event.source_count,
            // v2: 모든 출처 저장 (제한 없음)
            e.source_urls = event.source_urls,
            e.source_titles = event.source_titles,
            e.sources = event.sources,
            // v3: 원본 Driver ID
            e.source_driver = event.source_driver,
            // v4: 검색 쿼리 저장
            e.search_queries = event.search_queries,
            // v5: 정보 출처 신뢰도 (5단계: 1.0/0.8/0.6/0.4/0.2)
            e.source_confidence = event.source_confidence,
            e.source_confidence_reasoning = event.source_confidence_reasoning
        RETURN count(e) as count
        """

        event_data = []
        for e in events:
            # v4: sources가 dict 또는 EventSource 객체일 수 있음
            source_urls = []
            source_titles = []
            sources_detail = []
            search_queries_set = set()

            for s in e.sources:
                # dict인지 객체인지 확인
                if isinstance(s, dict):
                    url = s.get("url", "")
                    title = s.get("title", "")
                    snippet = s.get("snippet", "")
                    source_name = s.get("source_name", "")
                    search_query = s.get("search_query", "")
                    published_date = s.get("published_date")
                else:
                    url = s.url
                    title = s.title
                    snippet = s.snippet
                    source_name = s.source_name
                    search_query = s.search_query
                    published_date = s.published_date.isoformat() if s.published_date else None

                if url:
                    source_urls.append(url)
                if title:
                    source_titles.append(title)
                if search_query:
                    search_queries_set.add(search_query)

                sources_detail.append({
                    "url": url,
                    "title": title,
                    "snippet": snippet[:200] if snippet else "",
                    "published_date": published_date,
                    "source_name": source_name,
                    "search_query": search_query,
                })

            # sources_detail을 JSON 문자열로 직렬화 (Neo4j는 Map 저장 불가)
            import json as json_module
            sources_json = json_module.dumps(sources_detail, ensure_ascii=False)

            # v4: 검색 쿼리 추출 (중복 제거)
            search_queries = list(search_queries_set)

            event_data.append({
                "id": e.id,
                "name": e.name,
                "name_en": e.name_en,
                "category": e.category.value,
                "start_date": e.start_date.isoformat() if e.start_date else None,
                "end_date": e.end_date.isoformat() if e.end_date else None,
                "is_ongoing": e.is_ongoing,
                "severity": e.severity.value,
                "region_scope": e.region_scope,
                "aliases": e.aliases,
                "evidence": e.evidence[:500] if e.evidence else "",
                "source_count": e.source_count,
                "source_urls": source_urls,
                "source_titles": source_titles,
                "sources": sources_json,  # JSON 문자열로 저장
                "source_driver": e.source_driver,  # v3: 원본 Driver ID
                "search_queries": search_queries,  # v4: 검색 쿼리
                # v5: 정보 출처 신뢰도
                "source_confidence": getattr(e, 'source_confidence', 0.8),
                "source_confidence_reasoning": getattr(e, 'source_confidence_reasoning', ""),
            })

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, events=event_data)
            return result.single()["count"]

    def load_event_driver_relations(self, events: List[EventNode]) -> dict:
        """Event → Driver 관계 적재 (v5: confidence_reasoning 추가)"""
        # v5: Event→Driver AFFECTS 관계 + confidence_reasoning
        affects_query = """
        UNWIND $relations AS rel
        MATCH (e:Event {id: rel.event_id})
        MATCH (d:Driver {id: rel.driver_id})
        MERGE (e)-[r:AFFECTS]->(d)
        SET r.polarity = rel.polarity,
            r.weight = rel.weight,
            r.magnitude = rel.magnitude,
            r.confidence = rel.confidence,
            r.confidence_reasoning = rel.confidence_reasoning,
            r.evidence = rel.evidence,
            r.impact_type = rel.impact_type,
            r.impact_score = rel.impact_score
        RETURN count(r) as count
        """

        relations = []
        positive_count = 0
        negative_count = 0
        unmatched_drivers = set()

        for event in events:
            for rel in event.factor_relations:  # factor_relations 필드는 유지 (models.py 호환)
                rel_data = {
                    "event_id": event.id,
                    "driver_id": rel.factor_id,  # V3: factor_id가 한글 Driver ID
                    "polarity": rel.polarity,
                    "weight": rel.weight,
                    "magnitude": rel.magnitude,
                    "confidence": rel.confidence,
                    # v5: 신뢰도 판단 근거
                    "confidence_reasoning": getattr(rel, 'confidence_reasoning', ""),
                    "evidence": rel.evidence[:200] if rel.evidence else "",
                    "impact_type": rel.impact_type.value,
                    "impact_score": rel.impact_score  # v3: Impact Score
                }
                relations.append(rel_data)

                if rel.polarity > 0:
                    positive_count += 1
                else:
                    negative_count += 1

        counts = {"AFFECTS": 0, "positive": positive_count, "negative": negative_count, "total_attempted": len(relations)}

        with self.driver.session(database=self.config.neo4j_database) as session:
            if relations:
                result = session.run(affects_query, relations=relations)
                counts["AFFECTS"] = result.single()["count"]

        return counts

    def load_dimensions(self) -> dict:
        """Dimension 노드 적재 (dimension_definitions.json 기반)

        v4: Region, ProductCategory, TimePeriod 노드 생성
        """
        import json
        from pathlib import Path

        # dimension_definitions.json 로드
        schema_dir = Path(__file__).parent.parent / "schema"
        dim_path = schema_dir / "dimension_definitions.json"

        with open(dim_path, "r", encoding="utf-8") as f:
            dim_data = json.load(f)

        counts = {"Region": 0, "ProductCategory": 0, "TimePeriod": 0}

        with self.driver.session(database=self.config.neo4j_database) as session:
            # Region 노드
            for node in dim_data["dimensions"]["region"]["nodes"]:
                session.run("""
                    MERGE (d:Dimension:Region {id: $id})
                    SET d.name = $name, d.name_en = $name_en
                """, id=node["id"], name=node["name"], name_en=node.get("name_en", ""))
                counts["Region"] += 1

            # ProductCategory 노드
            for node in dim_data["dimensions"]["product_category"]["nodes"]:
                session.run("""
                    MERGE (d:Dimension:ProductCategory {id: $id})
                    SET d.name = $name
                """, id=node["id"], name=node["name"])
                counts["ProductCategory"] += 1

            # TimePeriod 노드
            for node in dim_data["dimensions"]["time_period"]["nodes"]:
                session.run("""
                    MERGE (d:Dimension:TimePeriod {id: $id})
                    SET d.year = $year,
                        d.quarter = $quarter,
                        d.half = $half
                """, id=node["id"],
                    year=node.get("year"),
                    quarter=node.get("quarter"),
                    half=node.get("half"))
                counts["TimePeriod"] += 1

        return counts

    def load_event_dimension_relations(self, events: List[EventNode]) -> int:
        """Event → Dimension 관계 적재 (v4: dimension_id 기반)"""
        query = """
        UNWIND $relations AS rel
        MATCH (e:Event {id: rel.event_id})
        MATCH (d:Dimension {id: rel.dimension_id})
        MERGE (e)-[r:TARGETS]->(d)
        SET r.specificity = rel.specificity,
            r.dimension_type = rel.dimension_type
        RETURN count(r) as count
        """

        relations = []
        for event in events:
            for rel in event.dimension_relations:
                if rel.dimension_id:  # dimension_id가 있는 경우만
                    relations.append({
                        "event_id": event.id,
                        "dimension_id": rel.dimension_id,
                        "dimension_type": rel.dimension_type,
                        "specificity": rel.specificity
                    })

        if not relations:
            return 0

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, relations=relations)
            return result.single()["count"]

    def load_embeddings(self, chunks: List[EventChunk]) -> int:
        """Vector Embedding을 Event 노드에 저장"""
        # 청크별 임베딩을 Event에 저장 (첫 번째 청크만)
        query = """
        UNWIND $embeddings AS emb
        MATCH (e:Event {id: emb.event_id})
        SET e.embedding = emb.embedding
        RETURN count(e) as count
        """

        # Event별 첫 번째 청크만 선택
        event_embeddings = {}
        for chunk in chunks:
            if chunk.embedding and chunk.event_id not in event_embeddings:
                event_embeddings[chunk.event_id] = chunk.embedding

        if not event_embeddings:
            return 0

        embeddings_data = [
            {"event_id": eid, "embedding": emb}
            for eid, emb in event_embeddings.items()
        ]

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, embeddings=embeddings_data)
            return result.single()["count"]

    def verify_load(self) -> dict:
        """적재 결과 검증 (v4: Dimension Layer 추가, IMPACTS 제거)"""
        queries = {
            "event_count": "MATCH (e:Event) RETURN count(e) as count",
            # v3: Event→Driver AFFECTS 관계 카운트
            "affects_count": "MATCH (:Event)-[r:AFFECTS]->(:Driver) RETURN count(r) as count",
            "positive_count": "MATCH (:Event)-[r:AFFECTS]->(:Driver) WHERE r.polarity > 0 RETURN count(r) as count",
            "negative_count": "MATCH (:Event)-[r:AFFECTS]->(:Driver) WHERE r.polarity < 0 RETURN count(r) as count",
            # v4: Dimension Layer
            "dimension_count": "MATCH (d:Dimension) RETURN count(d) as count",
            "region_count": "MATCH (d:Region) RETURN count(d) as count",
            "product_count": "MATCH (d:ProductCategory) RETURN count(d) as count",
            "time_count": "MATCH (d:TimePeriod) RETURN count(d) as count",
            "targets_count": "MATCH (:Event)-[r:TARGETS]->(:Dimension) RETURN count(r) as count",
            "top_events": """
                MATCH (e:Event)
                OPTIONAL MATCH (e)-[r:AFFECTS]->(d:Driver)
                RETURN e.name as name, e.category as category,
                       e.severity as severity, count(r) as driver_count,
                       collect(DISTINCT {driver: d.id, polarity: r.polarity})[0..3] as top_drivers
                ORDER BY driver_count DESC
                LIMIT 10
            """,
        }

        results = {}
        with self.driver.session(database=self.config.neo4j_database) as session:
            for key, query in queries.items():
                result = session.run(query)
                if key.endswith("_count"):
                    record = result.single()
                    results[key] = record["count"] if record else 0
                else:
                    results[key] = [dict(record) for record in result]

        return results


def load_layer3_to_neo4j(
    graph: Layer3Graph,
    clear_existing: bool = True,
    verbose: bool = True
) -> dict:
    """Layer 3 그래프를 Neo4j에 적재"""
    with Layer3Neo4jLoader() as loader:
        if verbose:
            print("=== Layer 3 Neo4j 적재 ===\n")

        # Constraint 설정
        if verbose:
            print("1. Constraint 설정...")
        loader.setup_constraints()

        # 기존 데이터 삭제
        if clear_existing:
            if verbose:
                print("\n2. 기존 데이터 삭제...")
            loader.clear_layer3_data()

        # Event 노드 적재
        if verbose:
            print(f"\n3. Event 노드 적재 ({len(graph.events)}개)...")
        event_count = loader.load_events(graph.events)
        if verbose:
            print(f"  적재: {event_count}개")

        # Event → Driver 관계 적재 (v3: AFFECTS + polarity)
        if verbose:
            print("\n4. Event → Driver 관계 적재 (v3: polarity/weight)...")
        driver_counts = loader.load_event_driver_relations(graph.events)
        if verbose:
            print(f"  시도: {driver_counts['total_attempted']}개")
            print(f"  AFFECTS 관계: {driver_counts['AFFECTS']}개")
            print(f"    - polarity +1 (증가): {driver_counts['positive']}개")
            print(f"    - polarity -1 (감소): {driver_counts['negative']}개")

        # v4: Dimension 노드 적재
        if verbose:
            print("\n5. Dimension 노드 적재...")
        dim_counts = loader.load_dimensions()
        if verbose:
            print(f"  Region: {dim_counts['Region']}개")
            print(f"  ProductCategory: {dim_counts['ProductCategory']}개")
            print(f"  TimePeriod: {dim_counts['TimePeriod']}개")

        # Event → Dimension 관계 적재
        if verbose:
            print("\n6. Event → Dimension 관계 적재...")
        dim_rel_count = loader.load_event_dimension_relations(graph.events)
        if verbose:
            print(f"  TARGETS: {dim_rel_count}개")

        # Vector Embedding 적재
        if graph.chunks:
            if verbose:
                print(f"\n7. Vector Embedding 적재 ({len(graph.chunks)}개 청크)...")
            emb_count = loader.load_embeddings(graph.chunks)
            if verbose:
                print(f"  적재: {emb_count}개 Event에 임베딩 추가")

        # 검증
        if verbose:
            print("\n=== 적재 결과 ===")
        verification = loader.verify_load()

        if verbose:
            print(f"Event 노드: {verification['event_count']}개")
            print(f"AFFECTS 관계 (Event→Driver): {verification['affects_count']}개")
            print(f"  - polarity +1: {verification['positive_count']}개")
            print(f"  - polarity -1: {verification['negative_count']}개")
            print(f"Dimension 노드: {verification['dimension_count']}개")
            print(f"  - Region: {verification['region_count']}개")
            print(f"  - ProductCategory: {verification['product_count']}개")
            print(f"  - TimePeriod: {verification['time_count']}개")
            print(f"TARGETS 관계 (Event→Dimension): {verification['targets_count']}개")

            print("\n--- 상위 Event (V4: Driver/Dimension 연결) ---")
            for e in verification.get("top_events", []):
                drivers_str = ""
                if e.get('top_drivers'):
                    drivers_str = ", ".join([
                        f"{d['driver']}({'+' if d['polarity'] and d['polarity'] > 0 else ''}{d['polarity'] or '?'})"
                        for d in e['top_drivers'] if d.get('driver')
                    ])
                print(f"  {e['name']} [{e['category']}] - {drivers_str}")

        return verification
