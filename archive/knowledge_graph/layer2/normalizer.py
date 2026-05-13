"""Factor 정규화 모듈"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict
from dataclasses import dataclass, field

from .models import FactorCategory, RelationType


@dataclass
class NormalizedFactor:
    """정규화된 Factor"""
    id: str
    name: str
    category: str
    original_names: List[str] = field(default_factory=list)
    mention_count: int = 0
    sources: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "original_names": self.original_names,
            "mention_count": self.mention_count,
            "sources": list(set(self.sources)),
        }


@dataclass
class NormalizedRelation:
    """정규화된 관계 (v2: 모든 출처 저장)"""
    factor_id: str
    anchor_id: str
    relation_type: str
    mention_count: int = 0
    polarity: int = 0           # v2: polarity 추가
    sources: List[dict] = field(default_factory=list)  # v2: 모든 출처 저장

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "anchor_id": self.anchor_id,
            "relation_type": self.relation_type,
            "mention_count": self.mention_count,
            "source_count": self.source_count,
            "polarity": self.polarity,
            "sources": self.sources,  # 모든 출처 포함
        }


class FactorNormalizer:
    """Factor 정규화"""

    def __init__(self, normalization_path: Path):
        self.mapping = self._load_normalization(normalization_path)
        self.reverse_mapping = self._build_reverse_mapping()
        self.exclude_list = self.mapping.get("exclude", [])

    def _load_normalization(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_reverse_mapping(self) -> Dict[str, Tuple[str, str]]:
        """variant → (canonical_name, category) 역매핑 생성"""
        reverse = {}
        for group_name, group_data in self.mapping.items():
            if group_name == "exclude":
                continue
            canonical = group_data.get("canonical", group_name)
            category = group_data.get("category", "macro_economy")
            for variant in group_data.get("variants", []):
                reverse[variant.lower()] = (canonical, category)
        return reverse

    def normalize_factor_name(self, name: str) -> Tuple[str, str, bool]:
        """
        Factor 이름 정규화
        Returns: (정규화된_이름, 카테고리, 제외여부)
        """
        # 제외 목록 확인
        if name in self.exclude_list:
            return name, "excluded", True

        # 정규화 매핑 확인
        name_lower = name.lower()
        if name_lower in self.reverse_mapping:
            canonical, category = self.reverse_mapping[name_lower]
            return canonical, category, False

        # 매핑에 없으면 원본 유지
        return name, "macro_economy", False

    def normalize_results(self, input_path: Path, output_path: Path) -> dict:
        """결과 파일 정규화"""
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Factor 정규화
        normalized_factors: Dict[str, NormalizedFactor] = {}
        factor_id_mapping: Dict[str, str] = {}  # old_id → new_id
        excluded_factors: List[str] = []

        for factor in data.get("factors", []):
            old_name = factor["name"]
            old_id = factor["id"]

            canonical_name, category, is_excluded = self.normalize_factor_name(old_name)

            if is_excluded:
                excluded_factors.append(old_name)
                continue

            new_id = self._name_to_id(canonical_name)
            factor_id_mapping[old_id] = new_id

            if new_id not in normalized_factors:
                normalized_factors[new_id] = NormalizedFactor(
                    id=new_id,
                    name=canonical_name,
                    category=category,
                )

            nf = normalized_factors[new_id]
            if old_name not in nf.original_names:
                nf.original_names.append(old_name)
            nf.mention_count += factor.get("mention_count", 1)
            nf.sources.extend(factor.get("sources", []))

        # 관계 정규화 및 집계 (v2: polarity + 모든 출처 수집)
        relation_map: Dict[Tuple[str, str, int], NormalizedRelation] = {}
        skipped_relations = 0

        for rel in data.get("relations", []):
            old_factor_id = rel["factor_id"]

            # 제외된 Factor의 관계는 스킵
            if old_factor_id not in factor_id_mapping:
                skipped_relations += 1
                continue

            new_factor_id = factor_id_mapping[old_factor_id]
            anchor_id = rel["anchor_id"]
            relation_type = rel["relation_type"]
            polarity = rel.get("polarity", 0)

            # v2: polarity 기준으로 그룹화
            key = (new_factor_id, anchor_id, polarity)

            if key not in relation_map:
                relation_map[key] = NormalizedRelation(
                    factor_id=new_factor_id,
                    anchor_id=anchor_id,
                    relation_type=relation_type,
                    polarity=polarity,
                )

            relation_map[key].mention_count += rel.get("mention_count", 1)

            # v2: 모든 출처 수집
            rel_sources = rel.get("sources", [])
            if rel_sources:
                relation_map[key].sources.extend(rel_sources)
            else:
                # sources가 없으면 source_count만 있는 경우 - 기존 호환
                pass

        # 결과 생성
        result = {
            "summary": {
                "original_factors": len(data.get("factors", [])),
                "normalized_factors": len(normalized_factors),
                "excluded_factors": len(excluded_factors),
                "original_relations": len(data.get("relations", [])),
                "normalized_relations": len(relation_map),
                "skipped_relations": skipped_relations,
            },
            "factors": [f.to_dict() for f in sorted(
                normalized_factors.values(),
                key=lambda x: x.mention_count,
                reverse=True
            )],
            "relations": [r.to_dict() for r in sorted(
                relation_map.values(),
                key=lambda x: x.mention_count,
                reverse=True
            )],
            "excluded": excluded_factors,
        }

        # 저장
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return result

    def _name_to_id(self, name: str) -> str:
        """이름을 ID로 변환"""
        return name.lower().replace(" ", "_").replace("/", "_")


def normalize_layer2(
    input_file: str = "layer2_result.json",
    output_file: str = "layer2_normalized.json",
    normalization_file: str = "factor_normalization.yaml"
):
    """Layer 2 결과 정규화 실행"""
    layer2_dir = Path(__file__).parent

    input_path = layer2_dir / input_file
    output_path = layer2_dir / output_file
    normalization_path = layer2_dir / normalization_file

    normalizer = FactorNormalizer(normalization_path)
    result = normalizer.normalize_results(input_path, output_path)

    print("=== 정규화 완료 ===")
    print(f"원본 Factor: {result['summary']['original_factors']}개")
    print(f"정규화 Factor: {result['summary']['normalized_factors']}개")
    print(f"제외된 Factor: {result['summary']['excluded_factors']}개")
    print(f"원본 관계: {result['summary']['original_relations']}개")
    print(f"정규화 관계: {result['summary']['normalized_relations']}개")
    print(f"\n결과 저장: {output_path}")

    print("\n=== 상위 Factor (언급 횟수) ===")
    for factor in result["factors"][:15]:
        originals = factor.get("original_names", [])
        if len(originals) > 1:
            print(f"  {factor['name']}: {factor['mention_count']}회 (통합: {len(originals)}개)")
        else:
            print(f"  {factor['name']}: {factor['mention_count']}회")

    return result


if __name__ == "__main__":
    normalize_layer2()
