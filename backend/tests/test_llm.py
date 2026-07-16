from agno.agent import RunContentEvent

from backend.schemas import ApiConfig
from backend.services.llm import run_agent


def test_run_agent_reports_streamed_content(monkeypatch):
    class FakeAgent:
        def run(self, prompt, stream=False):
            assert prompt == "测试提示词"
            assert stream is True
            return iter([RunContentEvent(content="第一段"), RunContentEvent(content="第二段")])

    monkeypatch.setattr("backend.services.llm.create_agent", lambda *_: FakeAgent())
    received: list[str] = []

    result = run_agent(
        ApiConfig(api_key="test-key"),
        "测试指令",
        "测试提示词",
        on_delta=received.append,
    )

    assert result == "第一段第二段"
    assert received == ["第一段", "第二段"]
