"""Structured output contract for the intent classifier."""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


class Period(BaseModel):
    """Analysis period extracted from the user query."""

    year: Optional[int] = Field(None, description="Year, e.g. 2025")
    quarter: Optional[Union[int, List[int]]] = Field(None, description="Quarter number 1-4")
    month: Optional[Union[int, List[int]]] = Field(None, description="Month number 1-12")


class ExtractedEntities(BaseModel):
    """Entities passed to downstream SQL, Graph-RAG, and analysis agents."""

    period: Optional[Period] = None
    region: Optional[Union[str, List[str]]] = None
    company: Optional[str] = Field(None, description="Company code, usually LGE")
    kpi_focus: Optional[str] = Field(None, description="Primary KPI, e.g. 매출, 영업이익, 판매량")
    drivers: Optional[List[str]] = Field(None, description="Mentioned drivers such as 물류비 or 패널원가")


class IntentClassification(BaseModel):
    """Minimal routing contract for the five-agent architecture."""

    service_type: Literal["DataQA", "ReportGeneration"]
    analysis_mode: Optional[Literal["descriptive", "diagnostic"]] = Field(
        None,
        description="Required when service_type is DataQA.",
    )
    report_type: Optional[
        Literal[
            "PerformanceSummary",
            "KPIDiagnosis",
            "DriverDeepDive",
            "RiskMonitoring",
        ]
    ] = Field(None, description="Required when service_type is ReportGeneration.")
    data_source: Optional[Literal["internal", "external", "hybrid"]] = Field(
        "internal",
        description="Routing hint for descriptive DataQA.",
    )
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Brief classification rationale.")
    clarifying_question: Optional[str] = Field(
        None,
        description="Set when confidence is below 0.7 or essential slots are ambiguous.",
    )


# Backward-compatible alias used by the classifier implementation.
IntentResult = IntentClassification
