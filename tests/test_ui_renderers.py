"""Smoke tests for Streamlit HTML renderers."""

from dataclasses import dataclass, field
import unittest

from ui.analysis_result import build_diagnostic_current_result, build_diagnostic_result_html


@dataclass
class FakeKPIChange:
    kpi_name: str = "영업이익"
    current_period: str = "2025 Q3"
    current_value: float = 100
    qoq_previous_value: float = 120
    yoy_previous_value: float = 130
    qoq_change_percent: float = -16.7
    yoy_change_percent: float = -23.1
    sql_query: str = "SELECT 1"


@dataclass
class FakeHypothesis:
    id: str = "panel_price"
    factor: str = "패널 가격"
    confidence: float = 0.8
    driver_id: str = "panel_price"
    reasoning: str = "정합한 방향의 변동이 관찰되었습니다."
    validation_data: dict = field(
        default_factory=lambda: {
            "method": "candidate_selection",
            "alignment_type": "both",
            "alignment_type_kr": "QoQ와 YoY 모두 정합",
            "aligned_qoq": True,
            "aligned_yoy": True,
            "qoq_delta_pct": 12.0,
            "yoy_delta_pct": 8.0,
        }
    )


@dataclass
class FakeEvent:
    event_name: str = "LCD 패널 공급 제약"
    event_category: str = "supply"
    total_score: float = 0.7
    event_id: str = "event_1"
    score_breakdown: dict = field(
        default_factory=lambda: {
            "final": 0.7,
            "text_similarity": 0.6,
            "graph_score": 0.5,
            "direction_bonus": 0.15,
        }
    )
    sources: list = field(default_factory=lambda: [{"title": "Market report", "url": "https://example.com"}])


@dataclass
class FakeDiagnosticPayload:
    kpi_change: FakeKPIChange = field(default_factory=FakeKPIChange)
    hypotheses: list = field(default_factory=lambda: [FakeHypothesis()])
    validated: list = field(default_factory=lambda: [FakeHypothesis()])
    matched_events: dict = field(default_factory=lambda: {"panel_price": [FakeEvent()]})
    summary_result: dict = field(default_factory=lambda: {"summary": "요약입니다.", "sources": []})
    validation_result: dict = field(
        default_factory=lambda: {
            "natural_language_summary": "후보 요인이 확인되었습니다.",
            "rejected_hypotheses": [],
            "analysis_plan": {},
        }
    )
    analysis_plan: dict = field(
        default_factory=lambda: {
            "total_hypotheses": 1,
            "passed_count": 1,
            "threshold": 1.0,
            "data_availability": {"driver_results": []},
        }
    )
    kpi_id: str = "operating_profit"


class DiagnosticRendererTests(unittest.TestCase):
    def test_build_diagnostic_result_html_renders_main_sections(self):
        html = build_diagnostic_result_html(
            "<script>bad()</script> 2025년 3분기 영업이익",
            FakeDiagnosticPayload(),
        )

        self.assertIn("analysis-result-box", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertIn("KPI 변동 확인", html)
        self.assertIn("가설 검증 및 분석 해석", html)
        self.assertIn("LCD 패널 공급 제약", html)

    def test_build_diagnostic_current_result_saves_compact_counts(self):
        state = build_diagnostic_current_result(
            "query",
            {"analysis_mode": "diagnostic"},
            FakeDiagnosticPayload(),
        )

        self.assertEqual(state["hypotheses"], 1)
        self.assertEqual(state["validated"], 1)
        self.assertEqual(state["matched_events"], 1)
        self.assertEqual(state["kpi_change"]["kpi_name"], "영업이익")


if __name__ == "__main__":
    unittest.main()
