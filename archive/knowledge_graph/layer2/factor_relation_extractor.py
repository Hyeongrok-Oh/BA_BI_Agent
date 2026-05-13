"""Factor-Factor 관계 추출 - LLM 기반

v5 (2024-12-31): Closed-Set 추출 추가
- 25개 핵심 Factor 내에서만 관계 추출
- Factor 검증 및 정규화 로직 강화
"""

import json
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .pdf_extractor import Paragraph, DocumentProcessor


# ============================================================
# Closed-Set Factor 관계 추출 프롬프트 (v6 - 인과관계 판단 강화)
# ============================================================
CLOSED_SET_FACTOR_RELATION_PROMPT = """다음 문단에서 Factor들 간의 **명시적 인과관계**를 추출하세요.

**[중요] 반드시 아래 목록에서만 Factor를 선택하세요:**

{factor_list}

**관계 유형:**
- CAUSES: A가 B를 유발 (예: 환율 상승 → 원재료 가격 상승)
- AMPLIFIES: A가 B를 강화/증폭
- MITIGATES: A가 B를 완화/감소

**[핵심] 인과관계 판단 기준:**

✓ 추출해야 하는 것 (명시적 인과):
- "A로 인해 B가..." → A가 B를 유발 (A → B)
- "A에 따른 B" → A가 B에 영향 (A → B)
- "A가 B를 촉진/견인/유발" → (A → B)
- "A 상승으로 B 증가" → (A → B)

✗ 추출하면 안되는 것 (병렬/동시 발생):
- "A와 B로 인해 C가..." → A, B는 병렬 나열 (A↔B 인과 없음)
- "A 및 B가 발생" → 단순 나열
- "A, B 등의 요인" → 단순 나열
- "A 부진과 B 심화로" → A, B 동시 발생

**예시:**

문장: "TV 수요 부진과 경쟁 심화로 실적 악화"
→ "TV 수요 부진"과 "경쟁 심화"는 병렬로 나열된 것
→ TV 수요와 경쟁 심화 사이에 인과관계 없음
→ {{"relations": []}}

문장: "수요 부진에 따른 경쟁 심화로 마케팅비 증가"
→ 수요 부진이 경쟁 심화를 유발 (인과관계 O)
→ {{"relations": [{{"source_factor": "TV 수요", "target_factor": "경쟁 심화", ...}}]}}

**문단:**
{paragraph}

**응답 형식 (JSON):**
```json
{{
  "relations": [
    {{
      "source_factor": "목록 내 Factor명",
      "target_factor": "목록 내 Factor명",
      "relation_type": "CAUSES|AMPLIFIES|MITIGATES",
      "evidence": "인과관계가 드러나는 원문 인용"
    }}
  ]
}}
```

명시적 인과관계가 없으면 빈 배열: {{"relations": []}}
"""


# ============================================================
# Enhanced Factor 관계 추출 프롬프트 (v7 - 완화된 추출)
# ============================================================
ENHANCED_FACTOR_RELATION_PROMPT = """다음 문단에서 Factor들 간의 **인과관계**를 추출하세요.

**[중요] 반드시 아래 목록에서만 Factor를 선택하세요:**

{factor_list}

**관계 유형:**
- CAUSES: A가 B를 유발/영향
- AMPLIFIES: A가 B를 강화/증폭
- MITIGATES: A가 B를 완화/감소

**[완화된 기준] 다음 경우도 인과관계로 추출하세요:**

1. **명시적 인과**: "A로 인해 B가", "A에 따른 B", "A가 B를 유발"
2. **암묵적 인과**: "A 상승 속에서 B도 상승" → A와 B가 연관
3. **연쇄 영향**: "A가 B를 통해 C에" → A→B, B→C 모두 추출
4. **맥락적 추론**:
   - "환율 상승과 원재료 가격 상승" → 환율→원재료 가격 (산업 상식)
   - "금리 인상과 수요 부진" → 금리→소비심리→수요 (경제 상식)
5. **동반 변화**: "A와 B가 동반 상승/하락" → 선행 Factor가 후행 Factor에 영향

**제외 기준 (추출하지 않음):**
- 단순 목록 나열: "A, B, C 등의 요인"
- 동의어/유사어 관계: "환율(원달러)"
- 역순 관계가 명백한 경우: 결과→원인

**문단:**
{paragraph}

**응답 형식 (JSON):**
```json
{{
  "relations": [
    {{
      "source_factor": "원인 Factor",
      "target_factor": "결과 Factor",
      "relation_type": "CAUSES|AMPLIFIES|MITIGATES",
      "confidence": "high|medium|low",
      "evidence": "인과관계 근거 문장",
      "inference_type": "explicit|contextual|domain_knowledge"
    }}
  ]
}}
```

인과관계가 없으면 빈 배열: {{"relations": []}}
"""


