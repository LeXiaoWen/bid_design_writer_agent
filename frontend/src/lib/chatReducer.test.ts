import assert from "node:assert/strict";
import test from "node:test";

import { applyChatStreamEvent } from "./chatReducer";
import type { ChatStreamEvent, WorkbenchMessage } from "./types";

const now = "2026-07-06T00:00:00.000Z";

function assistantMessage(overrides: Partial<WorkbenchMessage> = {}): WorkbenchMessage {
  return {
    id: "assistant-1",
    conversation_id: "conversation-1",
    role: "assistant",
    content: "",
    status: "streaming",
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

test("message_start inserts one streaming assistant message", () => {
  const event: ChatStreamEvent = {
    event: "message_start",
    data: {
      conversation_id: "conversation-1",
      message_id: "assistant-1",
      user_message_id: "user-1",
      run_id: "run-1",
      model: "deepseek-chat",
      usage: { context_characters: 120, context_estimated_tokens: 30 },
    },
  };

  const messages = applyChatStreamEvent([], event, now);
  const duplicate = applyChatStreamEvent(messages, event, now);

  assert.equal(messages.length, 1);
  assert.equal(messages[0].status, "streaming");
  assert.equal(messages[0].model, "deepseek-chat");
  assert.deepEqual(messages[0].usage, { context_characters: 120, context_estimated_tokens: 30 });
  assert.equal(duplicate.length, 1);
});

test("delta appends streamed content", () => {
  const messages = [assistantMessage({ content: "方案" })];
  const event: ChatStreamEvent = {
    event: "delta",
    data: {
      conversation_id: "conversation-1",
      message_id: "assistant-1",
      delta: "正文",
    },
  };

  const next = applyChatStreamEvent(messages, event, "2026-07-06T00:00:01.000Z");

  assert.equal(next[0].content, "方案正文");
  assert.equal(next[0].updated_at, "2026-07-06T00:00:01.000Z");
});

test("message_done finalizes content and metadata", () => {
  const messages = [assistantMessage({ content: "partial" })];
  const event: ChatStreamEvent = {
    event: "message_done",
    data: {
      conversation_id: "conversation-1",
      message_id: "assistant-1",
      status: "completed",
      finish_reason: "stop",
      usage: { total_tokens: 12 },
      content: "final",
    },
  };

  const next = applyChatStreamEvent(messages, event, "2026-07-06T00:00:02.000Z");

  assert.equal(next[0].content, "final");
  assert.equal(next[0].status, "completed");
  assert.equal(next[0].finish_reason, "stop");
  assert.deepEqual(next[0].usage, { total_tokens: 12 });
});

test("message_done preserves interrupted status", () => {
  const messages = [assistantMessage({ content: "partial" })];
  const event: ChatStreamEvent = {
    event: "message_done",
    data: {
      conversation_id: "conversation-1",
      message_id: "assistant-1",
      status: "interrupted",
      finish_reason: "cancelled",
      content: "partial",
    },
  };

  const next = applyChatStreamEvent(messages, event, now);

  assert.equal(next[0].status, "interrupted");
  assert.equal(next[0].content, "partial");
});

test("error marks the assistant message and keeps fallback content", () => {
  const messages = [assistantMessage({ content: "partial" })];
  const event: ChatStreamEvent = {
    event: "error",
    data: {
      conversation_id: "conversation-1",
      message_id: "assistant-1",
      type: "RateLimitError",
      message: "rate limited",
    },
  };

  const next = applyChatStreamEvent(messages, event, now);

  assert.equal(next[0].status, "error");
  assert.equal(next[0].content, "partial");
  assert.equal(next[0].error, "rate limited");
});
