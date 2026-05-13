"""PDF 텍스트 추출 및 TV 문단 필터링"""

import re
from pathlib import Path
from datetime import date
from typing import List, Optional, Generator
from dataclasses import dataclass

import yaml


@dataclass
class Paragraph:
    """추출된 문단"""
    text: str
    page_num: int
    doc_name: str
    doc_date: date
    doc_type: str  # consensus / dart


class PDFExtractor:
    """PDF에서 텍스트 추출"""

    def __init__(self, keywords_path: Path):
        self.keywords = self._load_keywords(keywords_path)

    def _load_keywords(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def extract_paragraphs(self, pdf_path: Path) -> List[Paragraph]:
        """PDF에서 문단 추출"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("PyMuPDF 필요: pip install PyMuPDF")

        doc_name = pdf_path.name
        doc_date = self._parse_date_from_filename(doc_name)
        doc_type = self._get_doc_type(pdf_path)

        paragraphs = []
        doc = fitz.open(pdf_path)

        for page_num, page in enumerate(doc, 1):
            text = page.get_text()
            # 문단 분리 (빈 줄 기준)
            for para_text in self._split_paragraphs(text):
                if len(para_text.strip()) > 20:  # 최소 길이
                    paragraphs.append(Paragraph(
                        text=para_text.strip(),
                        page_num=page_num,
                        doc_name=doc_name,
                        doc_date=doc_date,
                        doc_type=doc_type,
                    ))

        doc.close()
        return paragraphs

    def _parse_date_from_filename(self, filename: str) -> date:
        """파일명에서 날짜 추출: LG전자_20230109_... → 2023-01-09"""
        match = re.search(r"_(\d{8})_", filename)
        if match:
            date_str = match.group(1)
            return date(
                int(date_str[:4]),
                int(date_str[4:6]),
                int(date_str[6:8])
            )
        return date.today()

    def _get_doc_type(self, path: Path) -> str:
        """문서 타입 판별"""
        if "consensus" in str(path):
            return "consensus"
        elif "dart" in str(path):
            return "dart"
        return "unknown"

    def _split_paragraphs(self, text: str) -> List[str]:
        """텍스트를 문단으로 분리"""
        # 연속된 줄바꿈으로 분리
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.replace("\n", " ").strip() for p in paragraphs]

    def filter_tv_paragraphs(self, paragraphs: List[Paragraph]) -> List[Paragraph]:
        """TV 관련 문단만 필터링"""
        tv_keywords = self.keywords.get("tv_identifiers", [])
        exclude_keywords = self.keywords.get("exclude_only", [])

        filtered = []
        for para in paragraphs:
            text = para.text

            # TV 키워드 포함 여부
            has_tv = any(kw in text for kw in tv_keywords)

            # 제외 키워드만 있는지 확인
            has_exclude = any(kw in text for kw in exclude_keywords)

            # TV 키워드가 있으면 포함
            if has_tv:
                filtered.append(para)
            # TV 키워드 없이 제외 키워드만 있으면 제외
            elif has_exclude:
                continue

        return filtered


class DocumentProcessor:
    """문서 일괄 처리"""

    def __init__(self, layer2_dir: Path):
        self.layer2_dir = layer2_dir
        self.keywords_path = layer2_dir / "keywords.yaml"
        self.extractor = PDFExtractor(self.keywords_path)

    def process_all_documents(self) -> Generator[Paragraph, None, None]:
        """모든 PDF 처리"""
        for doc_type in ["consensus", "dart"]:
            doc_dir = self.layer2_dir / doc_type
            if not doc_dir.exists():
                continue

            for pdf_path in sorted(doc_dir.glob("*.pdf")):
                try:
                    paragraphs = self.extractor.extract_paragraphs(pdf_path)
                    tv_paragraphs = self.extractor.filter_tv_paragraphs(paragraphs)
                    for para in tv_paragraphs:
                        yield para
                except Exception as e:
                    print(f"Error processing {pdf_path.name}: {e}")

    def get_document_list(self) -> List[dict]:
        """문서 목록 조회"""
        docs = []
        for doc_type in ["consensus", "dart"]:
            doc_dir = self.layer2_dir / doc_type
            if not doc_dir.exists():
                continue

            for pdf_path in sorted(doc_dir.glob("*.pdf")):
                doc_date = self.extractor._parse_date_from_filename(pdf_path.name)
                docs.append({
                    "name": pdf_path.name,
                    "type": doc_type,
                    "date": doc_date.isoformat(),
                    "path": str(pdf_path),
                })
        return docs
