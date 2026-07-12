import os
import json
import time
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from src.observability import log_event


class BaseLLMClient(ABC):
    """Base interface for future LLM-backed reasoning.

    Current MVP modules still use deterministic rule outputs. This interface is
    reserved so agents, debate, and arbitration can later delegate narrative or
    reasoning generation to an LLM without changing their public contracts.
    """

    provider = "base"

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt."""


class MockLLMClient(BaseLLMClient):
    provider = "mock"

    def generate(self, prompt: str, **kwargs: Any) -> str:
        _ = kwargs
        trimmed = prompt.strip()
        if not trimmed:
            return "Mock LLM：未提供输入，返回默认占位结果。"
        return f"Mock LLM：已接收提示词，当前MVP使用规则输出保持演示稳定。提示摘要：{trimmed[:80]}"


class QwenLLMClient(BaseLLMClient):
    provider = "qwen"

    def __init__(self, api_key: str | None = None, model: str = "qwen-plus") -> None:
        self.api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        self.model = model

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, **kwargs: Any) -> str:
        if not self.is_configured:
            return MockLLMClient().generate("Qwen API key missing, fallback to mock.")

        if os.getenv("QWEN_REMOTE_ENABLED", "false").strip().lower() != "true":
            log_event("qwen_remote_disabled", model=self.model)
            return MockLLMClient().generate(prompt)

        payload = json.dumps(
            {
                "model": kwargs.pop("model", self.model),
                "messages": [{"role": "user", "content": prompt}],
                **kwargs,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        endpoint = os.getenv(
            "DASHSCOPE_API_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        for attempt in range(3):
            try:
                request = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return str(data["choices"][0]["message"]["content"])
            except Exception as error:
                log_event(
                    "qwen_request_failed",
                    model=self.model,
                    attempt=attempt + 1,
                    exception=type(error).__name__,
                )
                if attempt < 2:
                    time.sleep(0.2 * (2**attempt))

        log_event("qwen_fallback_to_mock", model=self.model)
        return MockLLMClient().generate(prompt)



def get_llm_client(mode: str = "mock") -> BaseLLMClient:
    normalized_mode = (mode or "mock").strip().lower()

    if normalized_mode == "qwen":
        qwen_client = QwenLLMClient()
        if qwen_client.is_configured:
            return qwen_client
        return MockLLMClient()

    return MockLLMClient()
