"""Factor-Factor 관계 정규화 및 Neo4j 적재"""

import json
import yaml
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from neo4j import GraphDatabase

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from knowledge_graph.config import BaseConfig


def load_normalization_mapping(normalization_path: Path) -> Tuple[Dict[str, str], List[str]]:
    """정규화 매핑 로드"""
    with open(normalization_path, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f)

    # 역매핑 생성
    reverse_mapping = {}
    for group_name, group_data in mapping.items():
        if group_name == "exclude":
            continue
        canonical = group_data.get("canonical", group_name)
        for variant in group_data.get("variants", []):
            reverse_mapping[variant.lower()] = canonical

    exclude_list = [e.lower() for e in mapping.get("exclude", [])]

    return reverse_mapping, exclude_list


def normalize_factor_name(name: str, reverse_mapping: Dict[str, str], exclude_list: List[str]) -> Optional[str]:
    """Factor 이름 정규화"""
    name_lower = name.lower()
    if name_lower in exclude_list:
        return None
    return reverse_mapping.get(name_lower, name)


def renormalize_factor_relations(
    input_path: Path,
    normalization_path: Path
) -> List[dict]:
    """Factor-Factor 관계 재정규화"""
    # 입력 로드
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 정규화 매핑 로드
    reverse_mapping, exclude_list = load_normalization_mapping(normalization_path)

    # 재정규화
    relation_map = {}

    for rel in data.get("relations", []):
        source = normalize_factor_name(rel["source_factor"], reverse_mapping, exclude_list)
        target = normalize_factor_name(rel["target_factor"], reverse_mapping, exclude_list)

        if not source or not target:
            continue
        if source == target:
            continue

        key = (source, target, rel["relation_type"])
        if key not in relation_map:
            relation_map[key] = {
                "source_factor": source,
                "target_factor": target,
                "relation_type": rel["relation_type"],
                "mention_count": 0,
                "sources": []
            }

        relation_map[key]["mention_count"] += rel.get("mention_count", 1)
        relation_map[key]["sources"].extend(rel.get("sources", []))

    # 중복 source 제거 및 정렬 (dict 형태 sources 지원)
    normalized = []
    for rel in relation_map.values():
        unique_sources = []
        seen_keys = set()
        for src in rel["sources"]:
            if isinstance(src, dict):
                # dict 형태: doc_name + page_num 기준으로 중복 제거
                key = (src.get("doc_name", ""), src.get("page_num", 0))
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_sources.append(src)
            else:
                # 하위 호환: 문자열 형태
                if src not in seen_keys:
                    seen_keys.add(src)
                    unique_sources.append(src)
        rel["sources"] = unique_sources
        normalized.append(rel)

    return sorted(normalized, key=lambda x: x["mention_count"], reverse=True)


