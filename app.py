"""
LG Electronics HE Business Intelligence - Multi-Agent System UI
"""

import streamlit as st
import sys
import os
import time
import markdown
from datetime import datetime

# 경로 설정 (Docker 및 로컬 환경 모두 지원)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# .env 로드 (python-dotenv 사용 가능하면 사용, 아니면 수동 로드)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
except ImportError:
    env_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

from config.settings import get_settings

SETTINGS = get_settings()
ERP_DB_PATH = str(SETTINGS.erp_db_path)

# Import agents/services
from agents.orchestrator import Orchestrator
from services import AnalysisService, IntentService
from ui import (
    build_diagnostic_current_result,
    build_diagnostic_result_html,
    display_chat_messages,
    display_vector_search_results,
    load_global_styles,
)

# Knowledge Graph Visualizer
try:
    from knowledge_graph.visualizer import KGVisualizer
    KG_VISUALIZER_AVAILABLE = True
except ImportError:
    KG_VISUALIZER_AVAILABLE = False


# 페이지 설정
st.set_page_config(
    page_title="LG HE BI System",
    page_icon="*",
    layout="wide"
)

# Global UI styles
load_global_styles()


def init_session_state():
    """세션 상태 초기화"""
    if 'orchestrator' not in st.session_state:
        st.session_state.orchestrator = Orchestrator(db_path=ERP_DB_PATH)
    if 'intent_service' not in st.session_state:
        st.session_state.intent_service = IntentService(
            fallback_classifier=st.session_state.orchestrator._simple_classify
        )
    if 'analysis_service' not in st.session_state:
        st.session_state.analysis_service = AnalysisService(db_path=ERP_DB_PATH)
    if 'history' not in st.session_state:
        st.session_state.history = []
    if 'current_result' not in st.session_state:
        st.session_state.current_result = None
    # Chat interface state
    if 'chat_messages' not in st.session_state:
        st.session_state.chat_messages = []  # [{role, content, analysis_html, timestamp}]
    if 'is_processing' not in st.session_state:
        st.session_state.is_processing = False
    if 'pending_query' not in st.session_state:
        st.session_state.pending_query = None
    if 'debug_mode' not in st.session_state:
        st.session_state.debug_mode = False


def classify_intent(query: str) -> dict:
    """Intent 분류"""
    history = st.session_state.get("chat_messages", [])
    result = st.session_state.intent_service.classify(query, history=history)

    if result.get("classification_error") and st.session_state.get("debug_mode", False):
        st.warning(f"Intent Classifier fallback: {result['classification_error']}")

    return result


