import json
from unittest.mock import Mock, patch

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


def test_qwen_client_falls_back_when_remote_not_enabled(monkeypatch):
    monkeypatch.delenv("QWEN_REMOTE_ENABLED", raising=False)
    client = QwenLLMClient(api_key="fake-key")

    assert client.is_configured is True
    assert "Mock LLM" in client.generate("hello")


def test_qwen_client_calls_dashscope_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("QWEN_REMOTE_ENABLED", "true")
    response = Mock()
    response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "dashscope-result"}}]}
    ).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)

    with patch("src.llm_client.urllib.request.urlopen", return_value=response) as urlopen:
        result = QwenLLMClient(api_key="fake-key").generate("hello")

    assert result == "dashscope-result"
    assert urlopen.call_args.kwargs["timeout"] == 10


def test_qwen_client_retries_twice_then_falls_back(monkeypatch):
    monkeypatch.setenv("QWEN_REMOTE_ENABLED", "true")
    with patch("src.llm_client.urllib.request.urlopen", side_effect=OSError("offline")) as urlopen, patch("src.llm_client.time.sleep"):
        result = QwenLLMClient(api_key="fake-key").generate("hello")

    assert urlopen.call_count == 3
    assert "Mock LLM" in result


def test_mock_client_returns_stable_text():
    client = MockLLMClient()

    result = client.generate("生成供应链应急建议")

    assert "Mock LLM" in result
    assert "规则输出" in result
