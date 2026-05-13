"""Layer 2 실행 - Factor 추출 및 Neo4j 적재"""

import argparse
import json
from pathlib import Path
from datetime import date
from dotenv import load_dotenv

load_dotenv()


def test_pdf_extraction():
    """PDF 추출 테스트"""
    from .pdf_extractor import DocumentProcessor

    layer2_dir = Path(__file__).parent
    processor = DocumentProcessor(layer2_dir)

    print("=== 문서 목록 ===")
    docs = processor.get_document_list()
    print(f"총 {len(docs)}개 문서")
    for doc in docs[:5]:
        print(f"  [{doc['type']}] {doc['date']} - {doc['name'][:50]}...")

    print("\n=== TV 문단 추출 테스트 ===")
    count = 0
    for para in processor.process_all_documents():
        print(f"\n[{para.doc_type}] {para.doc_date} - p.{para.page_num}")
        print(f"  {para.text[:100]}...")
        count += 1
        if count >= 5:
            break

    print(f"\n총 {count}개 TV 관련 문단 샘플")


def test_factor_extraction():
    """Factor 추출 테스트 (1개 문서)"""
    from .pdf_extractor import DocumentProcessor
    from .factor_extractor import FactorExtractor

    layer2_dir = Path(__file__).parent
    processor = DocumentProcessor(layer2_dir)
    extractor = FactorExtractor()

    print("=== Factor 추출 테스트 ===")
    count = 0
    for para in processor.process_all_documents():
        print(f"\n문단: {para.text[:80]}...")

        mentions = extractor.extract_from_paragraph(para)
        if mentions:
            for m in mentions:
                print(f"  → Factor: {m.factor_name}")
                print(f"     Anchor: {m.anchor_id}")
                print(f"     관계: {m.relation_type.value}")

        count += 1
        if count >= 3:
            break


def build_layer2(max_docs: int = None, output: str = None):
    """전체 Layer 2 빌드"""
    from .factor_extractor import Layer2Builder

    layer2_dir = Path(__file__).parent
    builder = Layer2Builder(str(layer2_dir))

    graph = builder.build(max_docs=max_docs)

    print("\n=== 결과 요약 ===")
    print(f"Factor 수: {len(graph.factors)}")
    print(f"관계 수: {len(graph.relations)}")
    print(f"총 언급 수: {sum(f.mention_count for f in graph.factors)}")

    print("\n=== Factor 목록 ===")
    for factor in sorted(graph.factors, key=lambda f: f.mention_count, reverse=True)[:10]:
        print(f"  {factor.name}: {factor.mention_count}회 언급")

    print("\n=== 주요 관계 ===")
    for rel in sorted(graph.relations, key=lambda r: r.mention_count, reverse=True)[:10]:
        print(f"  {rel.factor_id} --{rel.relation_type.value}--> {rel.anchor_id} ({rel.mention_count}회)")

    # JSON 출력
    if output:
        output_path = Path(output)
        result = {
            "summary": graph.summary(),
            "factors": [f.to_dict() for f in graph.factors],
            "relations": [r.to_dict() for r in graph.relations],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {output_path}")

    return graph


def main():
    parser = argparse.ArgumentParser(description="Layer 2: Factor Extraction")
    parser.add_argument(
        "command",
        choices=["test-pdf", "test-extract", "build"],
        help="실행할 명령"
    )
    parser.add_argument(
        "--max-docs", "-n",
        type=int,
        default=None,
        help="처리할 최대 문서 수"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="결과 출력 파일 (JSON)"
    )

    args = parser.parse_args()

    if args.command == "test-pdf":
        test_pdf_extraction()
    elif args.command == "test-extract":
        test_factor_extraction()
    elif args.command == "build":
        build_layer2(max_docs=args.max_docs, output=args.output)


if __name__ == "__main__":
    main()
