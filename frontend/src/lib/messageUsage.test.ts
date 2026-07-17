import assert from "node:assert/strict";
import test from "node:test";

import { formatMessageUsage } from "./messageUsage";

test("formats server-reported context and actual tokens", () => {
  assert.equal(
    formatMessageUsage({ context_characters: 120, context_budget: 24_000, context_estimated_tokens: 30, total_tokens: 42 }, 0),
    "上下文 120/24,000 字符 · 实际 42 tokens",
  );
});

test("falls back to a local context estimate when a provider omits usage", () => {
  assert.equal(formatMessageUsage(null, 160), "上下文本地估算 160/24,000 字符 · 约 40 tokens");
});

test("formats Skill context and token estimates", () => {
  assert.equal(
    formatMessageUsage({ usage_source: "estimated", context_characters: 100, context_estimated_tokens: 25, completion_estimated_tokens: 10, total_estimated_tokens: 35 }, 0),
    "Skill 上下文 100 字符 · 输入约 25 tokens · 输出约 10 tokens · 总计约 35 tokens",
  );
});
