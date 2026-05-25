import pytest

from src.llm_client import MockLLMClient, QwenLLMClient, get_llm_client


def test_get_llm_client_defaults_to_mock():
    client = get_llm_client()

    assert isinstance(client, MockLLMClient)
    assert client.provider == "mock"


def test_get_llm_client_qwen_without_key_falls_back_to_mock(monkeypatch):
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    client = get_llm_client("qwen")

    assert isinstance(client, MockLLMClient)


def test_qwen_client_is_placeholder_when_configured():
    client = QwenLLMClient(api_key="fake-key")

    assert client.is_configured is True
    with pytest.raises(NotImplementedError):
        client.generate("hello")


def test_mock_client_returns_stable_text():
    client = MockLLMClient()

    result = client.generate("生成供应链应急建议")

    assert "Mock LLM" in result
    assert "规则输出" in result
