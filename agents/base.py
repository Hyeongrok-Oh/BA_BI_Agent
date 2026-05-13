"""
Base classes for Agents and Tools
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import os
import time
import requests
from openai import OpenAI


@dataclass
class ToolResult:
    """Tool 실행 결과"""
    success: bool
    data: Any = None
    error: str = None


@dataclass
class AgentContext:
    """Agent 실행 컨텍스트 (상태 관리)"""
    query: str
    history: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def add_step(self, step_name: str, result: Any):
        """실행 단계 기록"""
        self.history.append({
            "step": step_name,
            "result": result
        })


class BaseTool(ABC):
    """
    Tool 베이스 클래스

    특징:
    - 단일 기능 수행
    - 입력 → 출력 명확
    - 결정권 없음 (Agent가 호출)
    """

    name: str = "base_tool"
    description: str = "Base tool"

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Tool 실행"""
        pass


class BaseAgent(ABC):
    """
    Agent 베이스 클래스

    특징:
    - 자율성 (Autonomy)
    - Planning & Selection
    - 상태 관리 (Context)
    - 협업 가능
    """

    name: str = "base_agent"
    description: str = "Base agent"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.llm = OpenAI(api_key=self.api_key)
        self.tools: List[BaseTool] = []
        self.sub_agents: List['BaseAgent'] = []

    def add_tool(self, tool: BaseTool):
        """Tool 추가"""
        self.tools.append(tool)

    def add_sub_agent(self, agent: 'BaseAgent'):
        """하위 Agent 추가"""
        self.sub_agents.append(agent)

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """이름으로 Tool 찾기"""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def get_sub_agent(self, name: str) -> Optional['BaseAgent']:
        """이름으로 하위 Agent 찾기"""
        for agent in self.sub_agents:
            if agent.name == name:
                return agent
        return None

    def _call_llm(
        self,
        prompt: str,
        system_prompt: str = None,
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens: int = 2000
    ) -> str:
        """LLM 호출 (Agent의 두뇌)

        o1/o3 추론 모델 지원:
        - o1, o1-mini, o1-preview, o3-mini 등
        - system prompt를 user message에 포함
        - temperature 파라미터 미사용
        """
        # o1/o3 추론 모델 여부 확인
        is_reasoning_model = model.startswith("o1") or model.startswith("o3")

        messages = []

        if is_reasoning_model:
            # o1/o3 모델: system prompt를 user message에 포함
            combined_prompt = prompt
            if system_prompt:
                combined_prompt = f"[시스템 지침]\n{system_prompt}\n\n[사용자 요청]\n{prompt}"
            messages.append({"role": "user", "content": combined_prompt})

            # o1/o3 모델용 API 호출 (temperature 없음, max_completion_tokens 사용)
            response = self.llm.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens
            )
        else:
            # 일반 모델 (gpt-4o, gpt-4o-mini 등)
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self.llm.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

        return response.choices[0].message.content.strip()

    def _call_responses_api_sync(
        self,
        prompt: str,
        model: str = "gpt-5.2-pro-2025-12-11",
        max_tokens: int = 2000
    ) -> str:
        """
        OpenAI Responses API 동기식 호출 (gpt-5 계열)

        Args:
            prompt: 프롬프트
            model: 모델 ID
            max_tokens: 최대 토큰 수

        Returns:
            생성된 텍스트
        """
        response = self.llm.responses.create(
            model=model,
            input=prompt
        )
        return response.output_text.strip() if response.output_text else ""

    def _call_responses_api(
        self,
        prompt: str,
        model: str = "o4-mini-deep-research-2025-06-26",
        max_wait_seconds: int = 300,
        poll_interval: int = 5
    ) -> str:
        """
        OpenAI Responses API 호출 (Deep Research 모델용)

        Args:
            prompt: 연구 질문/프롬프트
            model: 모델 ID (o4-mini-deep-research-2025-06-26)
            max_wait_seconds: 최대 대기 시간 (초)
            poll_interval: 폴링 간격 (초)

        Returns:
            생성된 텍스트
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 1. 요청 생성 (background mode)
        payload = {
            "model": model,
            "input": prompt,
            "reasoning": {"summary": "auto"},
            "background": True,
            "tools": [
                {"type": "web_search_preview"}
            ]
        }

        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            raise Exception(f"Responses API 요청 실패: {response.status_code} - {response.text}")

        result = response.json()
        response_id = result.get("id")
        status = result.get("status", "queued")

        print(f"[Responses API] Response ID: {response_id}, Status: {status}")

        # 2. 폴링으로 완료 대기
        start_time = time.time()
        while status in ["queued", "in_progress"]:
            if time.time() - start_time > max_wait_seconds:
                raise Exception(f"Responses API 타임아웃 ({max_wait_seconds}초 초과)")

            time.sleep(poll_interval)

            poll_response = requests.get(
                f"https://api.openai.com/v1/responses/{response_id}",
                headers=headers
            )

            if poll_response.status_code != 200:
                raise Exception(f"폴링 실패: {poll_response.status_code}")

            poll_result = poll_response.json()
            status = poll_result.get("status", "unknown")
            print(f"[Responses API] Polling... Status: {status}")

            if status == "completed":
                # 3. 결과 추출
                output = poll_result.get("output", [])
                for item in output:
                    if item.get("type") == "message":
                        content = item.get("content", [])
                        for c in content:
                            if c.get("type") == "output_text":
                                return c.get("text", "")
                return "(결과 텍스트 없음)"

            elif status == "failed":
                error = poll_result.get("error", {})
                error_code = error.get("code", "")

                # Rate Limit인 경우 재시도
                if error_code == "rate_limit_exceeded":
                    print(f"[Responses API] Rate limit 도달, 10초 후 재시도...")
                    time.sleep(10)
                    # 새로운 요청 생성
                    retry_response = requests.post(
                        "https://api.openai.com/v1/responses",
                        headers=headers,
                        json=payload
                    )
                    if retry_response.status_code == 200:
                        retry_result = retry_response.json()
                        response_id = retry_result.get("id")
                        status = retry_result.get("status", "queued")
                        print(f"[Responses API] 재시도 - Response ID: {response_id}, Status: {status}")
                        continue

                raise Exception(f"Deep Research 실패: {error}")

        return "(결과 없음)"

    @abstractmethod
    def run(self, context: AgentContext) -> Dict[str, Any]:
        """
        Agent 실행

        Args:
            context: 실행 컨텍스트 (쿼리, 히스토리, 메타데이터)

        Returns:
            실행 결과 딕셔너리
        """
        pass