class FactorRelationNeo4jLoader:
    """Factor-Factor 관계 Neo4j 로더"""

    def __init__(self, config: Optional[BaseConfig] = None):
        self.config = config or BaseConfig()
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

    def clear_factor_relations(self):
        """기존 Factor-Factor 관계 삭제"""
        query = "MATCH (:Factor)-[r:INFLUENCES]->(:Factor) DELETE r"

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query)
            summary = result.consume()
            print(f"  삭제된 관계: {summary.counters.relationships_deleted}개")

    def ensure_factors_exist(self, relations: List[dict]) -> int:
        """관계에 등장하는 Factor 노드 확인/생성"""
        # 모든 Factor 이름 수집
        factors = set()
        for rel in relations:
            factors.add(rel["source_factor"])
            factors.add(rel["target_factor"])

        # 기존에 없는 Factor만 생성
        query = """
        UNWIND $factors AS factor_name
        MERGE (f:Factor {id: toLower(replace(factor_name, ' ', '_'))})
        ON CREATE SET f.name = factor_name,
                      f.category = 'extracted',
                      f.mention_count = 0
        RETURN count(f) as count
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, factors=list(factors))
            record = result.single()
            return record["count"] if record else 0

    def load_relations(self, relations: List[dict]) -> int:
        """Factor-Factor 관계 생성 (sources 상세 정보 포함)"""
        # sources를 JSON 문자열로 변환
        for rel in relations:
            sources = rel.get("sources", [])
            if sources and isinstance(sources[0], dict):
                rel["sources_json"] = json.dumps(sources, ensure_ascii=False)
            else:
                rel["sources_json"] = json.dumps(sources)

        query = """
        UNWIND $relations AS rel
        MATCH (source:Factor {id: toLower(replace(rel.source_factor, ' ', '_'))})
        MATCH (target:Factor {id: toLower(replace(rel.target_factor, ' ', '_'))})
        MERGE (source)-[r:INFLUENCES {type: rel.relation_type}]->(target)
        SET r.mention_count = rel.mention_count,
            r.source_count = size(rel.sources),
            r.sources = rel.sources_json
        RETURN count(r) as count
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, relations=relations)
            record = result.single()
            return record["count"] if record else 0

    def load_normalized_relations(self, relations: List[dict]) -> int:
        """정규화된 AFFECTS 관계 생성 (polarity 포함)"""
        # sources를 JSON 문자열로 변환
        for rel in relations:
            sources = rel.get("sources", [])
            if sources and isinstance(sources[0], dict):
                rel["sources_json"] = json.dumps(sources[:10], ensure_ascii=False)  # 최대 10개
            else:
                rel["sources_json"] = json.dumps(sources[:10])

            # original_types도 JSON으로
            original_types = rel.get("original_types", [])
            rel["original_types_json"] = json.dumps(original_types, ensure_ascii=False)

        query = """
        UNWIND $relations AS rel
        MATCH (source:Factor {id: toLower(replace(rel.source_factor, ' ', '_'))})
        MATCH (target:Factor {id: toLower(replace(rel.target_factor, ' ', '_'))})
        MERGE (source)-[r:INFLUENCES]->(target)
        SET r.type = rel.relation_type,
            r.polarity = rel.polarity,
            r.mention_count = rel.mention_count,
            r.source_count = size(rel.sources),
            r.sources = rel.sources_json,
            r.original_types = rel.original_types_json
        RETURN count(r) as count
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, relations=relations)
            record = result.single()
            return record["count"] if record else 0

    def verify_load(self) -> dict:
        """적재 결과 검증"""
        queries = {
            "relation_count": "MATCH (:Factor)-[r:INFLUENCES]->(:Factor) RETURN count(r) as count",
            "top_relations": """
                MATCH (s:Factor)-[r:INFLUENCES]->(t:Factor)
                RETURN s.name as source, r.type as type, t.name as target, r.mention_count as mentions
                ORDER BY r.mention_count DESC
                LIMIT 10
            """,
            "relation_types": """
                MATCH (:Factor)-[r:INFLUENCES]->(:Factor)
                RETURN r.type as type, count(r) as count
                ORDER BY count DESC
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


