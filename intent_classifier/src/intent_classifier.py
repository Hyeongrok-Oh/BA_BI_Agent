"""LLM-backed intent classifier with a small structured output contract."""

import json
import os
from typing import Dict, List

from openai import OpenAI

try:
    from intent_classifier.db_schema import DB_SCHEMA_PROMPT
except ImportError:
    from db_schema import DB_SCHEMA_PROMPT

try:
    from .utils.example_selector import ExampleSelector
    from .schemas import IntentResult
except ImportError:
    from src.utils.example_selector import ExampleSelector
    from src.schemas import IntentResult


class IntentClassifier:
    """Classify a user query into the five-agent routing contract."""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API Key is required.")

        self.client = OpenAI(api_key=self.api_key)
        self.example_selector = self._load_example_selector()

    def classify(self, messages: List[Dict[str, str]]) -> Dict:
        """Return a structured IntentClassification dict."""

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        user_query = messages[-1]["content"] if messages else ""
        dynamic_examples = self._select_examples(user_query)

        api_messages = [{"role": "system", "content": self._build_system_prompt(dynamic_examples)}]
        for message in messages[-8:]:
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"} and message.get("content"):
                api_messages.append({"role": message["role"], "content": message["content"]})

        try:
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=api_messages,
                temperature=0,
                response_format=IntentResult,
            )
            return completion.choices[0].message.parsed.model_dump()
        except Exception as exc:
            return {"error": str(exc)}

    def _load_example_selector(self):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_path = os.path.join(base_dir, "data", "few_shot_examples.json")
            return ExampleSelector(data_path)
        except Exception:
            return None

    def _select_examples(self, user_query: str) -> List[Dict]:
        if not self.example_selector:
            return []
        try:
            return self.example_selector.find_diverse_examples(
                user_query,
                k=3,
                ensure_category_diversity=True,
            )
        except Exception:
            return []

    def _build_system_prompt(self, examples: List[Dict]) -> str:
        examples_text = ""
        for idx, example in enumerate(examples, 1):
            examples_text += f"\nExample {idx} ({example.get('category', 'general')})\n"
            examples_text += f"User: {example.get('question', '')}\n"
            examples_text += json.dumps(example.get("answer", {}), ensure_ascii=False, indent=2)
            examples_text += "\n"

        return f"""You are the intent classifier for an LG Electronics HE business intelligence system.

Return only the structured IntentClassification object.

Routing labels:
- service_type = DataQA when the user asks for data, events, or analysis in chat.
- service_type = ReportGeneration when the user asks for a document/report.
- analysis_mode = descriptive for factual lookup: "show", "how much", "trend", "list".
- analysis_mode = diagnostic for "why", "cause", "impact", "reason", "analysis".
- report_type = PerformanceSummary, KPIDiagnosis, DriverDeepDive, or RiskMonitoring.
- data_source = internal for ERP/SQL data, external for events/news/market issues, hybrid for diagnostic KPI analysis.

Entity extraction:
- period: year, quarter, month when present.
- region: Korean region names are allowed. Prefer 북미, 유럽, 아시아, 한국, 글로벌.
- company: use LGE when the user refers to LG전자, LG, 엘지, or 우리.
- kpi_focus: primary KPI such as 매출, 영업이익, 판매량, 평균판매가, OLED비중, 물류비, 마케팅비.
- drivers: mentioned candidate drivers such as 패널원가, 물류비, 환율, 해상운임.

Confidence and clarification:
- Set confidence between 0 and 1.
- If confidence < 0.7 or the report request lacks essential period/KPI scope, set clarifying_question in Korean.
- Do not invent unavailable columns or unsupported data.

ERP schema context:
{DB_SCHEMA_PROMPT}

Dynamic few-shot examples:
{examples_text}
"""