def generate_natural_response(query: str, data: list, source: str = "sql") -> str:
    """SQL/Graph 결과를 자연어로 변환"""
    if not data:
        return "조회 결과가 없습니다."

    try:
        from openai import OpenAI
        client = OpenAI()

        # 데이터를 간단한 텍스트로 변환
        if isinstance(data, list) and len(data) > 0:
            # 최대 5개 행만 포함
            data_preview = data[:5]
            data_str = "\n".join([str(row) for row in data_preview])
            if len(data) > 5:
                data_str += f"\n... 외 {len(data) - 5}개 행"
        else:
            data_str = str(data)

        prompt = f"""사용자 질문: {query}

조회된 데이터:
{data_str}

위 데이터를 바탕으로 사용자의 질문에 대해 자연스러운 한국어 문장으로 답변해주세요.
- 핵심 수치와 정보를 포함하세요
- 간결하게 2-3문장으로 작성하세요
- 데이터가 없으면 "해당 데이터가 없습니다"라고 답변하세요"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        # LLM 호출 실패 시 기본 메시지
        if isinstance(data, list) and data:
            return f"총 {len(data)}개의 결과를 찾았습니다."
        return "데이터를 조회했습니다."


def run_analysis(query: str):
    """분석 실행 및 결과 표시 (Unified Box Style)"""

    # Progress indicator (minimal) - 분석 중에만 표시
    progress = st.progress(0)
    status = st.empty()

    # Step 1: Intent Classification
    status.text("Analyzing...")
    progress.progress(10)

    intent_result = classify_intent(query)
    time.sleep(0.2)
    progress.progress(20)

    # Intent 타입 확인
    service_type = intent_result.get("service_type", "").lower().replace("-", "_").replace(" ", "_")
    raw_result = intent_result.get("raw_result", {})

    # Report Generation 처리
    if service_type == "report_generation" or raw_result.get("intent") == "Report Generation":
        report_type = intent_result.get("report_type") or "integrated_kpi_report"

        # entities는 intent_result에서 직접 가져옴 (raw_result가 없을 수 있음)
        entities = intent_result.get("extracted_entities", {}) or {}
        period = entities.get("period", {}) or {}

        # 기간 정보 추출 (없으면 기본값)
        year = period.get("year", 2024)
        quarter = period.get("quarter", 4)
        # progress/status 정리
        progress.empty()
        status.empty()

        generate_report(
            report_type=report_type,
            year=year,
            quarter=quarter
        )
        return

    # Out-of-Scope 또는 Ambiguous 처리
    if service_type in ["out_of_scope", "ambiguous"]:
        status.empty()
        progress.empty()

        # 응답 메시지 가져오기
        if service_type == "out_of_scope":
            response_message = raw_result.get("response_message",
                "죄송합니다. 해당 데이터는 현재 제공되지 않습니다. LG전자 HE사업부 관련 데이터만 조회 가능합니다.")
        else:  # ambiguous
            response_message = raw_result.get("clarifying_question",
                "질문을 좀 더 구체적으로 해주시겠어요? 예: '2025년 Q3 매출이 얼마야?' 또는 '매출 변동 원인 분석해줘'")

        # 추천 질문
        recommended = raw_result.get("recommended_questions", [
            "2025년 Q3 매출이 얼마야?",
            "2025년 Q3 매출 변동 원인 분석해줘",
            "OLED TV 판매량 추이 알려줘"
        ])

        # 응답 박스 표시
        recommendations_html = "".join([f'<li style="margin: 4px 0; color: #6B7280;">{q}</li>' for q in recommended[:3]])
        box_html = f'''<div class="analysis-result-box">
            <div class="box-query">{query}</div>
            <div class="box-summary" style="color: #374151;">
                {response_message}
                <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #E5E7EB;">
                    <div style="font-size: 13px; font-weight: 600; color: #6B7280; margin-bottom: 8px;">이런 질문은 어떠세요?</div>
                    <ul style="margin: 0; padding-left: 20px; font-size: 14px;">{recommendations_html}</ul>
                </div>
            </div>
        </div>'''
        st.markdown(box_html, unsafe_allow_html=True)
        return

    # 분석 모드에 따른 처리
    analysis_mode = intent_result.get("analysis_mode", "descriptive")

    if analysis_mode == "diagnostic":
        status.text("Running diagnostic analysis...")
        payload = st.session_state.analysis_service.run_diagnostic(
            query,
            intent_result,
            debug=st.session_state.get("debug_mode", False)
        )
        progress.progress(90)

        for warning in payload.warnings:
            st.warning(warning)

        status.empty()
        progress.empty()

        kg_visualizer_cls = KGVisualizer if KG_VISUALIZER_AVAILABLE else None
        box_html = build_diagnostic_result_html(
            query=query,
            payload=payload,
            debug_mode=st.session_state.get("debug_mode", False),
            kg_visualizer_cls=kg_visualizer_cls,
        )
        st.markdown(box_html, unsafe_allow_html=True)

        st.session_state.current_result = build_diagnostic_current_result(
            query=query,
            intent_result=intent_result,
            payload=payload,
        )

    else:
        status.text("Searching...")

        progress.progress(40)

        search_payload = st.session_state.analysis_service.run_descriptive(query, intent_result)
        result = search_payload.result
        source = search_payload.source
        source_label = search_payload.source_label

        if st.session_state.get("debug_mode", False):
            st.json({
                "search_routing": search_payload.debug_info,
                "source": source,
                "success": result.get("success"),
                "error": result.get("error"),
                "query": result.get("query")
            })

        progress.progress(70)

        # Clear progress
        status.empty()
        progress.empty()

        # Results
        summary_text = ""  # Initialize for both success and error cases
        box_html = ""

        if result.get("success") and result.get("data"):
            data = result["data"]

            # Details HTML 빌드
            details_html = f'<div class="detail-item"><strong>Data Source:</strong> {source_label}</div>'
            query_used = result.get("query", "")
            if query_used:
                query_escaped = query_used.replace('<', '&lt;').replace('>', '&gt;')
                details_html += f'<div class="detail-item"><strong>Query:</strong></div>'
                details_html += f'<pre style="background: #F7F7F5; padding: 12px; border-radius: 4px; font-size: 12px; overflow-x: auto; margin: 8px 0;">{query_escaped}</pre>'

            # 결과를 자연어로 변환
            summary_text = generate_natural_response(query, data, source)

            # 박스 HTML (단일 렌더링)
            box_html = f'<div class="analysis-result-box"><div class="box-query">{query}</div><div class="box-summary">{summary_text}</div><details class="box-details"><summary>View query details</summary><div class="details-content">{details_html}</div></details></div>'
            st.markdown(box_html, unsafe_allow_html=True)

            # 데이터 테이블은 박스 외부에 표시 (Streamlit 위젯)
            if source == "vector":
                display_vector_search_results(data)
            elif isinstance(data, list) and data:
                import pandas as pd
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True)
            else:
                st.json(data)
        else:
            error_msg = result.get('error', 'Unknown error')
            summary_text = f"Search failed: {error_msg}"
            box_html = f'<div class="analysis-result-box"><div class="box-query">{query}</div><div class="box-summary" style="color: #EB5757;">{summary_text}</div></div>'
            st.markdown(box_html, unsafe_allow_html=True)

        st.session_state.current_result = {
            "query": query,
            "intent": intent_result,
            "data": result.get("data"),
            "source": source,
            "sql": result.get("query") if source == "sql" else None,
            "analysis_html": box_html,
            "summary": summary_text
        }

    # 히스토리에 추가
    st.session_state.history.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "mode": analysis_mode
    })


def generate_report(
    report_type: str,
    year: int,
    quarter: int
):
    """
    보고서 자동 생성

    Args:
        report_type: 보고서 유형
        year: 연도
        quarter: 분기
    """
    try:
        from agents.report import ReportAgent, ReportType, ReportRequest

        # ReportRequest 생성
        request = ReportRequest(
            report_type=ReportType.from_value(report_type),
            year=year,
            quarter=quarter
        )

        # 보고서 생성
        with st.spinner(f"보고서 생성 중... ({year}년 Q{quarter})"):
            agent = ReportAgent(db_path=ERP_DB_PATH)
            result = agent.generate(request)

        if result.get("error"):
            st.error(f"보고서 생성 실패: {result['error']}")
            return

        # 결과 표시
        report_title = result.get("title", "보고서")
        markdown_content = result.get("markdown", "")

        # 채팅에 보고서 추가
        st.session_state.chat_messages.append({
            'role': 'assistant',
            'content': f"**{report_title}** 보고서가 생성되었습니다.",
            'analysis_html': f'<div class="report-content">{markdown.markdown(markdown_content)}</div>',
            'data': result.get('sections'),
            'source': 'report',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        # 보고서 다운로드 버튼
        st.download_button(
            label="보고서 다운로드 (Markdown)",
            data=markdown_content,
            file_name=f"{report_type}_{year}Q{quarter}.md",
            mime="text/markdown"
        )

        st.rerun()

    except ImportError as e:
        st.error(f"ReportAgent 모듈을 불러올 수 없습니다: {e}")
    except Exception as e:
        st.error(f"보고서 생성 중 오류 발생: {e}")


def main():
    """메인 함수"""
    init_session_state()

    # 사이드바 (Notion style - minimal icons)
    with st.sidebar:
        st.markdown("### System Status")

        # 시스템 상태 (텍스트 기반, 이모지 없음)
        st.markdown('<div style="font-size: 13px; color: #37352F;">', unsafe_allow_html=True)
        st.markdown("Orchestrator: Ready", unsafe_allow_html=True)
        st.markdown("SQL Tool: Ready", unsafe_allow_html=True)

        # Neo4j 연결 확인
        try:
            from agents.tools.graph_executor import GraphExecutor
            graph = GraphExecutor()
            result = graph.execute("RETURN 1 as test")
            if result.success:
                st.markdown("Neo4j: Connected", unsafe_allow_html=True)
            else:
                st.markdown('<span style="color: #9B9A97;">Neo4j: Not connected</span>', unsafe_allow_html=True)
        except:
            st.markdown('<span style="color: #9B9A97;">Neo4j: Not connected</span>', unsafe_allow_html=True)

        st.markdown("Intent Routing: Ready", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("---")

        # 예시 질문
        st.markdown("### Example Queries")

        example_queries = [
            "2024년 4분기 북미 영업이익이 왜 감소했어?",
            "2025년 Q3 매출 변동 원인 분석해줘",
            "2024년 4분기 총 매출은 얼마야?",
            "유럽 지역 원가 현황 알려줘",
            "최근 물류 관련 이벤트 알려줘",
            "관세 정책 관련 이슈가 뭐가 있어?",
        ]

        for eq in example_queries:
            if st.button(eq, key=f"example_{eq[:20]}", use_container_width=True):
                st.session_state.example_query = eq
                st.rerun()

        st.markdown("---")

        # 히스토리
        st.markdown("### Query History")
        if st.session_state.history:
            for item in st.session_state.history[-5:]:
                st.caption(f"{item['timestamp'][:10]} - {item['query'][:25]}...")
        else:
            st.caption("No queries yet")

        # 자동 보고서 생성
        st.markdown("---")
        st.markdown("### Integrated KPI Report")

        col_year, col_quarter = st.columns(2)
        with col_year:
            report_year = st.selectbox("연도", [2025, 2024, 2023], index=1, key="report_year")
        with col_quarter:
            report_quarter = st.selectbox("분기", [1, 2, 3, 4], index=3, key="report_quarter")

        if st.button("통합 KPI 보고서 생성", use_container_width=True, type="primary"):
            generate_report(
                report_type="integrated_kpi_report",
                year=report_year,
                quarter=report_quarter
            )

        # 채팅 기록 초기화 버튼
        st.markdown("---")
        if st.button("Clear Chat", use_container_width=True):
            st.session_state.chat_messages = []
            st.session_state.is_processing = False
            st.session_state.pending_query = None
            st.rerun()

        # 진단 옵션
        st.markdown("---")
        st.markdown("### Diagnostics")
        st.session_state.debug_mode = st.checkbox(
            "분석 과정 상세 정보",
            value=st.session_state.debug_mode,
            help="분석 과정의 상세 정보를 표시합니다"
        )

    # 메인 영역 - Chat Interface with content area
    st.markdown('<div class="main-content-area">', unsafe_allow_html=True)
    st.markdown('<p class="main-header">LG HE Business Intelligence</p>', unsafe_allow_html=True)

    # Chat message display area (shows previous conversations)
    chat_container = st.container()
    with chat_container:
        display_chat_messages()

    # Process pending query - show results here
    if st.session_state.is_processing and st.session_state.pending_query:
        query_to_process = st.session_state.pending_query
        st.session_state.pending_query = None

        # Run analysis with unified result display
        run_analysis(query_to_process)

        # Get the summary from current_result if available
        summary_text = "Analysis completed."
        if st.session_state.current_result:
            result = st.session_state.current_result
            if isinstance(result, dict):
                if result.get('summary'):
                    summary_text = result.get('summary', summary_text)

        # Add assistant message to chat for history (with full HTML and data)
        current = st.session_state.current_result or {}
        st.session_state.chat_messages.append({
            'role': 'assistant',
            'content': summary_text,
            'analysis_html': current.get('analysis_html', ''),
            'data': current.get('data'),
            'source': current.get('source'),
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        st.session_state.is_processing = False

    st.markdown('</div>', unsafe_allow_html=True)

    # Fixed Input area at bottom (Notion AI style)
    st.markdown('<div class="chat-input-area">', unsafe_allow_html=True)

    # 예시 질문이 선택되었으면 적용
    default_query = st.session_state.get("example_query", "")

    col1, col2 = st.columns([9, 1])

    with col1:
        query = st.text_input(
            "질문 입력",
            value=default_query,
            placeholder="비즈니스 데이터에 대해 질문하세요...",
            key="query_input",
            label_visibility="collapsed"
        )

    with col2:
        analyze_button = st.button("Send", type="primary", use_container_width=True)

    # 예시 질문 상태 초기화
    if "example_query" in st.session_state:
        del st.session_state.example_query

    st.markdown('</div>', unsafe_allow_html=True)

    # Handle submission
    if analyze_button and query:
        # Add user message to chat
        st.session_state.chat_messages.append({
            'role': 'user',
            'content': query,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        # Store the query for processing
        st.session_state.pending_query = query
        st.session_state.is_processing = True
        st.rerun()

    elif analyze_button and not query:
        st.warning("Please enter a question.")


if __name__ == "__main__":
    main()
