import unittest

from services.intent_service import IntentService, normalize_intent_result


class FailingClassifier:
    def __init__(self, api_key=None):
        pass

    def classify(self, messages):
        raise RuntimeError("classifier unavailable")


class IntentServiceTests(unittest.TestCase):
    def test_normalizes_llm_result_to_app_contract(self):
        result = normalize_intent_result(
            {
                "intent": "Report Generation",
                "analysis_mode": "Diagnostic",
                "sub_intent": "Defined Report",
                "report_type": "Risk Monitoring",
                "extracted_entities": {"period": {"year": 2025, "quarter": 1}},
            },
            "리스크 보고서 만들어줘",
        )

        self.assertEqual(result["service_type"], "report_generation")
        self.assertEqual(result["analysis_mode"], "diagnostic")
        self.assertEqual(result["sub_intent"], "defined_report")
        self.assertEqual(result["report_type"], "risk_monitoring")
        self.assertEqual(result["extracted_entities"]["period"]["year"], 2025)

    def test_falls_back_to_deterministic_classifier(self):
        service = IntentService(
            classifier_cls=FailingClassifier,
            fallback_classifier=lambda query: {
                "service_type": "data_qa",
                "analysis_mode": "descriptive",
                "sub_intent": "internal_data",
                "query": query,
            },
        )

        result = service.classify("매출 알려줘")

        self.assertEqual(result["classifier_source"], "fallback")
        self.assertEqual(result["service_type"], "data_qa")
        self.assertIn("classification_error", result)

    def test_normalizes_minimal_intent_classification_schema(self):
        result = normalize_intent_result(
            {
                "service_type": "DataQA",
                "analysis_mode": "diagnostic",
                "data_source": "hybrid",
                "entities": {"kpi_focus": "영업이익"},
                "confidence": 0.91,
            },
            "영업이익 왜 떨어졌어?",
        )

        self.assertEqual(result["service_type"], "data_qa")
        self.assertEqual(result["analysis_mode"], "diagnostic")
        self.assertEqual(result["sub_intent"], "hybrid_data")
        self.assertEqual(result["extracted_entities"]["kpi_focus"], "영업이익")
        self.assertEqual(result["confidence"], 0.91)

    def test_builds_message_history_without_duplicate_current_query(self):
        service = IntentService(classifier_cls=FailingClassifier)
        messages = service._build_messages(
            "매출 알려줘",
            history=[{"role": "user", "content": "매출 알려줘"}],
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "매출 알려줘")


if __name__ == "__main__":
    unittest.main()