# ============================================================
# 기존 Open-Set 프롬프트 (하위 호환)
# ============================================================
# Factor-Factor 관계 추출 프롬프트
FACTOR_RELATION_PROMPT = """다음 문단에서 LG전자 TV(HE) 사업의 실적 변동 요인(Factor)들 간의 인과관계를 추출하세요.

**추출 규칙:**
1. Factor는 실적에 영향을 주는 외부/내부 요인 (예: 환율, 수요, 경쟁, 패널가격, 물류비 등)
2. Factor 간의 인과관계를 추출:
   - CAUSES: A가 B를 유발 (A → B)
   - AMPLIFIES: A가 B를 강화/증폭
   - MITIGATES: A가 B를 완화/감소
3. 문단에서 명시적 또는 암시적으로 언급된 관계만 추출
4. Factor명은 간결하게 (예: "환율", "경쟁심화", "패널가격", "물류비")

**문단:**
{paragraph}

**응답 형식 (JSON):**
```json
{{
  "relations": [
    {{
      "source_factor": "원인 Factor명",
      "target_factor": "결과 Factor명",
      "relation_type": "CAUSES|AMPLIFIES|MITIGATES",
      "evidence": "근거 문장"
    }}
  ]
}}
```

관계가 없으면 빈 배열 반환: {{"relations": []}}
"""


@dataclass
class FactorRelation:
    """Factor-Factor 관계 (v2: 상세 출처 포함)"""
    source_factor: str
    target_factor: str
    relation_type: str
    evidence: str
    doc_name: str
    doc_date: str
    doc_type: str = ""
    page_num: int = 0
    paragraph_text: str = ""


@dataclass
class FactorRelationGraph:
    """Factor-Factor 관계 그래프"""
    relations: List[FactorRelation] = field(default_factory=list)

    def add_relation(self, relation: FactorRelation):
        self.relations.append(relation)

    def aggregate(self) -> List[dict]:
        """관계 집계 (v2: 상세 출처 포함)"""
        relation_map: Dict[Tuple[str, str, str], dict] = {}

        for rel in self.relations:
            key = (rel.source_factor, rel.target_factor, rel.relation_type)
            if key not in relation_map:
                relation_map[key] = {
                    "source_factor": rel.source_factor,
                    "target_factor": rel.target_factor,
                    "relation_type": rel.relation_type,
                    "mention_count": 0,
                    "evidences": [],
                    "sources": []  # 상세 출처 리스트
                }
            relation_map[key]["mention_count"] += 1
            relation_map[key]["evidences"].append(rel.evidence)
            # 상세 출처 추가
            relation_map[key]["sources"].append({
                "doc_name": rel.doc_name,
                "doc_date": rel.doc_date,
                "doc_type": rel.doc_type,
                "page_num": rel.page_num,
                "paragraph": rel.paragraph_text[:300] if rel.paragraph_text else "",
                "evidence": rel.evidence
            })

        return sorted(
            relation_map.values(),
            key=lambda x: x["mention_count"],
            reverse=True
        )

    def summary(self) -> dict:
        return {
            "total_relations": len(self.relations),
            "unique_relations": len(set(
                (r.source_factor, r.target_factor, r.relation_type)
                for r in self.relations
            ))
        }


class FactorRelationExtractor:
    """Factor-Factor 관계 추출기 (v4: OpenAI GPT-4o 모델 사용, 상세 출처 포함)"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 필요")

    def extract_from_paragraph(self, paragraph: Paragraph) -> List[FactorRelation]:
        """문단에서 Factor-Factor 관계 추출 (v4: OpenAI GPT-4o, 상세 출처)"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요: pip install openai")

        client = OpenAI(api_key=self.api_key)
        prompt = FACTOR_RELATION_PROMPT.format(paragraph=paragraph.text)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.choices[0].message.content
        return self._parse_response(response_text, paragraph)

    def _parse_response(self, response: str, paragraph: Paragraph) -> List[FactorRelation]:
        """LLM 응답 파싱 (v2: 상세 출처 포함)"""
        import re

        # JSON 블록 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            relations = []
            for r in data.get("relations", []):
                relations.append(FactorRelation(
                    source_factor=r["source_factor"],
                    target_factor=r["target_factor"],
                    relation_type=r["relation_type"],
                    evidence=r.get("evidence", ""),
                    doc_name=paragraph.doc_name,
                    doc_date=str(paragraph.doc_date),
                    doc_type=paragraph.doc_type,
                    page_num=paragraph.page_num,
                    paragraph_text=paragraph.text,
                ))
            return relations
        except json.JSONDecodeError:
            return []


class FactorRelationBuilder:
    """Factor-Factor 관계 빌드"""

    def __init__(self, layer2_dir: str):
        self.layer2_dir = Path(layer2_dir)
        self.extractor = FactorRelationExtractor()
        self.graph = FactorRelationGraph()

    def build(self, max_paragraphs: Optional[int] = None) -> FactorRelationGraph:
        """전체 문서에서 Factor-Factor 관계 추출"""
        processor = DocumentProcessor(self.layer2_dir)
        para_count = 0

        print("TV 관련 문단에서 Factor-Factor 관계 추출 시작...")

        for paragraph in processor.process_all_documents():
            para_count += 1

            if para_count % 10 == 0:
                print(f"  처리 중: {para_count}개 문단...")

            try:
                relations = self.extractor.extract_from_paragraph(paragraph)
                for relation in relations:
                    self.graph.add_relation(relation)
            except Exception as e:
                print(f"  추출 오류: {e}")

            if max_paragraphs and para_count >= max_paragraphs:
                break

        print(f"\n완료: {self.graph.summary()}")
        return self.graph


