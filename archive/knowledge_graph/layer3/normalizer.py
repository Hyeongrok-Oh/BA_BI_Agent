"""Event 정규화 - 중복 제거 및 표준화"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

from .models import EventNode, Layer3Graph


class EventNormalizer:
    """Event 정규화 및 중복 제거"""

    def __init__(self, normalization_path: Optional[Path] = None):
        self.normalization_path = normalization_path or Path(__file__).parent / "event_normalization.yaml"
        self.mapping, self.exclude_list = self._load_mapping()
        self.seen_events: Dict[str, EventNode] = {}

    def _load_mapping(self) -> Tuple[Dict[str, dict], List[str]]:
        """정규화 매핑 로드"""
        if not self.normalization_path.exists():
            return {}, []

        with open(self.normalization_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # 역매핑 생성 (alias → canonical info)
        mapping = {}
        for key, info in data.items():
            if key in ["version", "exclude"]:
                continue
            canonical = info.get("canonical", key)
            for alias in info.get("aliases", []):
                mapping[alias.lower()] = {
                    "canonical": canonical,
                    "canonical_en": info.get("canonical_en"),
                    "category": info.get("category")
                }
            # canonical 자체도 매핑
            mapping[canonical.lower()] = {
                "canonical": canonical,
                "canonical_en": info.get("canonical_en"),
                "category": info.get("category")
            }

        exclude_list = [e.lower() for e in data.get("exclude", [])]
        return mapping, exclude_list

    def normalize_event(self, event: EventNode) -> Optional[EventNode]:
        """Event 정규화"""
        name_lower = event.name.lower()

        # 제외 목록 체크
        for exclude in self.exclude_list:
            if exclude in name_lower:
                return None

        # 매핑에서 canonical 찾기
        if name_lower in self.mapping:
            info = self.mapping[name_lower]
            event.name = info["canonical"]
            if info.get("canonical_en"):
                event.name_en = info["canonical_en"]
            # ID 재생성
            event.id = self._generate_id(event.name)

        return event

    def deduplicate(self, events: List[EventNode]) -> List[EventNode]:
        """중복 Event 제거"""
        self.seen_events = {}
        unique_events = []

        for event in events:
            # 정규화
            normalized = self.normalize_event(event)
            if not normalized:
                continue

            # 기존 이벤트와 비교
            existing = self._find_similar_event(normalized)
            if existing:
                # 병합: 소스 추가
                existing.sources.extend(normalized.sources)
                # Factor 관계 병합
                existing_factors = {r.factor_id for r in existing.factor_relations}
                for r in normalized.factor_relations:
                    if r.factor_id not in existing_factors:
                        existing.factor_relations.append(r)
            else:
                self.seen_events[normalized.id] = normalized
                unique_events.append(normalized)

        return unique_events

    def _find_similar_event(self, event: EventNode) -> Optional[EventNode]:
        """유사한 기존 Event 찾기"""
        # 1. ID로 찾기
        if event.id in self.seen_events:
            return self.seen_events[event.id]

        # 2. 이름 유사도로 찾기
        for existing in self.seen_events.values():
            if self._is_similar(event.name, existing.name):
                return existing
            # 영문 이름 비교
            if event.name_en and existing.name_en:
                if self._is_similar(event.name_en, existing.name_en):
                    return existing

        return None

    def _is_similar(self, name1: str, name2: str, threshold: float = 0.8) -> bool:
        """이름 유사도 비교"""
        # 정규화
        n1 = name1.lower().replace(" ", "")
        n2 = name2.lower().replace(" ", "")

        # 완전 일치
        if n1 == n2:
            return True

        # 부분 포함
        if n1 in n2 or n2 in n1:
            return True

        # 시퀀스 유사도
        ratio = SequenceMatcher(None, n1, n2).ratio()
        return ratio >= threshold

    def _generate_id(self, name: str) -> str:
        """Event ID 생성"""
        import re
        clean_name = re.sub(r'[^\w\s]', '', name.lower())
        clean_name = clean_name.replace(" ", "_")[:30]
        return f"event_{clean_name}"


def normalize_layer3(graph: Layer3Graph) -> Layer3Graph:
    """Layer 3 그래프 정규화"""
    normalizer = EventNormalizer()

    print(f"정규화 전: {len(graph.events)}개 Event")

    # 정규화 및 중복 제거
    unique_events = normalizer.deduplicate(graph.events)

    # 새 그래프 생성
    normalized_graph = Layer3Graph()
    normalized_graph.events = unique_events

    print(f"정규화 후: {len(normalized_graph.events)}개 Event")

    return normalized_graph
