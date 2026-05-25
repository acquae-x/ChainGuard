import os
from abc import ABC, abstractmethod
from typing import Any


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
        _ = prompt
        _ = kwargs
        if not self.is_configured:
            return MockLLMClient().generate("Qwen API key missing, fallback to mock.")

        raise NotImplementedError(
            "QwenLLMClient 当前仅预留接口。真实 API 调用将在后续版本中接入，"
            "当前MVP不会强制访问网络或真实LLM服务。"
        )


def get_llm_client(mode: str = "mock") -> BaseLLMClient:
    normalized_mode = (mode or "mock").strip().lower()

    if normalized_mode == "qwen":
        qwen_client = QwenLLMClient()
        if qwen_client.is_configured:
            return qwen_client
        return MockLLMClient()

    return MockLLMClient()