def normalize_factor_relations(
    relations: List[dict],
    normalization_path: Path
) -> List[dict]:
    """Factor-Factor 관계 정규화"""
    # 정규화 사전 로드
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

    def normalize_name(name: str) -> Optional[str]:
        name_lower = name.lower()
        if name_lower in exclude_list:
            return None
        return reverse_mapping.get(name_lower, name)

    # 정규화 적용
    normalized = []
    relation_map = {}

    for rel in relations:
        source = normalize_name(rel["source_factor"])
        target = normalize_name(rel["target_factor"])

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

    # 중복 source 제거 및 정렬 (v2: dict 형태의 sources 처리)
    for rel in relation_map.values():
        # sources가 dict인 경우 (상세 출처) - doc_name 기준으로 중복 제거
        unique_sources = []
        seen_docs = set()
        for src in rel["sources"]:
            if isinstance(src, dict):
                doc_key = (src.get("doc_name", ""), src.get("page_num", 0))
                if doc_key not in seen_docs:
                    seen_docs.add(doc_key)
                    unique_sources.append(src)
            else:
                if src not in seen_docs:
                    seen_docs.add(src)
                    unique_sources.append(src)
        rel["sources"] = unique_sources
        normalized.append(rel)

    return sorted(normalized, key=lambda x: x["mention_count"], reverse=True)


def build_factor_relations(
    max_paragraphs: Optional[int] = None,
    output_file: str = "factor_relations.json"
):
    """Factor-Factor 관계 빌드 및 저장"""
    layer2_dir = Path(__file__).parent

    builder = FactorRelationBuilder(str(layer2_dir))
    graph = builder.build(max_paragraphs=max_paragraphs)

    # 집계
    aggregated = graph.aggregate()

    # 정규화
    normalization_path = layer2_dir / "factor_normalization.yaml"
    if normalization_path.exists():
        print("\nFactor 정규화 적용 중...")
        normalized = normalize_factor_relations(aggregated, normalization_path)
    else:
        normalized = aggregated

    # 결과 저장
    result = {
        "summary": {
            "total_extracted": len(graph.relations),
            "aggregated": len(aggregated),
            "normalized": len(normalized),
        },
        "relations": normalized,
    }

    output_path = layer2_dir / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n=== Factor-Factor 관계 추출 완료 ===")
    print(f"추출된 관계: {result['summary']['total_extracted']}개")
    print(f"집계 후: {result['summary']['aggregated']}개")
    print(f"정규화 후: {result['summary']['normalized']}개")
    print(f"결과 저장: {output_path}")

    print("\n=== 상위 관계 ===")
    for rel in normalized[:15]:
        print(f"  {rel['source_factor']} --{rel['relation_type']}--> {rel['target_factor']} ({rel['mention_count']}회)")

    return result


# ============================================================
# Closed-Set Factor 관계 추출기 (v5)
# ============================================================

