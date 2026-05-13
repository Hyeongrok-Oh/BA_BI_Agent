"""
Hypothesis Validator - 후보 요인 선별기

역할:
    인과관계를 판단하지 않고, KPI와 Driver의 변화량 및 기대 부호만을 이용하여
    "후보 요인(Candidate Factors)"을 자동으로 선별하고 한국어 설명을 생성한다.

분석 로직:
    A) KPI 변화량 계산 및 임계값 체크
    B) Driver 변화량 계산 및 임계값 체크
    C) 기대 부호(expected_sign)와 실제 부호 정합성 검사
    D) 모든 조건 만족 시 candidate_drivers에 추가

출력:
    1) 구조적 JSON (kpi_summaries)
    2) 자연어 한국어 요약
"""

import os
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..base import BaseAgent, AgentContext


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ThresholdConfig:
    """임계값 설정"""
    type: str = "ratio"  # "ratio" or "abs_point"
    value: float = 0.01  # 1% or 0.01 point


@dataclass
class KPIData:
    """KPI 데이터"""
    id: str
    label: str
    curr_value: float
    qoq_value: float
    yoy_value: float = 0.0
    threshold: ThresholdConfig = field(default_factory=ThresholdConfig)


@dataclass
class DriverData:
    """Driver 데이터"""
    id: str
    label: str
    curr_value: float
    qoq_value: float
    yoy_value: float = 0.0
    threshold: ThresholdConfig = field(default_factory=ThresholdConfig)


@dataclass
class KPIDriverConfig:
    """KPI-Driver 관계 설정"""
    kpi_id: str
    driver_id: str
    expected_sign: str  # "+" or "-"


@dataclass
class CandidateDriver:
    """후보 요인"""
    driver_id: str
    driver_label: str
    driver_delta: float
    driver_delta_pct: float
    expected_sign: str
    aligned: bool
    alignment_reason: str


@dataclass
class KPISummary:
    """KPI 분석 요약"""
    kpi_id: str
    kpi_label: str
    delta: float
    delta_pct: float
    passed_threshold: bool
    threshold_reason: str
    candidate_drivers: List[CandidateDriver] = field(default_factory=list)
    excluded_drivers: List[Dict] = field(default_factory=list)


# =============================================================================
# Driver → ERP 컬럼 매핑
# =============================================================================

