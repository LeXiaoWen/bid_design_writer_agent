from types import SimpleNamespace

from agno.agent import RunContentEvent

from backend.schemas import ApiConfig
from backend.services.llm import run_agent
from backend.services.workbench_llm import CONTEXT_CHARACTER_BUDGET, _build_context_window, _context_characters, _context_usage, _merge_usage


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


def test_context_window_summarizes_old_messages_and_respects_budget():
    messages = [
        SimpleNamespace(role="user" if index % 2 == 0 else "assistant", content=f"消息-{index}: " + "x" * 2_000)
        for index in range(14)
    ]

    summary, recent_messages, updated = _build_context_window("", messages, "当前问题" * 400)

    assert updated is True
    assert "消息-0" in summary
    assert len(recent_messages) < 12
    assert _context_characters(summary, recent_messages, "当前问题" * 400) <= CONTEXT_CHARACTER_BUDGET


def test_context_window_keeps_history_when_under_budget():
    messages = [SimpleNamespace(role="user", content="简短消息")]

    summary, recent_messages, updated = _build_context_window("已有摘要", messages, "当前问题")

    assert updated is False
    assert summary == "已有摘要"
    assert recent_messages == messages


def test_usage_merges_context_estimate_with_provider_tokens():
    usage = _merge_usage(_context_usage(101), {"prompt_tokens": 28, "completion_tokens": 12, "total_tokens": 40})

    assert usage == {
        "context_characters": 101,
        "context_budget": CONTEXT_CHARACTER_BUDGET,
        "context_estimated_tokens": 26,
        "prompt_tokens": 28,
        "completion_tokens": 12,
        "total_tokens": 40,
    }