class ClosedSetFactorRelationExtractor:
    """25개 Factor 내에서만 관계를 추출하는 Closed-Set 추출기"""

    # 25개 Factor에 대한 별칭 매핑
    FACTOR_ALIASES = {
        # 원자재_부품
        "패널가격": "패널 가격",
        "패널단가": "패널 가격",
        "패널 단가": "패널 가격",
        "원자재가격": "원재료 가격",
        "원자재 가격": "원재료 가격",
        "원재료비": "원재료 가격",
        "DRAM": "DRAM 가격",
        "디램": "DRAM 가격",
        "디램 가격": "DRAM 가격",
        # 생산
        "가동률": "공장 가동률",
        "공장가동률": "공장 가동률",
        "인건비용": "인건비",
        # 물류
        "운임": "해상 운임",
        "해상운임": "해상 운임",
        "물류비용": "물류비",
        "운임비": "물류비",
        "컨테이너 운임": "해상 운임",
        # 마케팅
        "마케팅 비용": "마케팅비",
        "프로모션비": "프로모션",
        "프로모션 비용": "프로모션",
        # 수요
        "TV수요": "TV 수요",
        "수요": "TV 수요",
        "소비심리": "소비 심리",
        "소비자심리": "소비 심리",
        "소비자 심리": "소비 심리",
        "계절성 효과": "계절성",
        # 경쟁
        "경쟁심화": "경쟁 심화",
        "경쟁 강화": "경쟁 심화",
        "시장점유율": "점유율",
        "시장 점유율": "점유율",
        "평균판매가격": "ASP",
        "평균 판매가격": "ASP",
        "평균판매단가": "ASP",
        # 거시경제
        "환율변동": "환율",
        "원달러환율": "환율",
        "원/달러": "환율",
        "금리인상": "금리",
        "금리인하": "금리",
        "경기침체": "경기",
        "경기회복": "경기",
        "물가상승": "인플레이션",
        "물가": "인플레이션",
        # 정책_규제
        "관세율": "관세",
        "관세 인상": "관세",
        "무역정책": "무역 정책",
        "무역분쟁": "무역 정책",
        "무역 분쟁": "무역 정책",
        # 제품_기술
        "OLED TV": "OLED",
        "올레드": "OLED",
        "프리미엄제품": "프리미엄 제품",
        "프리미엄 TV": "프리미엄 제품",
        "B2B": "B2B 사업",
        "B2B사업": "B2B 사업",
        "웹OS": "WebOS",
        "webOS": "WebOS",
    }

    def __init__(self, factor_list_path: Optional[Path] = None, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 필요")

        # Factor 목록 로드
        if factor_list_path is None:
            factor_list_path = Path(__file__).parent / "layer2_final.json"

        self.factor_list = self._load_factor_list(factor_list_path)
        self.factor_names = [f["name"] for f in self.factor_list]
        self.factor_names_lower = {f.lower(): f for f in self.factor_names}

        # 별칭 맵 빌드 (소문자 → 정규 이름)
        self.alias_map = {k.lower(): v for k, v in self.FACTOR_ALIASES.items()}

        print(f"ClosedSetFactorRelationExtractor 초기화: {len(self.factor_names)}개 Factor 로드")

    def _load_factor_list(self, path: Path) -> List[dict]:
        """layer2_final.json에서 Factor 목록 로드"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("factors", [])

    def _format_factor_list_for_prompt(self) -> str:
        """프롬프트용 Factor 목록 포맷팅"""
        # 카테고리별로 그룹화
        by_category = defaultdict(list)
        for f in self.factor_list:
            by_category[f["category"]].append(f["name"])

        lines = []
        for cat, factors in by_category.items():
            lines.append(f"- {cat}: {', '.join(factors)}")
        return "\n".join(lines)

    def _validate_and_normalize(self, factor_name: str) -> Optional[str]:
        """Factor명 검증 및 정규화 (25개 목록 내에서만)"""
        if not factor_name:
            return None

        name_lower = factor_name.strip().lower()

        # 1. 정확히 일치
        if name_lower in self.factor_names_lower:
            return self.factor_names_lower[name_lower]

        # 2. 별칭 매칭
        if name_lower in self.alias_map:
            return self.alias_map[name_lower]

        # 3. 부분 매칭 (마지막 시도)
        for canonical in self.factor_names:
            if name_lower in canonical.lower() or canonical.lower() in name_lower:
                return canonical

        return None  # 목록에 없음

    def extract_from_paragraph(self, paragraph: Paragraph) -> List[FactorRelation]:
        """문단에서 Closed-Set Factor-Factor 관계 추출"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요: pip install openai")

        client = OpenAI(api_key=self.api_key)

        factor_list_str = self._format_factor_list_for_prompt()
        prompt = CLOSED_SET_FACTOR_RELATION_PROMPT.format(
            factor_list=factor_list_str,
            paragraph=paragraph.text
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.choices[0].message.content
        return self._parse_and_validate_response(response_text, paragraph)

    def _parse_and_validate_response(self, response: str, paragraph: Paragraph) -> List[FactorRelation]:
        """LLM 응답 파싱 및 Factor 검증"""
        import re

        # JSON 블록 추출
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            relations = []

            for r in data.get("relations", []):
                # Factor 검증 및 정규화
                source = self._validate_and_normalize(r.get("source_factor", ""))
                target = self._validate_and_normalize(r.get("target_factor", ""))

                # 유효한 경우만 추가
                if source and target and source != target:
                    rel_type = r.get("relation_type", "CAUSES")
                    if rel_type not in ["CAUSES", "AMPLIFIES", "MITIGATES"]:
                        rel_type = "CAUSES"

                    relations.append(FactorRelation(
                        source_factor=source,
                        target_factor=target,
                        relation_type=rel_type,
                        evidence=r.get("evidence", ""),
                        doc_name=paragraph.doc_name,
                        doc_date=str(paragraph.doc_date),
                        doc_type=paragraph.doc_type,
                        page_num=paragraph.page_num,
                        paragraph_text=paragraph.text,
                    ))

            return relations
        except json.JSONDecodeError:
            return []


class ClosedSetFactorRelationBuilder:
    """Closed-Set Factor-Factor 관계 빌드"""

    def __init__(self, layer2_dir: str):
        self.layer2_dir = Path(layer2_dir)
        self.extractor = ClosedSetFactorRelationExtractor(
            factor_list_path=self.layer2_dir / "layer2_final.json"
        )
        self.graph = FactorRelationGraph()

    def build(self, max_paragraphs: Optional[int] = None) -> FactorRelationGraph:
        """전체 문서에서 Closed-Set Factor-Factor 관계 추출"""
        processor = DocumentProcessor(self.layer2_dir)
        para_count = 0

        print("=" * 60)
        print("Closed-Set Factor-Factor 관계 추출 시작")
        print(f"Factor 목록: {len(self.extractor.factor_names)}개")
        print("=" * 60)

        for paragraph in processor.process_all_documents():
            para_count += 1

            if para_count % 20 == 0:
                print(f"  처리 중: {para_count}개 문단... (관계 {len(self.graph.relations)}개)")

            try:
                relations = self.extractor.extract_from_paragraph(paragraph)
                for relation in relations:
                    self.graph.add_relation(relation)
            except Exception as e:
                print(f"  추출 오류 (문단 {para_count}): {e}")

            if max_paragraphs and para_count >= max_paragraphs:
                print(f"\n최대 문단 수 도달: {max_paragraphs}")
                break

        print(f"\n완료: {para_count}개 문단 처리, {self.graph.summary()}")
        return self.graph


def build_closed_set_factor_relations(
    max_paragraphs: Optional[int] = None,
    output_file: str = "factor_relations_closed.json"
):
    """Closed-Set Factor-Factor 관계 빌드 및 저장"""
    layer2_dir = Path(__file__).parent

    builder = ClosedSetFactorRelationBuilder(str(layer2_dir))
    graph = builder.build(max_paragraphs=max_paragraphs)

    # 집계
    aggregated = graph.aggregate()

    # 결과 저장
    result = {
        "summary": {
            "factor_count": len(builder.extractor.factor_names),
            "factors": builder.extractor.factor_names,
            "total_extracted": len(graph.relations),
            "unique_relations": len(aggregated),
        },
        "relations": aggregated,
    }

    output_path = layer2_dir / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("Closed-Set Factor-Factor 관계 추출 완료")
    print(f"{'=' * 60}")
    print(f"Factor 수: {result['summary']['factor_count']}개")
    print(f"추출된 관계: {result['summary']['total_extracted']}개")
    print(f"집계 후 (고유): {result['summary']['unique_relations']}개")
    print(f"결과 저장: {output_path}")

    print(f"\n=== 상위 15개 관계 ===")
    for rel in aggregated[:15]:
        print(f"  {rel['source_factor']} --{rel['relation_type']}--> {rel['target_factor']} ({rel['mention_count']}회)")

    return result


# ============================================================
# 2차 검증: Factor 관계 Validator (v7)
# ============================================================

VALIDATION_PROMPT = """TV 산업 Factor-Factor 관계의 타당성을 검토하세요.

관계: {source} → {target}
근거: {evidence}

TV 산업 도메인 지식 (참고):
- 거시경제: 환율↑→원재료가격↑, 금리↑→소비심리↓, 경기↑→수요↑
- 공급망: 해상운임↑→물류비↑, 패널가격↑→원가↑
- 경쟁: 경쟁심화→마케팅비↑, 경쟁심화→ASP↓
- 수요: 소비심리↑→TV수요↑, 수요↑→가동률↑

검토 기준:
1. TV/가전 산업에서 이 인과관계가 성립하는가?
2. polarity 방향:
   - Source↑ → Target↑ 또는 Source↓ → Target↓: polarity = 1
   - Source↑ → Target↓ 또는 Source↓ → Target↑: polarity = -1

중요:
- 산업 상식에 부합하면 valid=true
- 단순 병렬 나열만 valid=false

반드시 아래 JSON 형식으로만 응답:
{{"valid": true, "reason": "이유", "polarity": 1}}
또는
{{"valid": false, "reason": "이유", "polarity": 0}}
"""


class FactorRelationValidator:
    """Factor-Factor 관계 2차 검증"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 필요")

    def validate_relation(self, source: str, target: str, evidence: str) -> dict:
        """단일 관계 검증"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요")

        client = OpenAI(api_key=self.api_key)
        prompt = VALIDATION_PROMPT.format(
            source=source,
            target=target,
            evidence=evidence
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.choices[0].message.content
        return self._parse_response(response_text)

    def _parse_response(self, response: str) -> dict:
        """검증 응답 파싱 (robust)"""
        import re

        # 1. JSON 블록에서 추출 시도
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 2. { } 사이의 JSON 추출 시도
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = response

        try:
            data = json.loads(json_str)
            return {
                "valid": data.get("valid", False),
                "reason": data.get("reason", ""),
                "polarity": data.get("polarity", 1)
            }
        except json.JSONDecodeError:
            # 3. 텍스트에서 패턴 추출 시도
            valid_match = re.search(r'"valid"\s*:\s*(true|false)', response, re.I)
            polarity_match = re.search(r'"polarity"\s*:\s*(-?1|0)', response)

            if valid_match:
                is_valid = valid_match.group(1).lower() == "true"
                polarity = int(polarity_match.group(1)) if polarity_match else (1 if is_valid else 0)
                return {
                    "valid": is_valid,
                    "reason": "패턴 추출",
                    "polarity": polarity
                }

            return {"valid": False, "reason": "파싱 오류", "polarity": 0}

    def validate_all(self, relations: List[dict]) -> List[dict]:
        """모든 관계 검증"""
        validated = []

        for i, rel in enumerate(relations):
            source = rel["source_factor"]
            target = rel["target_factor"]

            # 대표 evidence 선택 (첫 번째)
            sources = rel.get("sources", [])
            if sources and isinstance(sources[0], dict):
                evidence = sources[0].get("evidence", "")[:200]
            else:
                evidence = str(sources[0])[:200] if sources else ""

            print(f"  [{i+1}/{len(relations)}] {source} → {target}...", end=" ")

            result = self.validate_relation(source, target, evidence)

            if result["valid"]:
                print(f"✓ (polarity: {result['polarity']:+d})")
                validated.append({
                    **rel,
                    "validated": True,
                    "polarity": result["polarity"],
                    "validation_reason": result["reason"]
                })
            else:
                print(f"✗ ({result['reason'][:30]}...)")

        return validated


def validate_and_reload_relations(
    input_file: str = "factor_relations_closed_v6.json",
    output_file: str = "factor_relations_validated.json"
):
    """관계 검증 후 Neo4j 재적재"""
    from .factor_relation_loader import FactorRelationNeo4jLoader

    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file
    output_path = layer2_dir / output_file

    print("=" * 60)
    print("Factor-Factor 관계 2차 검증")
    print("=" * 60)

    # 입력 로드
    print("\n1. 관계 로드...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    relations = data.get("relations", [])
    print(f"  로드된 관계: {len(relations)}개")

    # 검증
    print("\n2. 2차 검증 시작...")
    validator = FactorRelationValidator()
    validated = validator.validate_all(relations)

    print(f"\n  검증 결과: {len(validated)}/{len(relations)}개 통과")

    # 결과 저장
    result = {
        "summary": {
            "original_count": len(relations),
            "validated_count": len(validated),
            "rejection_rate": f"{(1 - len(validated)/len(relations))*100:.1f}%"
        },
        "relations": validated
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  저장: {output_path}")

    # Neo4j 적재
    print("\n3. Neo4j 적재...")
    with FactorRelationNeo4jLoader() as loader:
        loader.clear_factor_relations()

        # validated 관계에 대해 sources_json 변환
        for rel in validated:
            sources = rel.get("sources", [])
            if sources and isinstance(sources[0], dict):
                rel["sources_json"] = json.dumps(sources[:5], ensure_ascii=False)
            else:
                rel["sources_json"] = json.dumps(sources[:5])
            rel["original_types_json"] = json.dumps(rel.get("original_types", []))

        # 적재 쿼리 실행
        query = """
        UNWIND $relations AS rel
        MATCH (source:Factor {id: toLower(replace(rel.source_factor, ' ', '_'))})
        MATCH (target:Factor {id: toLower(replace(rel.target_factor, ' ', '_'))})
        MERGE (source)-[r:INFLUENCES]->(target)
        SET r.type = 'AFFECTS',
            r.polarity = rel.polarity,
            r.mention_count = rel.mention_count,
            r.validation_reason = rel.validation_reason,
            r.sources = rel.sources_json
        RETURN count(r) as count
        """
        with loader.driver.session(database=loader.config.neo4j_database) as session:
            result_neo = session.run(query, relations=validated)
            record = result_neo.single()
            rel_count = record["count"] if record else 0

        print(f"  생성된 관계: {rel_count}개")

    # 결과 출력
    print(f"\n{'=' * 60}")
    print("검증 완료")
    print(f"{'=' * 60}")
    print(f"원본: {len(relations)}개 → 검증 통과: {len(validated)}개")

    print("\n--- 검증 통과 관계 ---")
    for rel in validated[:10]:
        pol = rel["polarity"]
        pol_str = f"+{pol}" if pol > 0 else str(pol)
        print(f"  {rel['source_factor']} → {rel['target_factor']}: {rel['mention_count']}회 (polarity: {pol_str})")

    return result


# ============================================================
# Enhanced Factor 관계 추출기 (v7 - 완화된 프롬프트 + 도메인 규칙)
# ============================================================

class EnhancedFactorRelationExtractor:
    """완화된 프롬프트 + 도메인 규칙 기반 Factor-Factor 관계 추출기"""

    def __init__(self, factor_list_path: Optional[Path] = None, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 필요")

        # Factor 목록 로드
        if factor_list_path is None:
            factor_list_path = Path(__file__).parent / "layer2_final.json"

        self.layer2_dir = Path(__file__).parent
        self.factor_list = self._load_factor_list(factor_list_path)
        self.factor_names = [f["name"] for f in self.factor_list]
        self.factor_names_lower = {f.lower(): f for f in self.factor_names}

        # 별칭 맵 (ClosedSetFactorRelationExtractor에서 가져옴)
        self.alias_map = {
            "패널가격": "패널 가격", "패널단가": "패널 가격",
            "원자재가격": "원재료 가격", "원재료비": "원재료 가격",
            "해상운임": "해상 운임", "운임": "해상 운임",
            "물류비용": "물류비", "운임비": "물류비",
            "마케팅 비용": "마케팅비",
            "TV수요": "TV 수요", "수요": "TV 수요",
            "소비심리": "소비 심리", "소비자심리": "소비 심리",
            "경쟁심화": "경쟁 심화", "경쟁 강화": "경쟁 심화",
            "시장점유율": "점유율", "시장 점유율": "점유율",
            "환율변동": "환율", "원달러환율": "환율",
            "금리인상": "금리", "금리인하": "금리",
            "경기침체": "경기", "경기회복": "경기",
            "관세율": "관세", "관세 인상": "관세",
        }
        self.alias_map = {k.lower(): v for k, v in self.alias_map.items()}

        # 도메인 규칙 로드
        from .domain_relations import DOMAIN_RULES_CANDIDATES
        self.domain_rules = DOMAIN_RULES_CANDIDATES

        print(f"EnhancedFactorRelationExtractor 초기화: {len(self.factor_names)}개 Factor, {len(self.domain_rules)}개 도메인 규칙")

    def _load_factor_list(self, path: Path) -> List[dict]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("factors", [])

    def _format_factor_list_for_prompt(self) -> str:
        by_category = defaultdict(list)
        for f in self.factor_list:
            by_category[f["category"]].append(f["name"])
        lines = []
        for cat, factors in by_category.items():
            lines.append(f"- {cat}: {', '.join(factors)}")
        return "\n".join(lines)

    def _validate_and_normalize(self, factor_name: str) -> Optional[str]:
        if not factor_name:
            return None
        name_lower = factor_name.strip().lower()
        if name_lower in self.factor_names_lower:
            return self.factor_names_lower[name_lower]
        if name_lower in self.alias_map:
            return self.alias_map[name_lower]
        for canonical in self.factor_names:
            if name_lower in canonical.lower() or canonical.lower() in name_lower:
                return canonical
        return None

    def _detect_mentioned_factors(self, text: str) -> List[str]:
        """문단에서 언급된 Factor 탐지"""
        mentioned = []
        text_lower = text.lower()

        for factor in self.factor_names:
            if factor.lower() in text_lower:
                mentioned.append(factor)

        # 별칭도 체크
        for alias, canonical in self.alias_map.items():
            if alias in text_lower and canonical not in mentioned:
                mentioned.append(canonical)

        return mentioned

    def extract_from_paragraph(self, paragraph: Paragraph) -> List[FactorRelation]:
        """문단에서 관계 추출 (완화된 프롬프트 + 도메인 규칙)"""
        relations = []

        # 1. 완화된 프롬프트로 추출
        explicit_relations = self._extract_with_enhanced_prompt(paragraph)
        relations.extend(explicit_relations)

        # 2. 도메인 규칙 적용
        domain_relations = self._apply_domain_rules(paragraph)
        relations.extend(domain_relations)

        # 3. 중복 제거
        unique_relations = self._dedupe_relations(relations)

        return unique_relations

    def _extract_with_enhanced_prompt(self, paragraph: Paragraph) -> List[FactorRelation]:
        """완화된 프롬프트로 추출"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요")

        client = OpenAI(api_key=self.api_key)
        factor_list_str = self._format_factor_list_for_prompt()
        prompt = ENHANCED_FACTOR_RELATION_PROMPT.format(
            factor_list=factor_list_str,
            paragraph=paragraph.text
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.choices[0].message.content
        return self._parse_response(response_text, paragraph, inference_type="document")

    def _apply_domain_rules(self, paragraph: Paragraph) -> List[FactorRelation]:
        """도메인 규칙 적용 (문단에서 두 Factor가 언급된 경우)"""
        mentioned = self._detect_mentioned_factors(paragraph.text)
        relations = []

        for rule in self.domain_rules:
            if rule.source in mentioned and rule.target in mentioned:
                relations.append(FactorRelation(
                    source_factor=rule.source,
                    target_factor=rule.target,
                    relation_type="CAUSES",
                    evidence=f"[도메인 규칙] {rule.rationale}",
                    doc_name=paragraph.doc_name,
                    doc_date=str(paragraph.doc_date),
                    doc_type=paragraph.doc_type,
                    page_num=paragraph.page_num,
                    paragraph_text=paragraph.text,
                ))

        return relations

    def _parse_response(self, response: str, paragraph: Paragraph, inference_type: str) -> List[FactorRelation]:
        """LLM 응답 파싱"""
        import re

        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            relations = []

            for r in data.get("relations", []):
                source = self._validate_and_normalize(r.get("source_factor", ""))
                target = self._validate_and_normalize(r.get("target_factor", ""))

                if source and target and source != target:
                    rel_type = r.get("relation_type", "CAUSES")
                    if rel_type not in ["CAUSES", "AMPLIFIES", "MITIGATES"]:
                        rel_type = "CAUSES"

                    relations.append(FactorRelation(
                        source_factor=source,
                        target_factor=target,
                        relation_type=rel_type,
                        evidence=r.get("evidence", ""),
                        doc_name=paragraph.doc_name,
                        doc_date=str(paragraph.doc_date),
                        doc_type=paragraph.doc_type,
                        page_num=paragraph.page_num,
                        paragraph_text=paragraph.text,
                    ))

            return relations
        except json.JSONDecodeError:
            return []

    def _dedupe_relations(self, relations: List[FactorRelation]) -> List[FactorRelation]:
        """중복 관계 제거 (source-target-type 기준)"""
        seen = set()
        unique = []
        for rel in relations:
            key = (rel.source_factor, rel.target_factor, rel.relation_type)
            if key not in seen:
                seen.add(key)
                unique.append(rel)
        return unique


class EnhancedFactorRelationBuilder:
    """Enhanced Factor-Factor 관계 빌드 (추출 + 도메인 규칙)"""

    def __init__(self, layer2_dir: str):
        self.layer2_dir = Path(layer2_dir)
        self.extractor = EnhancedFactorRelationExtractor(
            factor_list_path=self.layer2_dir / "layer2_final.json"
        )
        self.graph = FactorRelationGraph()

    def build(self, max_paragraphs: Optional[int] = None) -> FactorRelationGraph:
        """전체 문서에서 Factor-Factor 관계 추출"""
        processor = DocumentProcessor(self.layer2_dir)
        para_count = 0

        print("=" * 60)
        print("Enhanced Factor-Factor 관계 추출 시작")
        print(f"Factor 목록: {len(self.extractor.factor_names)}개")
        print(f"도메인 규칙: {len(self.extractor.domain_rules)}개")
        print("=" * 60)

        for paragraph in processor.process_all_documents():
            para_count += 1

            if para_count % 20 == 0:
                print(f"  처리 중: {para_count}개 문단... (관계 {len(self.graph.relations)}개)")

            try:
                relations = self.extractor.extract_from_paragraph(paragraph)
                for relation in relations:
                    self.graph.add_relation(relation)
            except Exception as e:
                print(f"  추출 오류 (문단 {para_count}): {e}")

            if max_paragraphs and para_count >= max_paragraphs:
                print(f"\n최대 문단 수 도달: {max_paragraphs}")
                break

        print(f"\n완료: {para_count}개 문단 처리, {self.graph.summary()}")
        return self.graph


def build_enhanced_factor_relations(
    max_paragraphs: Optional[int] = None,
    output_file: str = "factor_relations_enhanced.json"
):
    """Enhanced Factor-Factor 관계 빌드 및 저장"""
    layer2_dir = Path(__file__).parent

    builder = EnhancedFactorRelationBuilder(str(layer2_dir))
    graph = builder.build(max_paragraphs=max_paragraphs)

    # 집계
    aggregated = graph.aggregate()

    # 결과 저장
    result = {
        "summary": {
            "total_extracted": len(graph.relations),
            "aggregated": len(aggregated),
        },
        "relations": aggregated,
    }

    output_path = layer2_dir / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("Enhanced Factor-Factor 관계 추출 완료")
    print(f"{'=' * 60}")
    print(f"추출된 관계: {result['summary']['total_extracted']}개")
    print(f"집계 후: {result['summary']['aggregated']}개")
    print(f"결과 저장: {output_path}")

    print("\n=== 상위 15개 관계 ===")
    for rel in aggregated[:15]:
        print(f"  {rel['source_factor']} --{rel['relation_type']}--> {rel['target_factor']} ({rel['mention_count']}회)")

    return result


def validate_enhanced_relations(
    input_file: str = "factor_relations_enhanced.json",
    output_file: str = "factor_relations_enhanced_validated.json"
):
    """Enhanced 관계 LLM 검증 후 Neo4j 적재"""
    from .factor_relation_loader import FactorRelationNeo4jLoader

    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file
    output_path = layer2_dir / output_file

    print("=" * 60)
    print("Enhanced Factor-Factor 관계 LLM 검증")
    print("=" * 60)

    # 입력 로드
    print("\n1. 관계 로드...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    relations = data.get("relations", [])
    print(f"  로드된 관계: {len(relations)}개")

    # 도메인 규칙 기반 / 문서 추출 분류
    domain_based = [r for r in relations if any("[도메인 규칙]" in e for e in r.get("evidences", []))]
    document_based = [r for r in relations if not any("[도메인 규칙]" in e for e in r.get("evidences", []))]
    print(f"  - 도메인 규칙 기반: {len(domain_based)}개")
    print(f"  - 문서 추출 기반: {len(document_based)}개")

    # 검증
    print("\n2. LLM 검증 시작...")
    validator = FactorRelationValidator()
    validated = validator.validate_all(relations)

    print(f"\n  검증 결과: {len(validated)}/{len(relations)}개 통과")

    # 결과 저장
    result = {
        "summary": {
            "original_count": len(relations),
            "validated_count": len(validated),
            "rejection_rate": f"{(1 - len(validated)/len(relations))*100:.1f}%"
        },
        "relations": validated
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  저장: {output_path}")

    # Neo4j 적재
    print("\n3. Neo4j 적재...")
    with FactorRelationNeo4jLoader() as loader:
        loader.clear_factor_relations()

        # validated 관계에 대해 sources_json 변환
        for rel in validated:
            sources = rel.get("sources", [])
            if sources and isinstance(sources[0], dict):
                rel["sources_json"] = json.dumps(sources[:5], ensure_ascii=False)
            else:
                rel["sources_json"] = json.dumps(sources[:5])
            rel["original_types_json"] = json.dumps(rel.get("original_types", []))

        # 적재 쿼리 실행
        query = """
        UNWIND $relations AS rel
        MATCH (source:Factor {id: toLower(replace(rel.source_factor, ' ', '_'))})
        MATCH (target:Factor {id: toLower(replace(rel.target_factor, ' ', '_'))})
        MERGE (source)-[r:INFLUENCES]->(target)
        SET r.type = 'AFFECTS',
            r.polarity = rel.polarity,
            r.mention_count = rel.mention_count,
            r.validation_reason = rel.validation_reason,
            r.sources = rel.sources_json
        RETURN count(r) as count
        """
        with loader.driver.session(database=loader.config.neo4j_database) as session:
            result_neo = session.run(query, relations=validated)
            record = result_neo.single()
            rel_count = record["count"] if record else 0

        print(f"  생성된 관계: {rel_count}개")

    # 결과 출력
    print(f"\n{'=' * 60}")
    print("검증 완료")
    print(f"{'=' * 60}")
    print(f"원본: {len(relations)}개 → 검증 통과: {len(validated)}개")

    # 도메인 규칙 통과율 확인
    domain_validated = [r for r in validated if "[도메인 규칙]" in r.get("validation_reason", "")]
    doc_validated = len(validated) - len(domain_validated)

    print(f"\n--- 관계 유형별 통계 ---")
    print(f"  도메인 규칙 기반: {len(domain_validated)}개 통과")
    print(f"  문서 추출 기반: {doc_validated}개 통과")

    print("\n--- 검증 통과 관계 (상위 15개) ---")
    for rel in validated[:15]:
        pol = rel["polarity"]
        pol_str = f"+{pol}" if pol > 0 else str(pol)
        print(f"  {rel['source_factor']} → {rel['target_factor']}: {rel['mention_count']}회 (polarity: {pol_str})")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["open", "closed", "validate", "enhanced", "validate-enhanced"], default="enhanced",
                        help="모드: open(기존), closed(25개), validate(2차검증), enhanced(완화+도메인), validate-enhanced(enhanced 검증)")
    parser.add_argument("--max", type=int, default=None, help="최대 문단 수")
    args = parser.parse_args()

    if args.mode == "validate-enhanced":
        validate_enhanced_relations()
    elif args.mode == "enhanced":
        build_enhanced_factor_relations(max_paragraphs=args.max)
    elif args.mode == "validate":
        validate_and_reload_relations()
    elif args.mode == "closed":
        build_closed_set_factor_relations(max_paragraphs=args.max)
    else:
        build_factor_relations(max_paragraphs=args.max)