def load_factor_relations_to_neo4j(
    input_file: str = "factor_relations.json",
    output_file: str = "factor_relations_normalized.json"
):
    """Factor-Factor 관계 재정규화 및 Neo4j 적재"""
    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file
    normalization_path = layer2_dir / "factor_normalization.yaml"
    output_path = layer2_dir / output_file

    print("=== Factor-Factor 관계 정규화 및 Neo4j 적재 ===")

    # 재정규화
    print("\n1. 관계 재정규화...")
    normalized = renormalize_factor_relations(input_path, normalization_path)
    print(f"  정규화된 관계: {len(normalized)}개")

    # 결과 저장
    result = {
        "summary": {"normalized_relations": len(normalized)},
        "relations": normalized
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  저장: {output_path}")

    # Neo4j 적재
    print("\n2. Neo4j 적재...")
    with FactorRelationNeo4jLoader() as loader:
        # 기존 관계 삭제
        print("  기존 Factor-Factor 관계 삭제...")
        loader.clear_factor_relations()

        # Factor 노드 확인/생성
        print("  Factor 노드 확인/생성...")
        factor_count = loader.ensure_factors_exist(normalized)
        print(f"  처리된 Factor: {factor_count}개")

        # 관계 생성
        print("  INFLUENCES 관계 생성...")
        rel_count = loader.load_relations(normalized)
        print(f"  생성된 관계: {rel_count}개")

        # 검증
        print("\n3. 적재 결과 검증...")
        verification = loader.verify_load()

        print(f"\n=== 적재 완료 ===")
        print(f"INFLUENCES 관계: {verification['relation_count']}개")

        print("\n--- 관계 유형별 ---")
        for rt in verification.get("relation_types", []):
            print(f"  {rt['type']}: {rt['count']}개")

        print("\n--- 상위 관계 ---")
        for r in verification.get("top_relations", []):
            print(f"  {r['source']} --{r['type']}--> {r['target']}: {r['mentions']}회")

    return verification


def normalize_to_affects(relations: List[dict]) -> List[dict]:
    """Factor-Factor 관계를 AFFECTS로 통합 정규화

    - CAUSES/AMPLIFIES → polarity +1
    - MITIGATES → polarity -1
    - 같은 (source, target) 쌍을 하나로 통합
    - polarity는 mention_count 가중 평균
    """
    # relation_type → polarity 변환
    POLARITY_MAP = {
        "CAUSES": 1.0,
        "AMPLIFIES": 1.0,
        "MITIGATES": -1.0,
    }

    # (source, target) 쌍별로 그룹화
    pair_map: Dict[Tuple[str, str], dict] = {}

    for rel in relations:
        source = rel["source_factor"]
        target = rel["target_factor"]
        key = (source, target)

        rel_type = rel.get("relation_type", "CAUSES")
        polarity = POLARITY_MAP.get(rel_type, 1.0)
        mention_count = rel.get("mention_count", 1)

        if key not in pair_map:
            pair_map[key] = {
                "source_factor": source,
                "target_factor": target,
                "relation_type": "AFFECTS",
                "polarity_sum": 0.0,
                "total_mentions": 0,
                "sources": [],
                "original_types": []  # 디버깅용
            }

        pair_map[key]["polarity_sum"] += polarity * mention_count
        pair_map[key]["total_mentions"] += mention_count
        pair_map[key]["sources"].extend(rel.get("sources", []))
        pair_map[key]["original_types"].append({
            "type": rel_type,
            "count": mention_count
        })

    # 최종 결과 생성
    normalized = []
    for key, data in pair_map.items():
        # polarity 가중 평균 계산
        if data["total_mentions"] > 0:
            polarity = data["polarity_sum"] / data["total_mentions"]
        else:
            polarity = 0.0

        # -1.0 ~ +1.0 범위로 클램핑
        polarity = max(-1.0, min(1.0, polarity))

        normalized.append({
            "source_factor": data["source_factor"],
            "target_factor": data["target_factor"],
            "relation_type": "AFFECTS",
            "polarity": round(polarity, 2),
            "mention_count": data["total_mentions"],
            "sources": data["sources"],
            "original_types": data["original_types"]
        })

    return sorted(normalized, key=lambda x: x["mention_count"], reverse=True)


def load_closed_set_relations_to_neo4j(
    input_file: str = "factor_relations_closed.json"
):
    """Closed-Set Factor-Factor 관계 Neo4j 적재 (정규화 불필요)"""
    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file

    print("=== Closed-Set Factor-Factor 관계 Neo4j 적재 ===")

    # 입력 로드
    print("\n1. 관계 로드...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    relations = data.get("relations", [])
    print(f"  로드된 관계: {len(relations)}개")
    print(f"  Factor 수: {data['summary'].get('factor_count', 0)}개")

    # Neo4j 적재
    print("\n2. Neo4j 적재...")
    with FactorRelationNeo4jLoader() as loader:
        # 기존 관계 삭제
        print("  기존 INFLUENCES 관계 삭제...")
        loader.clear_factor_relations()

        # Closed-Set은 기존 25개 Factor만 사용 - 노드 생성 스킵
        # 관계 생성
        print("  INFLUENCES 관계 생성...")
        rel_count = loader.load_relations(relations)
        print(f"  생성된 관계: {rel_count}개")

        # 검증
        print("\n3. 적재 결과 검증...")
        verification = loader.verify_load()

        print(f"\n{'=' * 50}")
        print("Closed-Set Factor-Factor 관계 적재 완료")
        print(f"{'=' * 50}")
        print(f"INFLUENCES 관계: {verification['relation_count']}개")

        print("\n--- 관계 유형별 ---")
        for rt in verification.get("relation_types", []):
            print(f"  {rt['type']}: {rt['count']}개")

        print("\n--- 상위 10개 관계 ---")
        for r in verification.get("top_relations", []):
            print(f"  {r['source']} --{r['type']}--> {r['target']}: {r['mentions']}회")

    return verification


def load_normalized_affects_to_neo4j(
    input_file: str = "factor_relations_closed.json",
    output_file: str = "factor_relations_normalized_affects.json"
):
    """Factor-Factor 관계를 AFFECTS로 정규화하여 Neo4j에 적재"""
    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file
    output_path = layer2_dir / output_file

    print("=" * 60)
    print("Factor-Factor 관계 정규화 (AFFECTS 통합)")
    print("=" * 60)

    # 입력 로드
    print("\n1. 관계 로드...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    relations = data.get("relations", [])
    print(f"  로드된 관계: {len(relations)}개")

    # 정규화
    print("\n2. AFFECTS로 정규화...")
    normalized = normalize_to_affects(relations)
    print(f"  정규화 후: {len(normalized)}개 (중복 통합)")

    # polarity 분포
    positive = sum(1 for r in normalized if r["polarity"] > 0)
    negative = sum(1 for r in normalized if r["polarity"] < 0)
    mixed = sum(1 for r in normalized if r["polarity"] == 0)
    print(f"  - polarity > 0 (정상관): {positive}개")
    print(f"  - polarity < 0 (역상관): {negative}개")
    print(f"  - polarity = 0 (혼합): {mixed}개")

    # JSON 저장
    result = {
        "summary": {
            "original_count": len(relations),
            "normalized_count": len(normalized),
            "positive_polarity": positive,
            "negative_polarity": negative,
        },
        "relations": normalized
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  저장: {output_path}")

    # Neo4j 적재
    print("\n3. Neo4j 적재...")
    with FactorRelationNeo4jLoader() as loader:
        # 기존 관계 삭제
        print("  기존 INFLUENCES 관계 삭제...")
        loader.clear_factor_relations()

        # 정규화된 관계 생성
        print("  정규화된 INFLUENCES 관계 생성...")
        rel_count = loader.load_normalized_relations(normalized)
        print(f"  생성된 관계: {rel_count}개")

        # 검증
        print("\n4. 적재 결과 검증...")
        verification = loader.verify_load()

        print(f"\n{'=' * 60}")
        print("정규화 완료")
        print(f"{'=' * 60}")
        print(f"INFLUENCES 관계: {verification['relation_count']}개")

        print("\n--- 상위 10개 관계 (polarity 포함) ---")
        # polarity 포함 쿼리
        with loader.driver.session(database=loader.config.neo4j_database) as session:
            result = session.run("""
                MATCH (s:Factor)-[r:INFLUENCES]->(t:Factor)
                RETURN s.name as source, t.name as target,
                       r.polarity as polarity, r.mention_count as mentions
                ORDER BY r.mention_count DESC
                LIMIT 10
            """)
            for record in result:
                pol = record["polarity"]
                pol_str = f"+{pol}" if pol > 0 else str(pol)
                print(f"  {record['source']} → {record['target']}: {record['mentions']}회 (polarity: {pol_str})")

    return verification


def load_upstream_relations_to_neo4j(
    input_file: str = "upstream_factor_relations_validated.json",
    clear_existing: bool = False
):
    """Upstream Factor 관계 Neo4j 적재

    Args:
        input_file: 정규화된 upstream 관계 파일
        clear_existing: 기존 INFLUENCES 관계 삭제 여부
    """
    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file

    print("=" * 60)
    print("Upstream Factor 관계 Neo4j 적재")
    print("=" * 60)

    # 입력 로드
    print("\n1. 관계 로드...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    relations = data.get("relations", [])
    new_upstream_factors = data["summary"].get("new_upstream_factors", [])
    print(f"  로드된 관계: {len(relations)}개")
    print(f"  신규 Upstream Factor: {len(new_upstream_factors)}개")

    # Neo4j 적재
    print("\n2. Neo4j 적재...")
    with FactorRelationNeo4jLoader() as loader:
        if clear_existing:
            print("  기존 INFLUENCES 관계 삭제...")
            loader.clear_factor_relations()

        # 신규 Upstream Factor 노드 생성
        print("  신규 Upstream Factor 노드 생성...")
        create_query = """
        UNWIND $factors AS factor_name
        MERGE (f:Factor {id: toLower(replace(factor_name, ' ', '_'))})
        ON CREATE SET f.name = factor_name,
                      f.category = 'upstream',
                      f.is_core = false,
                      f.mention_count = 0
        RETURN count(f) as count
        """
        with loader.driver.session(database=loader.config.neo4j_database) as session:
            result = session.run(create_query, factors=new_upstream_factors)
            record = result.single()
            created = record["count"] if record else 0
            print(f"  생성/확인된 Upstream Factor: {created}개")

        # INFLUENCES 관계 생성 (sources 포함)
        print("  INFLUENCES 관계 생성...")

        # sources를 JSON 문자열로 변환
        for rel in relations:
            sources = rel.get("sources", [])
            # 최대 10개 source만 저장 (Neo4j 속성 크기 제한)
            rel["sources_json"] = json.dumps(sources[:10], ensure_ascii=False)

        rel_query = """
        UNWIND $relations AS rel
        MATCH (source:Factor {id: rel.source_factor_id})
        MATCH (target:Factor {id: rel.target_factor_id})
        MERGE (source)-[r:INFLUENCES]->(target)
        SET r.type = rel.relation_type,
            r.polarity = rel.polarity,
            r.mention_count = rel.mention_count,
            r.is_upstream = rel.is_new_upstream,
            r.sources = rel.sources_json
        RETURN count(r) as count
        """
        with loader.driver.session(database=loader.config.neo4j_database) as session:
            result = session.run(rel_query, relations=relations)
            record = result.single()
            rel_count = record["count"] if record else 0
            print(f"  생성된 관계: {rel_count}개")

        # 검증
        print("\n3. 적재 결과 검증...")
        with loader.driver.session(database=loader.config.neo4j_database) as session:
            # Factor 노드 수
            result = session.run("MATCH (f:Factor) RETURN count(f) as count")
            factor_count = result.single()["count"]

            # 전체 INFLUENCES 관계 수
            result = session.run("MATCH ()-[r:INFLUENCES]->() RETURN count(r) as count")
            total_rel = result.single()["count"]

            # Upstream 관계 수
            result = session.run("MATCH ()-[r:INFLUENCES {is_upstream: true}]->() RETURN count(r) as count")
            upstream_rel = result.single()["count"]

            # 9개 누락 Factor 커버리지
            missing_9 = ["DRAM 가격", "인건비", "해상 운임", "프로모션", "환율", "금리", "경기", "인플레이션", "무역 정책"]
            result = session.run("""
                UNWIND $factors AS factor_name
                OPTIONAL MATCH (f:Factor {name: factor_name})<-[:INFLUENCES]-()
                RETURN factor_name, count(*) as upstream_count
            """, factors=missing_9)
            coverage = {r["factor_name"]: r["upstream_count"] for r in result}

        print(f"\n{'=' * 60}")
        print("Upstream Factor 적재 완료")
        print(f"{'=' * 60}")
        print(f"Factor 노드: {factor_count}개")
        print(f"INFLUENCES 관계: {total_rel}개 (Upstream: {upstream_rel}개)")

        print("\n--- 9개 누락 Factor 커버리지 ---")
        for factor in missing_9:
            count = coverage.get(factor, 0)
            status = "✓" if count > 0 else "✗"
            print(f"  {status} {factor}: {count}개 upstream")

    return {"factor_count": factor_count, "relation_count": total_rel, "upstream_count": upstream_rel}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["open", "closed", "normalize", "upstream"], default="normalize",
                        help="적재 모드: open(기존), closed(Closed-Set), normalize(AFFECTS 정규화), upstream(Upstream Factor)")
    args = parser.parse_args()

    if args.mode == "normalize":
        load_normalized_affects_to_neo4j()
    elif args.mode == "closed":
        load_closed_set_relations_to_neo4j()
    elif args.mode == "upstream":
        load_upstream_relations_to_neo4j()
    else:
        load_factor_relations_to_neo4j()
