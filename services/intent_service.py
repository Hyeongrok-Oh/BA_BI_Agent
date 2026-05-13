"""Stable app-facing adapter for intent classification."""

from typing import Any, Callable, Dict, Iterable, List, Optional


IntentFallback = Callable[[str], Dict[str, Any]]


def _slug(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text.lower().replace("-", "_").replace(" ", "_")


def _normalize_service_type(value: Any) -> str:
    normalized = _slug(value, "data_qa")
    return {
        "dataqa": "data_qa",
        "data_qa": "data_qa",
        "reportgeneration": "report_generation",
        "report_generation": "report_generation",
        "out_of_scope": "out_of_scope",
        "ambiguous": "ambiguous",
    }.get(normalized, normalized)


def _normalize_report_type(value: Any) -> str:
    normalized = _slug(value, "")
    return {
        "performancesummary": "performance_summary",
        "kpidiagnosis": "kpi_diagnosis",
        "driverdeepdive": "driver_deep_dive",
        "riskmonitoring": "risk_monitoring",
    }.get(normalized, normalized)


def _normalize_data_source(value: Any) -> str:
    normalized = _slug(value, "internal_data")
    return {
        "internal": "internal_data",
        "external": "external_data",
        "hybrid": "hybrid_data",
    }.get(normalized, normalized)


def _plain_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def _is_event_query(query: str, sub_intent: str) -> bool:
    event_keywords = ["뉴스", "이벤트", "사건", "동향", "트렌드", "이슈", "최근", "요즘"]
    return sub_intent == "external_data" and any(keyword in query for keyword in event_keywords)


def normalize_intent_result(raw_result: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Normalize classifier/fallback output to the app's routing contract."""

    raw_result = raw_result or {}

    service_type = _normalize_service_type(raw_result.get("service_type") or raw_result.get("intent"))
    analysis_mode = _slug(raw_result.get("analysis_mode"), "descriptive")
    sub_intent = _normalize_data_source(raw_result.get("sub_intent") or raw_result.get("data_source"))
    report_type = _normalize_report_type(raw_result.get("report_type"))
    detail_type = _slug(raw_result.get("detail_type"), "")

    entities = _plain_dict(raw_result.get("extracted_entities") or raw_result.get("entities"))

    normalized = {
        "service_type": service_type,
        "analysis_mode": analysis_mode,
        "sub_intent": sub_intent,
        "query": raw_result.get("query") or query,
        "extracted_entities": entities,
        "is_event_query": raw_result.get("is_event_query", _is_event_query(query, sub_intent)),
        "thinking": raw_result.get("thinking", ""),
        "clarifying_question": raw_result.get("clarifying_question"),
        "response_message": raw_result.get("response_message"),
        "recommended_questions": raw_result.get("recommended_questions") or [],
        "confidence": raw_result.get("confidence"),
        "raw_result": raw_result,
    }

    if report_type:
        normalized["report_type"] = report_type
    if detail_type:
        normalized["detail_type"] = detail_type

    return normalized


class IntentService:
    """Lazily call the LLM classifier and fall back to deterministic routing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        fallback_classifier: Optional[IntentFallback] = None,
        classifier_cls: Optional[type] = None,
    ):
        self.api_key = api_key
        self.fallback_classifier = fallback_classifier
        self.classifier_cls = classifier_cls
        self._classifier = None
        self._classifier_import_error = None

    @property
    def classifier(self):
        if self._classifier is not None:
            return self._classifier

        classifier_cls = self.classifier_cls
        if classifier_cls is None:
            try:
                from intent_classifier import IntentClassifier

                classifier_cls = IntentClassifier
            except Exception as exc:
                self._classifier_import_error = exc
                raise

        self._classifier = classifier_cls(self.api_key)
        return self._classifier

    def classify(self, query: str, history: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
        messages = self._build_messages(query, history)

        try:
            raw_result = self.classifier.classify(messages)
            if raw_result.get("error"):
                raise RuntimeError(raw_result["error"])
            result = normalize_intent_result(raw_result, query)
            result["classifier_source"] = "llm"
            return result
        except Exception as exc:
            result = self._fallback(query)
            result["classifier_source"] = "fallback"
            result["classification_error"] = str(exc)
            return result

    def _fallback(self, query: str) -> Dict[str, Any]:
        if self.fallback_classifier:
            return normalize_intent_result(self.fallback_classifier(query), query)

        return normalize_intent_result(
            {
                "service_type": "data_qa",
                "analysis_mode": "descriptive",
                "sub_intent": "internal_data",
                "query": query,
                "extracted_entities": {},
            },
            query,
        )

    def _build_messages(
        self,
        query: str,
        history: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []

        for item in history or []:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": str(content)})

        if not messages or messages[-1].get("content") != query:
            messages.append({"role": "user", "content": query})

        return messages[-8:]