DRIVER_ERP_MAPPING = {
    # 원가/구매 관련
    "패널 가격": {"table": "TR_PURCHASE", "column": "PANEL_PRICE_USD", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "패널 원가": {"table": "TR_PURCHASE", "column": "PANEL_PRICE_USD", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "패널원가": {"table": "TR_PURCHASE", "column": "PANEL_PRICE_USD", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "패널": {"table": "TR_PURCHASE", "column": "PANEL_PRICE_USD", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "원자재 가격": {"table": "TR_PURCHASE", "column": "RAW_MATERIAL_INDEX", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "원자재": {"table": "TR_PURCHASE", "column": "RAW_MATERIAL_INDEX", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "dram 가격": {"table": "TR_PURCHASE", "column": "DRAM_PRICE_USD_PER_GB", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "메모리 가격": {"table": "TR_PURCHASE", "column": "DRAM_PRICE_USD_PER_GB", "agg": "AVG", "date_col": "PURCHASE_DATE"},
    "원가": {"table": "TR_PURCHASE", "column": "TOTAL_COGS_USD", "agg": "SUM", "date_col": "PURCHASE_DATE"},
    "제조원가": {"table": "TR_PURCHASE", "column": "TOTAL_COGS_USD", "agg": "SUM", "date_col": "PURCHASE_DATE"},

    # 비용 관련
    "물류비": {"table": "TR_EXPENSE", "column": "LOGISTICS_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},
    "물류 비용": {"table": "TR_EXPENSE", "column": "LOGISTICS_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},
    "마케팅 비용": {"table": "TR_EXPENSE", "column": "MARKETING_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},
    "마케팅비": {"table": "TR_EXPENSE", "column": "MARKETING_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},
    "프로모션 비용": {"table": "TR_EXPENSE", "column": "PROMOTION_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},
    "프로모션비용": {"table": "TR_EXPENSE", "column": "PROMOTION_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},
    "인건비": {"table": "TR_EXPENSE", "column": "LABOR_COST", "agg": "SUM", "date_col": "EXPENSE_DATE"},

    # 매출 관련
    "판매량": {"table": "TR_SALES", "column": "QTY", "agg": "SUM", "date_col": "SALES_DATE"},
    "출하량": {"table": "TR_SALES", "column": "QTY", "agg": "SUM", "date_col": "SALES_DATE"},
    "매출": {"table": "TR_SALES", "column": "REVENUE_USD", "agg": "SUM", "date_col": "SALES_DATE"},
    "webos 수익": {"table": "TR_SALES", "column": "WEBOS_REV_USD", "agg": "SUM", "date_col": "SALES_DATE"},

    # ASP
    "평균판매가": {"table": "TR_SALES", "calc": "ASP", "date_col": "SALES_DATE"},
    "tv 평균판매가": {"table": "TR_SALES", "calc": "ASP", "date_col": "SALES_DATE"},
    "asp": {"table": "TR_SALES", "calc": "ASP", "date_col": "SALES_DATE"},

    # 비중 관련 (JOIN 계산 필요)
    "oled 비중": {"table": "TR_SALES", "calc": "OLED_RATIO", "date_col": "SALES_DATE"},
    "oled비중": {"table": "TR_SALES", "calc": "OLED_RATIO", "date_col": "SALES_DATE"},
    "프리미엄 비중": {"table": "TR_SALES", "calc": "PREMIUM_RATIO", "date_col": "SALES_DATE"},
    "프리미엄비중": {"table": "TR_SALES", "calc": "PREMIUM_RATIO", "date_col": "SALES_DATE"},

    # 외부 요인
    "환율": {"table": "EXT_MACRO", "column": "EXCHANGE_RATE_KRW_USD", "agg": "AVG", "date_col": "DATA_DATE"},
    "금리": {"table": "EXT_MACRO", "column": "INTEREST_RATE", "agg": "AVG", "date_col": "DATA_DATE"},
    "소비심리": {"table": "EXT_MACRO", "column": "CSI_INDEX", "agg": "AVG", "date_col": "DATA_DATE"},
    "해상운임": {"table": "EXT_MARKET", "column": "SCFI_INDEX", "agg": "AVG", "date_col": "DATA_DATE"},
    "관세": {"table": "EXT_TRADE_POLICY", "column": "TARIFF_RATE", "agg": "AVG", "date_col": "DATA_DATE"},
}

# KPI → ERP 매핑
KPI_ERP_MAPPING = {
    "영업이익": {"table": "TR_SALES", "column": "REVENUE_USD", "agg": "SUM", "date_col": "SALES_DATE"},
    "영업이익률": {"table": "TR_SALES", "calc": "OPM", "date_col": "SALES_DATE"},
    "매출": {"table": "TR_SALES", "column": "REVENUE_USD", "agg": "SUM", "date_col": "SALES_DATE"},
    "매출총이익률": {"table": "TR_SALES", "calc": "GPM", "date_col": "SALES_DATE"},
    "평균판매가": {"table": "TR_SALES", "calc": "ASP", "date_col": "SALES_DATE"},
}

# 기본 임계값 설정
DEFAULT_THRESHOLDS = {
    "kpi": {"type": "ratio", "value": 0.01},  # 1%
    "driver": {"type": "ratio", "value": 0.01},  # 1%
}


# =============================================================================
# Main Class
# =============================================================================

class HypothesisValidator(BaseAgent):
    """
    후보 요인 선별기 (Candidate Factor Selector)

    역할:
        인과관계를 판단하지 않고, KPI와 Driver의 변화량 및 기대 부호만을 이용하여
        "후보 요인(Candidate Factors)"을 자동으로 선별한다.

    분석 로직:
        A) KPI 변화량 계산 및 임계값 체크
        B) Driver 변화량 계산 및 임계값 체크
        C) 기대 부호(expected_sign)와 실제 부호 정합성 검사
        D) 모든 조건 만족 시 candidate_drivers에 추가
    """

    name = "hypothesis_validator"
    description = "후보 요인 선별기 - 변화량과 방향성 기반 필터링"

    def __init__(self, api_key: str = None, db_path: str = None):
        from config.settings import get_erp_db_path

        self.api_key = api_key
        self.db_path = db_path or get_erp_db_path()
        self.tools = []
        self.sub_agents = []
        self._whitelist_cache = {}

        # SQLExecutor 초기화
        try:
            from ..tools import SQLExecutor
            self.sql_executor = SQLExecutor(self.db_path)
        except Exception:
            self.sql_executor = None

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    def validate(
        self,
        hypotheses: List,
        kpi_id: str = None,
        period: dict = None,
        verbose: bool = False,
        question_focus: str = "both"
    ) -> dict:
        """
        후보 요인 선별 수행

        Args:
            hypotheses: Hypothesis 객체 리스트
            kpi_id: KPI ID (예: "영업이익")
            period: 분석 기간 {"year": 2024, "quarter": 4}
            verbose: 상세 출력 여부
            question_focus: 질문 초점 ("qoq", "yoy", "both")
                - "qoq": 전분기 대비에 초점 → QoQ 정합성 필수
                - "yoy": 전년 대비에 초점 → YoY 정합성 필수
                - "both": 둘 다 또는 불명확 → 둘 중 하나라도 정합하면 통과

        Returns:
            {
                "period": "2024Q4",
                "kpi_summaries": [...],
                "validated_hypotheses": [...],
                "natural_language_summary": "...",
                "analysis_log": [...]  # 분석 과정 상세 로그
            }
        """
        analysis_log = []
        period_str = f"{period.get('year', 2024)}Q{period.get('quarter', 4)}" if period else "Unknown"

        # =====================================================================
        # Step 0: 분석 시작 로깅
        # =====================================================================
        analysis_log.append({
            "step": "0. 분석 시작",
            "description": f"KPI '{kpi_id}'에 대한 후보 요인 선별을 시작합니다.",
            "inputs": {
                "kpi_id": kpi_id,
                "period": period_str,
                "hypothesis_count": len(hypotheses)
            }
        })

        if verbose:
            print(f"\n{'='*70}")
            print(f"[HypothesisValidator] 후보 요인 선별 시작")
            print(f"  - KPI: {kpi_id}")
            print(f"  - 기간: {period_str}")
            print(f"  - 가설 수: {len(hypotheses)}개")
            print(f"{'='*70}")

        # =====================================================================
        # Step A: KPI 변화량 계산 및 임계값 체크 (QoQ + YoY)
        # =====================================================================
        kpi_data = self._get_kpi_data(kpi_id, period)
        kpi_delta = kpi_data["delta"]
        kpi_qoq_pct = kpi_data.get("qoq_change_pct", kpi_data.get("delta_pct", 0))
        kpi_yoy_pct = kpi_data.get("yoy_change_pct", 0)
        kpi_threshold = DEFAULT_THRESHOLDS["kpi"]["value"] * 100  # 1%

        # QoQ 또는 YoY 중 하나라도 임계값 이상이면 통과
        kpi_passed_threshold = (
            abs(kpi_qoq_pct) >= kpi_threshold or
            abs(kpi_yoy_pct) >= kpi_threshold
        )

        # Primary 결정: 변화가 더 큰 쪽
        if abs(kpi_yoy_pct) > abs(kpi_qoq_pct):
            kpi_delta_pct = kpi_yoy_pct
            kpi_primary = "yoy"
        else:
            kpi_delta_pct = kpi_qoq_pct
            kpi_primary = "qoq"

        kpi_direction = "증가" if kpi_delta_pct > 0 else "감소" if kpi_delta_pct < 0 else "변동없음"

        analysis_log.append({
            "step": "A. KPI 변화량 계산",
            "description": f"KPI '{kpi_id}'의 QoQ/YoY 변화량을 계산합니다.",
            "calculation": {
                "curr_value": kpi_data["curr_value"],
                "qoq_value": kpi_data["qoq_value"],
                "yoy_value": kpi_data["yoy_value"],
                "qoq_pct": f"{kpi_qoq_pct:+.1f}%",
                "yoy_pct": f"{kpi_yoy_pct:+.1f}%",
                "primary": kpi_primary,
                "delta": round(kpi_delta, 2),
                "delta_pct": f"{kpi_delta_pct:+.1f}%",
                "threshold": f"{kpi_threshold}%",
                "passed_threshold": kpi_passed_threshold
            },
            "result": f"KPI 변화율 QoQ {kpi_qoq_pct:+.1f}%, YoY {kpi_yoy_pct:+.1f}% (primary: {kpi_primary}) - 임계값 {kpi_threshold}% {'이상' if kpi_passed_threshold else '미만'}"
        })

        if verbose:
            print(f"\n[Step A] KPI 변화량 계산 (QoQ + YoY)")
            print(f"  - 현재값: {kpi_data['curr_value']:,.0f}")
            print(f"  - QoQ: {kpi_data['qoq_value']:,.0f} → {kpi_qoq_pct:+.1f}%")
            print(f"  - YoY: {kpi_data['yoy_value']:,.0f} → {kpi_yoy_pct:+.1f}%")
            print(f"  - Primary: {kpi_primary} ({kpi_delta_pct:+.1f}%)")
            print(f"  - 임계값: {kpi_threshold}%")
            print(f"  - 통과 여부: {'O' if kpi_passed_threshold else 'X'}")

        # KPI가 임계값 미달이면 분석 대상에서 제외
        if not kpi_passed_threshold:
            analysis_log.append({
                "step": "결론",
                "description": f"KPI '{kpi_id}'의 변화량이 임계값 미만이므로 분석 대상에서 제외합니다.",
                "result": "분석 종료 - 의미있는 변화 없음"
            })

            return {
                "period": period_str,
                "kpi_summaries": [{
                    "kpi_id": kpi_id,
                    "kpi_label": kpi_id,
                    "delta": kpi_delta,
                    "delta_pct": kpi_delta_pct,
                    "passed_threshold": False,
                    "threshold_reason": f"변화율 {kpi_delta_pct:+.1f}%가 임계값 {kpi_threshold}% 미만",
                    "candidate_drivers": [],
                    "excluded_drivers": []
                }],
                "validated_hypotheses": [],
                "natural_language_summary": f"이번 분기 {kpi_id}는 전분기 대비 {abs(kpi_delta_pct):.1f}% {kpi_direction}했으나, 변화폭이 임계값({kpi_threshold}%) 미만이어서 유의미한 변화로 보기 어렵습니다.",
                "analysis_log": analysis_log
            }

        # =====================================================================
        # Step B & C: Driver별 변화량 계산 및 정합성 검사
        # =====================================================================
        whitelist = self._load_whitelist(kpi_id)
        candidate_drivers = []
        excluded_drivers = []
        validated_hypotheses = []

        analysis_log.append({
            "step": "B. Driver 변화량 계산 시작",
            "description": f"{len(hypotheses)}개의 가설에 대해 Driver 변화량을 계산합니다."
        })

        if verbose:
            print(f"\n[Step B & C] Driver별 변화량 계산 및 정합성 검사")
            print("-" * 70)

        for i, hypothesis in enumerate(hypotheses, 1):
            factor = getattr(hypothesis, 'factor', '') or ''
            factor_lower = factor.lower().strip().replace(" ", "")  # 공백 제거 정규화

            # Driver 데이터 조회 (QoQ + YoY)
            driver_data = self._get_driver_data(hypothesis, period)
            driver_delta = driver_data.get("delta", 0)
            driver_qoq_pct = driver_data.get("qoq_change_pct", driver_data.get("delta_pct", 0))
            driver_yoy_pct = driver_data.get("yoy_change_pct", 0)
            driver_threshold = DEFAULT_THRESHOLDS["driver"]["value"] * 100  # 1%

            # QoQ 또는 YoY 중 하나라도 임계값 이상이면 통과
            driver_passed_threshold = (
                abs(driver_qoq_pct) >= driver_threshold or
                abs(driver_yoy_pct) >= driver_threshold
            )

            # Primary 결정: 변화가 더 큰 쪽
            if abs(driver_yoy_pct) > abs(driver_qoq_pct):
                driver_delta_pct = driver_yoy_pct
                driver_primary = "yoy"
            else:
                driver_delta_pct = driver_qoq_pct
                driver_primary = "qoq"

            # Whitelist에서 expected_sign 조회 (공백 제거 + 부분 매칭)
            driver_whitelist = None
            matched_whitelist_key = None
            for key in whitelist:
                key_normalized = key.lower().strip().replace(" ", "")  # 공백 제거 정규화
                if factor_lower in key_normalized or key_normalized in factor_lower:
                    driver_whitelist = whitelist[key]
                    matched_whitelist_key = key
                    if verbose:
                        print(f"    ✓ '{factor}' → whitelist key '{key}' 매칭")
                    break

            # Whitelist에서 찾지 못하면 제외 (기본값 "+" 사용 안함)
            if not driver_whitelist:
                driver_log = {
                    "driver": factor,
                    "excluded_reason": f"Whitelist에 '{factor}' 없음 → 제외"
                }
                excluded_drivers.append({
                    "driver_id": factor,
                    "reason": "no_whitelist",
                    "detail": driver_log["excluded_reason"]
                })
                if verbose:
                    print(f"  [{i}] {factor}: 제외 - Whitelist에 없음")
                continue

            expected_sign = driver_whitelist.get("expected_polarity", "+")

            if verbose:
                print(f"  [{i}] {factor}: Whitelist '{matched_whitelist_key}' 매칭, expected_sign='{expected_sign}'")

            driver_direction = "증가" if driver_delta_pct > 0 else "감소" if driver_delta_pct < 0 else "변동없음"

            driver_log = {
                "driver": factor,
                "matched_whitelist_key": matched_whitelist_key,
                "curr_value": driver_data.get("curr_value", 0),
                "qoq_value": driver_data.get("qoq_value", 0),
                "yoy_value": driver_data.get("yoy_value", 0),
                "qoq_pct": f"{driver_qoq_pct:+.1f}%",
                "yoy_pct": f"{driver_yoy_pct:+.1f}%",
                "primary": driver_primary,
                "delta_pct": f"{driver_delta_pct:+.1f}%",
                "expected_sign": expected_sign,
                "sql_verified": driver_data.get("sql_verified", False)
            }

            # B-1) ERP 매핑 존재 여부 체크
            if not driver_data.get("sql_verified", False):
                driver_log["excluded_reason"] = f"ERP 데이터 매핑 없음 (DRIVER_ERP_MAPPING에 '{factor}' 없음)"
                excluded_drivers.append({
                    "driver_id": factor,
                    "reason": "no_erp_mapping",
                    "detail": driver_log["excluded_reason"],
                    "delta_pct": 0
                })

                if verbose:
                    print(f"  [{i}] {factor}: 제외 - {driver_log['excluded_reason']}")
                continue

            # ERP 매핑된 hypothesis에 validation_data 설정 (필터링 결과와 무관하게 UI 표시용)
            hypothesis.validation_data = {
                **driver_data,
                "method": "candidate_selection",
                "qoq_delta_pct": driver_qoq_pct,
                "yoy_delta_pct": driver_yoy_pct,
                "primary_comparison": driver_primary,
                "kpi_qoq_pct": kpi_qoq_pct,
                "kpi_yoy_pct": kpi_yoy_pct,
                "kpi_primary": kpi_primary
            }

            # B-2) Driver 임계값 체크 (QoQ or YoY)
            driver_log["passed_threshold"] = driver_passed_threshold

            if not driver_passed_threshold:
                driver_log["excluded_reason"] = f"QoQ {driver_qoq_pct:+.1f}%, YoY {driver_yoy_pct:+.1f}% 모두 임계값 {driver_threshold}% 미만"
                excluded_drivers.append({
                    "driver_id": factor,
                    "reason": "threshold",
                    "detail": driver_log["excluded_reason"],
                    "qoq_pct": driver_qoq_pct,
                    "yoy_pct": driver_yoy_pct
                })

                if verbose:
                    print(f"  [{i}] {factor}: 제외 - {driver_log['excluded_reason']}")
                continue

            # C) 이중 정합성 검사 (QoQ + YoY)
            # KPI 방향
            kpi_qoq_up = kpi_qoq_pct > 0
            kpi_yoy_up = kpi_yoy_pct > 0
            # Driver 방향
            driver_qoq_up = driver_qoq_pct > 0
            driver_yoy_up = driver_yoy_pct > 0

            # QoQ 정합성 검사 (필수 조건)
            if expected_sign == "+":
                aligned_qoq = (kpi_qoq_up == driver_qoq_up)
            elif expected_sign == "-":
                aligned_qoq = (kpi_qoq_up != driver_qoq_up)
            else:  # "mixed"
                aligned_qoq = True

            # YoY 정합성 검사 (추가 분류용)
            if expected_sign == "+":
                aligned_yoy = (kpi_yoy_up == driver_yoy_up)
            elif expected_sign == "-":
                aligned_yoy = (kpi_yoy_up != driver_yoy_up)
            else:  # "mixed"
                aligned_yoy = True

            driver_log["aligned_qoq"] = aligned_qoq
            driver_log["aligned_yoy"] = aligned_yoy

            # question_focus에 따른 정합성 필터링
            should_exclude = False
            exclude_reason = ""

            if question_focus == "qoq":
                # QoQ 초점: QoQ 정합성이 반드시 필요
                if not aligned_qoq:
                    should_exclude = True
                    exclude_reason = f"QoQ 정합성 실패 (question_focus=qoq) - KPI QoQ {kpi_qoq_pct:+.1f}%, Driver QoQ {driver_qoq_pct:+.1f}%, expected: {expected_sign}"
            elif question_focus == "yoy":
                # YoY 초점: YoY 정합성이 반드시 필요
                if not aligned_yoy:
                    should_exclude = True
                    exclude_reason = f"YoY 정합성 실패 (question_focus=yoy) - KPI YoY {kpi_yoy_pct:+.1f}%, Driver YoY {driver_yoy_pct:+.1f}%, expected: {expected_sign}"
            else:  # "both" 또는 None
                # 둘 다 또는 불명확: 하나라도 정합하면 통과
                if not aligned_qoq and not aligned_yoy:
                    should_exclude = True
                    exclude_reason = f"QoQ/YoY 모두 정합성 실패 - KPI: QoQ {kpi_qoq_pct:+.1f}%, YoY {kpi_yoy_pct:+.1f}% / Driver: QoQ {driver_qoq_pct:+.1f}%, YoY {driver_yoy_pct:+.1f}%, expected: {expected_sign}"

            if should_exclude:
                driver_log["excluded_reason"] = exclude_reason
                excluded_drivers.append({
                    "driver_id": factor,
                    "reason": f"alignment_{question_focus}",
                    "detail": exclude_reason,
                    "qoq_pct": driver_qoq_pct,
                    "yoy_pct": driver_yoy_pct,
                    "expected_sign": expected_sign,
                    "question_focus": question_focus
                })

                if verbose:
                    print(f"  [{i}] {factor}: 제외 - {exclude_reason[:50]}...")
                    print(f"       KPI: QoQ {kpi_qoq_pct:+.1f}%, YoY {kpi_yoy_pct:+.1f}%")
                    print(f"       Driver: QoQ {driver_qoq_pct:+.1f}%, YoY {driver_yoy_pct:+.1f}%")
                continue

            # 정합성 유형 결정 (3가지)
            if aligned_qoq and aligned_yoy:
                alignment_type = "both"
                alignment_type_kr = "단기·장기 모두 정합성이 있습니다"
                alignment_reason = f"QoQ/YoY 모두 정합 (단기+장기 모두 영향)"
            elif aligned_qoq:
                alignment_type = "qoq_only"
                alignment_type_kr = "단기 변화(QoQ)에서 정합성이 있습니다"
                alignment_reason = f"QoQ 정합, YoY 불일치 (최근 분기에만 영향)"
            else:  # aligned_yoy only
                alignment_type = "yoy_only"
                alignment_type_kr = "장기 변화(YoY)에서 정합성이 있습니다"
                alignment_reason = f"YoY 정합, QoQ 불일치 (장기적 영향)"

            # D) 후보 요인으로 추가
            candidate = CandidateDriver(
                driver_id=factor,
                driver_label=factor,
                driver_delta=driver_delta,
                driver_delta_pct=driver_qoq_pct,  # QoQ 기준
                expected_sign=expected_sign,
                aligned=True,
                alignment_reason=alignment_reason
            )
            candidate_drivers.append(candidate)

            # hypothesis에 validation_data 설정
            hypothesis.validation_status = "validated"
            hypothesis.validated = True
            hypothesis.validation_data = {
                **driver_data,
                "aligned": True,
                "aligned_qoq": aligned_qoq,
                "aligned_yoy": aligned_yoy,
                "alignment_type": alignment_type,
                "alignment_type_kr": alignment_type_kr,
                "expected_sign": expected_sign,
                "alignment_reason": alignment_reason,
                "method": "candidate_selection",
                # QoQ/YoY 정보
                "qoq_delta_pct": driver_qoq_pct,
                "yoy_delta_pct": driver_yoy_pct,
                "kpi_qoq_pct": kpi_qoq_pct,
                "kpi_yoy_pct": kpi_yoy_pct,
            }
            validated_hypotheses.append(hypothesis)

            if verbose:
                qoq_mark = "✓" if aligned_qoq else "✗"
                yoy_mark = "✓" if aligned_yoy else "✗"
                print(f"  [{i}] {factor}: 정합성 확인 - {alignment_type_kr}")
                print(f"       QoQ: {driver_qoq_pct:+.1f}% {qoq_mark}, YoY: {driver_yoy_pct:+.1f}% {yoy_mark}")

            analysis_log.append({
                "step": f"B-{i}. Driver '{factor}' 분석",
                "driver_data": driver_log,
                "result": f"정합성 확인 [{alignment_type}]"
            })

        # =====================================================================
        # Step D: 결과 정리
        # =====================================================================
        analysis_log.append({
            "step": "D. 정합성 검증 완료",
            "description": f"{len(candidate_drivers)}개의 요인에서 정합성이 확인되었습니다.",
            "candidates": [c.driver_id for c in candidate_drivers],
            "excluded_count": len(excluded_drivers)
        })

        if verbose:
            print("-" * 70)
            print(f"\n[Step D] 결과 정리")
            print(f"  - 정합성 확인: {len(candidate_drivers)}개")
            print(f"  - 제외된 요인: {len(excluded_drivers)}개")

        # =====================================================================
        # 자연어 요약 생성
        # =====================================================================
        natural_summary = self._generate_natural_summary(
            kpi_id=kpi_id,
            kpi_qoq_pct=kpi_qoq_pct,
            kpi_yoy_pct=kpi_yoy_pct,
            period_str=period_str,
            candidate_drivers=candidate_drivers,
            excluded_drivers=excluded_drivers,
            validated_hypotheses=validated_hypotheses
        )

        analysis_log.append({
            "step": "E. 자연어 요약 생성",
            "summary": natural_summary
        })

        if verbose:
            print(f"\n[자연어 요약]")
            print(natural_summary)

        # =====================================================================
        # 최종 결과 반환
        # =====================================================================
        kpi_summary = KPISummary(
            kpi_id=kpi_id,
            kpi_label=kpi_id,
            delta=kpi_delta,
            delta_pct=kpi_delta_pct,
            passed_threshold=True,
            threshold_reason=f"변화율 {kpi_delta_pct:+.1f}%가 임계값 {kpi_threshold}% 이상",
            candidate_drivers=candidate_drivers,
            excluded_drivers=excluded_drivers
        )

        return {
            "period": period_str,
            "kpi_summaries": [self._kpi_summary_to_dict(kpi_summary)],
            "validated_hypotheses": validated_hypotheses,
            "natural_language_summary": natural_summary,
            "analysis_log": analysis_log,
            # 호환성을 위한 필드
            "contributions": self._create_contributions(candidate_drivers),
            "rejected_hypotheses": excluded_drivers,
            "analysis_plan": {
                "method": "candidate_selection",
                "kpi_id": kpi_id,
                "kpi_delta_pct": kpi_delta_pct,
                "threshold": DEFAULT_THRESHOLDS["kpi"]["value"] * 100,
                "total_hypotheses": len(hypotheses),
                "passed_count": len(candidate_drivers),
                "rejected_count": len(excluded_drivers)
            }
        }

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _generate_natural_summary(
        self,
        kpi_id: str,
        kpi_qoq_pct: float,
        kpi_yoy_pct: float,
        period_str: str,
        candidate_drivers: List[CandidateDriver],
        excluded_drivers: List[Dict],
        validated_hypotheses: List = None
    ) -> str:
        """자연어 요약 생성"""

        summary_parts = []

        # KPI 변화 설명 (QoQ 기준)
        kpi_direction = "증가" if kpi_qoq_pct > 0 else "감소" if kpi_qoq_pct < 0 else "변동없음"
        summary_parts.append(
            f"이번 분기({period_str}) {kpi_id}는 전분기 대비 {abs(kpi_qoq_pct):.1f}% {kpi_direction}했습니다."
        )

        if not candidate_drivers:
            summary_parts.append(
                "같은 기간 분석된 요인들 중 기대되는 방향성과 일치하는 요인을 찾지 못했습니다."
            )
            if excluded_drivers:
                threshold_excluded = [d for d in excluded_drivers if d.get("reason") == "threshold"]
                alignment_excluded = [d for d in excluded_drivers if d.get("reason") in ("alignment", "alignment_none")]

                if threshold_excluded:
                    names = [d["driver_id"] for d in threshold_excluded[:3]]
                    summary_parts.append(
                        f"변화폭이 작아 제외된 요인: {', '.join(names)}" +
                        (f" 외 {len(threshold_excluded)-3}개" if len(threshold_excluded) > 3 else "")
                    )
                if alignment_excluded:
                    names = [d["driver_id"] for d in alignment_excluded[:3]]
                    summary_parts.append(
                        f"방향성이 맞지 않아 제외된 요인: {', '.join(names)}" +
                        (f" 외 {len(alignment_excluded)-3}개" if len(alignment_excluded) > 3 else "")
                    )
        else:
            # validated_hypotheses에서 validation_data 가져오기
            vd_map = {}
            if validated_hypotheses:
                for h in validated_hypotheses:
                    if h.validation_data:
                        vd_map[h.factor] = h.validation_data

            # 요인 설명
            for i, driver in enumerate(candidate_drivers):
                vd = vd_map.get(driver.driver_label, {})
                driver_qoq_pct = vd.get("qoq_delta_pct", driver.driver_delta_pct)
                alignment_type = vd.get("alignment_type", "both")
                driver_direction = "상승" if driver_qoq_pct > 0 else "하락"
                sign_desc = "양의 관계" if driver.expected_sign == "+" else "음의 관계"

                # alignment_type에 따른 표현
                if alignment_type == "both":
                    alignment_desc = f"전분기 대비로도 전년 대비로도 기대되는 {sign_desc}와 방향이 일치합니다"
                elif alignment_type == "qoq_only":
                    alignment_desc = f"전분기 대비로는 기대되는 {sign_desc}와 방향이 일치합니다"
                else:  # yoy_only
                    alignment_desc = f"전분기 대비로는 반대 방향이지만, 전년 대비로는 정합성이 있습니다"

                summary_parts.append(
                    f"같은 기간 {driver.driver_label}은(는) 전분기 대비 약 {abs(driver_qoq_pct):.1f}% {driver_direction}하여, "
                    f"{alignment_desc}. "
                    f"따라서 {driver.driver_label}은(는) 이번 분기에 검토할 수 있는 요인으로 볼 수 있습니다."
                )

                if i >= 2:  # 상위 3개만 상세 설명
                    remaining = len(candidate_drivers) - 3
                    if remaining > 0:
                        other_names = [d.driver_label for d in candidate_drivers[3:]]
                        summary_parts.append(f"그 외 요인: {', '.join(other_names)}")
                    break

        return "\n".join(summary_parts)

    def _kpi_summary_to_dict(self, summary: KPISummary) -> dict:
        """KPISummary를 dict로 변환"""
        return {
            "kpi_id": summary.kpi_id,
            "kpi_label": summary.kpi_label,
            "delta": summary.delta,
            "delta_pct": summary.delta_pct,
            "passed_threshold": summary.passed_threshold,
            "threshold_reason": summary.threshold_reason,
            "candidate_drivers": [
                {
                    "driver_id": d.driver_id,
                    "driver_label": d.driver_label,
                    "driver_delta": d.driver_delta,
                    "driver_delta_pct": d.driver_delta_pct,
                    "expected_sign": d.expected_sign,
                    "aligned": d.aligned,
                    "alignment_reason": d.alignment_reason
                }
                for d in summary.candidate_drivers
            ],
            "excluded_drivers": summary.excluded_drivers
        }

    def _create_contributions(self, candidate_drivers: List[CandidateDriver]) -> List[dict]:
        """호환성을 위한 contributions 생성"""
        contributions = []
        for d in candidate_drivers:
            contributions.append({
                "factor": d.driver_label,
                "contribution_pct": 0,  # 기여도 계산 제거
                "yoy_change_pct": d.driver_delta_pct,
                "qoq_change_pct": d.driver_delta_pct,
                "expected_sign": d.expected_sign,
                "aligned": d.aligned
            })
        return contributions

    def _get_kpi_data(self, kpi_id: str, period: dict) -> dict:
        """KPI의 현재/전분기/전년동기 데이터 조회"""
        empty_result = {"curr_value": 0, "qoq_value": 0, "yoy_value": 0, "delta": 0, "delta_pct": 0, "qoq_change_pct": 0, "yoy_change_pct": 0}

        if not self.sql_executor:
            return empty_result

        year = period.get("year", 2024) if period else 2024
        quarter = period.get("quarter", 4) if period else 4

        quarter_dates = {
            1: ("01-01", "03-31"),
            2: ("04-01", "06-30"),
            3: ("07-01", "09-30"),
            4: ("10-01", "12-31")
        }

        q_start, q_end = quarter_dates[quarter]
        curr_start = f"{year}-{q_start}"
        curr_end = f"{year}-{q_end}"

        # 전분기 계산 (QoQ)
        if quarter == 1:
            prev_q_start, prev_q_end = quarter_dates[4]
            prev_start = f"{year-1}-{prev_q_start}"
            prev_end = f"{year-1}-{prev_q_end}"
        else:
            prev_q_start, prev_q_end = quarter_dates[quarter - 1]
            prev_start = f"{year}-{prev_q_start}"
            prev_end = f"{year}-{prev_q_end}"

        # 전년 동기 계산 (YoY)
        yoy_start = f"{year-1}-{q_start}"
        yoy_end = f"{year-1}-{q_end}"

        kpi_mapping = KPI_ERP_MAPPING.get(kpi_id, KPI_ERP_MAPPING.get("매출"))
        if not kpi_mapping:
            return empty_result

        table = kpi_mapping["table"]
        date_col = kpi_mapping.get("date_col", "SALES_DATE")
        calc_type = kpi_mapping.get("calc")
        column = kpi_mapping.get("column", "REVENUE_USD")
        agg = kpi_mapping.get("agg", "SUM")

        def build_sql(start_date, end_date):
            if calc_type == "ASP":
                return f"SELECT ROUND(SUM(REVENUE_USD) / NULLIF(SUM(QTY), 0), 2) as value FROM TR_SALES WHERE SALES_DATE BETWEEN '{start_date}' AND '{end_date}'"
            elif calc_type == "OPM" or calc_type == "GPM":
                return f"SELECT {agg}({column}) as value FROM {table} WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'"
            else:
                return f"SELECT {agg}({column}) as value FROM {table} WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'"

        try:
            # 현재 분기
            result_curr = self.sql_executor.execute(build_sql(curr_start, curr_end))
            value_curr = float(result_curr.data.iloc[0, 0] or 0) if result_curr.success and result_curr.data is not None else 0

            # 전분기 (QoQ)
            result_prev = self.sql_executor.execute(build_sql(prev_start, prev_end))
            value_prev = float(result_prev.data.iloc[0, 0] or 0) if result_prev.success and result_prev.data is not None else 0

            # 전년 동기 (YoY)
            result_yoy = self.sql_executor.execute(build_sql(yoy_start, yoy_end))
            value_yoy = float(result_yoy.data.iloc[0, 0] or 0) if result_yoy.success and result_yoy.data is not None else 0

            # QoQ 계산 (전분기 대비)
            qoq_delta = value_curr - value_prev
            qoq_pct = ((qoq_delta / abs(value_prev)) * 100) if value_prev != 0 else 0

            # YoY 계산 (전년 동기 대비)
            yoy_delta = value_curr - value_yoy
            yoy_pct = ((yoy_delta / abs(value_yoy)) * 100) if value_yoy != 0 else 0

            return {
                "curr_value": value_curr,
                "qoq_value": value_prev,
                "yoy_value": value_yoy,
                "delta": qoq_delta,
                "delta_pct": round(qoq_pct, 1),
                "qoq_change_pct": round(qoq_pct, 1),
                "yoy_change_pct": round(yoy_pct, 1)
            }
        except Exception as e:
            return {"curr_value": 0, "qoq_value": 0, "yoy_value": 0, "delta": 0, "delta_pct": 0, "qoq_change_pct": 0, "yoy_change_pct": 0, "error": str(e)}

    def _get_driver_data(self, hypothesis, period: dict) -> dict:
        """Driver의 현재/전분기/전년동기 데이터 조회"""
        empty_result = {"curr_value": 0, "qoq_value": 0, "yoy_value": 0, "delta": 0, "delta_pct": 0, "qoq_change_pct": 0, "yoy_change_pct": 0, "sql_verified": False}

        if not self.sql_executor:
            return empty_result

        driver_info = getattr(hypothesis, 'driver_info', None)
        driver_name_kr = driver_info.name_kr if driver_info and hasattr(driver_info, 'name_kr') else ''
        factor_name = getattr(hypothesis, 'factor', '')
        driver_name = (driver_name_kr or factor_name).lower().strip()

        if not driver_name:
            return empty_result

        erp_mapping = None
        driver_name_normalized = driver_name.lower().strip().replace(" ", "")  # 공백 제거 정규화
        for key, mapping in DRIVER_ERP_MAPPING.items():
            key_normalized = key.lower().strip().replace(" ", "")  # 공백 제거 정규화
            if key_normalized in driver_name_normalized or driver_name_normalized in key_normalized:
                erp_mapping = mapping
                break

        if not erp_mapping:
            return empty_result

        year = period.get("year", 2024) if period else 2024
        quarter = period.get("quarter", 4) if period else 4

        quarter_dates = {
            1: ("01-01", "03-31"),
            2: ("04-01", "06-30"),
            3: ("07-01", "09-30"),
            4: ("10-01", "12-31")
        }

        q_start, q_end = quarter_dates[quarter]
        curr_start = f"{year}-{q_start}"
        curr_end = f"{year}-{q_end}"

        # 전분기 계산
        if quarter == 1:
            prev_q_start, prev_q_end = quarter_dates[4]
            prev_start = f"{year-1}-{prev_q_start}"
            prev_end = f"{year-1}-{prev_q_end}"
        else:
            prev_q_start, prev_q_end = quarter_dates[quarter - 1]
            prev_start = f"{year}-{prev_q_start}"
            prev_end = f"{year}-{prev_q_end}"

        table = erp_mapping["table"]
        date_col = erp_mapping.get("date_col", "SALES_DATE")
        calc_type = erp_mapping.get("calc")

        def build_sql(start_date, end_date):
            if calc_type == "ASP":
                return f"SELECT ROUND(SUM(REVENUE_USD) / NULLIF(SUM(QTY), 0), 2) as value FROM TR_SALES WHERE SALES_DATE BETWEEN '{start_date}' AND '{end_date}'"
            elif calc_type == "OLED_RATIO":
                return f"""SELECT ROUND(100.0 * SUM(CASE WHEN p.DISPLAY_TYPE = 'OLED' THEN s.QTY ELSE 0 END) / NULLIF(SUM(s.QTY), 0), 2) as value
                          FROM TR_SALES s JOIN MD_PRODUCT p ON s.PRODUCT_ID = p.PRODUCT_ID
                          WHERE s.SALES_DATE BETWEEN '{start_date}' AND '{end_date}'"""
            elif calc_type == "PREMIUM_RATIO":
                return f"""SELECT ROUND(100.0 * SUM(CASE WHEN p.IS_PREMIUM = 'Y' THEN s.QTY ELSE 0 END) / NULLIF(SUM(s.QTY), 0), 2) as value
                          FROM TR_SALES s JOIN MD_PRODUCT p ON s.PRODUCT_ID = p.PRODUCT_ID
                          WHERE s.SALES_DATE BETWEEN '{start_date}' AND '{end_date}'"""
            else:
                column = erp_mapping.get("column", "")
                agg = erp_mapping.get("agg", "SUM")
                return f"SELECT {agg}({column}) as value FROM {table} WHERE {date_col} BETWEEN '{start_date}' AND '{end_date}'"

        # YoY 계산용 전년 동기 날짜
        yoy_start = f"{year-1}-{q_start}"
        yoy_end = f"{year-1}-{q_end}"

        column = erp_mapping.get("column", "")

        try:
            # 현재 분기
            result_curr = self.sql_executor.execute(build_sql(curr_start, curr_end))
            value_curr = float(result_curr.data.iloc[0, 0] or 0) if result_curr.success and result_curr.data is not None else 0

            # 전분기 (QoQ)
            result_prev = self.sql_executor.execute(build_sql(prev_start, prev_end))
            value_prev = float(result_prev.data.iloc[0, 0] or 0) if result_prev.success and result_prev.data is not None else 0

            # 전년 동기 (YoY)
            result_yoy = self.sql_executor.execute(build_sql(yoy_start, yoy_end))
            value_yoy = float(result_yoy.data.iloc[0, 0] or 0) if result_yoy.success and result_yoy.data is not None else 0

            # QoQ 계산 (전분기 대비)
            qoq_delta = value_curr - value_prev
            qoq_pct = ((qoq_delta / abs(value_prev)) * 100) if value_prev != 0 else 0

            # YoY 계산 (전년 동기 대비)
            yoy_delta = value_curr - value_yoy
            yoy_pct = ((yoy_delta / abs(value_yoy)) * 100) if value_yoy != 0 else 0

            return {
                "curr_value": value_curr,
                "qoq_value": value_prev,
                "yoy_value": value_yoy,
                "delta": qoq_delta,
                "delta_pct": round(qoq_pct, 1),
                "qoq_change_pct": round(qoq_pct, 1),
                "yoy_change_pct": round(yoy_pct, 1),
                "sql_verified": True,
                "erp_table": table,
                "erp_column": column,
                "period": f"{year}Q{quarter}"
            }
        except Exception as e:
            return {"curr_value": 0, "qoq_value": 0, "yoy_value": 0, "delta": 0, "delta_pct": 0, "qoq_change_pct": 0, "yoy_change_pct": 0, "sql_verified": False, "error": str(e)}

    def _load_whitelist(self, kpi_id: str) -> dict:
        """kpi_driver_whitelist.json에서 해당 KPI의 Driver 정보 로드"""
        if kpi_id in self._whitelist_cache:
            return self._whitelist_cache[kpi_id]

        whitelist_path = os.path.join(
            os.path.dirname(__file__),
            "../../knowledge_graph/schema/kpi_driver_whitelist.json"
        )

        try:
            with open(whitelist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            kpi_data = data.get("whitelists", {}).get(kpi_id, {})
            drivers = kpi_data.get("allowed_drivers", [])

            result = {
                d.get("driver_id", "").lower(): {
                    "expected_polarity": d.get("expected_polarity", "+"),
                    "effect_type": d.get("effect_type", ""),
                    "strength": d.get("strength", "medium"),
                    "rationale": d.get("rationale", "")
                }
                for d in drivers
            }

            self._whitelist_cache[kpi_id] = result
            return result
        except Exception as e:
            print(f"[HypothesisValidator] Whitelist 로드 오류: {e}")
            return {}

    # =========================================================================
    # Agent Interface
    # =========================================================================

    def run(self, context: AgentContext) -> Dict[str, Any]:
        """Agent 실행 인터페이스"""
        hypotheses = context.metadata.get("hypotheses", [])
        kpi_id = context.metadata.get("kpi_id", "영업이익")
        period = context.metadata.get("period", {"year": 2024, "quarter": 4})
        verbose = context.metadata.get("verbose", False)

        result = self.validate(
            hypotheses=hypotheses,
            kpi_id=kpi_id,
            period=period,
            verbose=verbose
        )

        context.add_step("hypothesis_validation", {
            "validated_count": len(result["validated_hypotheses"]),
            "total_count": len(hypotheses)
        })

        return result
