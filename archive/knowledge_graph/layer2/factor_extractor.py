"""Factor 추출 - LLM 기반 Factor-Anchor 관계 추출

v2 개선사항:
- polarity/weight 속성 추출 추가
- 관계의 방향성과 영향력 정량화
"""

import json
import os
from typing import List, Optional
from dataclasses import dataclass

from .models import (
    FactorMention, SourceReference, RelationType,
    FactorCategory, Layer2Graph
)
from .pdf_extractor import Paragraph


# Factor-Anchor 관계 추출 프롬프트 (v4: 9개 카테고리 + 2개 Anchor)
EXTRACTION_PROMPT = """다음 문단에서 LG전자 TV(HE) 사업의 실적 변동 요인(Factor)을 추출하세요.

**카테고리 (9개):**
1. 원자재_부품: 패널가격, DRAM, 원재료, 부품수급
2. 생산: 공장가동률, 인건비, 생산효율
3. 물류: 해상운임, 물류비, 공급망리스크
4. 마케팅: 마케팅비, 프로모션, 브랜드
5. 수요: TV수요, 가전수요, 지역별수요, 계절성, 소비심리
6. 경쟁: 점유율, 경쟁심화, 가격경쟁, ASP
7. 거시경제: 환율, 금리, 경기, 인플레이션
8. 정책_규제: 관세, 무역정책, 환경규제
9. 제품_기술: OLED, 프리미엄, WebOS, AI, B2B

**Anchor (KPI) - 2개:**
- revenue: 매출, 판매량, 수익
- cost: 원가, 비용

**추출 규칙:**
1. Factor는 간결하게 (2-4단어): "글로벌 TV 수요" (O), "글로벌 TV 수요가 회복되고 있다" (X)
2. 구체적인 Factor만: "수요" (X) → "TV 수요" (O), "가전 수요" (O)
3. polarity: +1 (정상관), -1 (역상관)
4. 문단에서 명시적으로 언급된 관계만 추출

**문단:**
{paragraph}

**응답 형식 (JSON):**
```json
{{
  "factors": [
    {{
      "factor_name": "요인명 (2-4단어)",
      "category": "카테고리명",
      "anchor_id": "revenue|cost",
      "polarity": 1 또는 -1,
      "evidence": "근거 문장"
    }}
  ]
}}
```

관계가 없으면 빈 배열 반환: {{"factors": []}}
"""


@dataclass
class ExtractionResult:
    """추출 결과 (v4: category 추가)"""
    factor_name: str
    anchor_id: str
    category: str = ""      # 9개 카테고리 중 하나
    polarity: int = 0       # -1: 역상관, +1: 정상관
    evidence: str = ""
    # 하위 호환용
    relation_type: str = ""

    def __post_init__(self):
        """polarity에서 relation_type 자동 추론 (하위 호환)"""
        if not self.relation_type:
            if self.polarity > 0:
                self.relation_type = "PROPORTIONAL"
            elif self.polarity < 0:
                self.relation_type = "INVERSELY_PROPORTIONAL"
            else:
                self.relation_type = "AFFECTS"


class FactorExtractor:
    """LLM 기반 Factor 추출 (v3: OpenAI 모델 사용)"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 필요")

    def extract_from_paragraph(self, paragraph: Paragraph) -> List[FactorMention]:
        """문단에서 Factor-Anchor 관계 추출 (v3: OpenAI 모델)"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요: pip install openai")

        client = OpenAI(api_key=self.api_key)
        prompt = EXTRACTION_PROMPT.format(paragraph=paragraph.text)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.choices[0].message.content
        results = self._parse_response(response_text)

        # FactorMention으로 변환
        mentions = []
        for result in results:
            try:
                mention = FactorMention(
                    factor_name=result.factor_name,
                    anchor_id=result.anchor_id,
                    relation_type=RelationType(result.relation_type),
                    source=SourceReference(
                        doc_name=paragraph.doc_name,
                        doc_date=paragraph.doc_date,
                        doc_type=paragraph.doc_type,
                        paragraph=paragraph.text,
                        page_num=paragraph.page_num,
                    ),
                    polarity=result.polarity,
                    category=result.category,  # v4: category 추가
                )
                mentions.append(mention)
            except (KeyError, ValueError) as e:
                print(f"파싱 오류: {e}")
                continue

        return mentions

    def _parse_response(self, response: str) -> List[ExtractionResult]:
        """LLM 응답 파싱 (v2: polarity 기반, weight는 mention_count로 자동 계산)"""
        # JSON 블록 추출
        import re
        json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response

        try:
            data = json.loads(json_str)
            factors = data.get("factors", [])
            results = []
            for f in factors:
                polarity = f.get("polarity", 0)

                # 하위 호환: relation_type이 있으면 polarity 추론
                if polarity == 0 and "relation_type" in f:
                    if f["relation_type"] == "PROPORTIONAL":
                        polarity = 1
                    elif f["relation_type"] == "INVERSELY_PROPORTIONAL":
                        polarity = -1

                results.append(ExtractionResult(
                    factor_name=f["factor_name"],
                    anchor_id=f["anchor_id"],
                    category=f.get("category", ""),
                    polarity=polarity,
                    evidence=f.get("evidence", ""),
                ))
            return results
        except json.JSONDecodeError:
            return []


class Layer2Builder:
    """Layer 2 그래프 빌더"""

    def __init__(self, layer2_dir: str):
        from pathlib import Path
        self.layer2_dir = Path(layer2_dir)
        self.extractor = FactorExtractor()
        self.graph = Layer2Graph()

    def build(self, max_docs: Optional[int] = None) -> Layer2Graph:
        """전체 문서에서 Factor 추출"""
        from .pdf_extractor import DocumentProcessor

        processor = DocumentProcessor(self.layer2_dir)
        doc_count = 0
        para_count = 0

        print("TV 관련 문단에서 Factor 추출 시작...")

        for paragraph in processor.process_all_documents():
            para_count += 1

            # 진행 상황 출력
            if para_count % 10 == 0:
                print(f"  처리 중: {para_count}개 문단...")

            try:
                mentions = self.extractor.extract_from_paragraph(paragraph)
                for mention in mentions:
                    self.graph.add_mention(mention)
            except Exception as e:
                print(f"  추출 오류: {e}")

            # 문서 수 제한
            if max_docs and doc_count >= max_docs:
                break

        # 관계 집계
        self.graph.aggregate_relations()

        print(f"\n완료: {self.graph.summary()}")
        return self.graph

    def build_from_paragraphs(self, paragraphs: List[Paragraph]) -> Layer2Graph:
        """주어진 문단들에서 Factor 추출"""
        for para in paragraphs:
            try:
                mentions = self.extractor.extract_from_paragraph(para)
                for mention in mentions:
                    self.graph.add_mention(mention)
            except Exception as e:
                print(f"추출 오류: {e}")

        self.graph.aggregate_relations()
        return self.graph
