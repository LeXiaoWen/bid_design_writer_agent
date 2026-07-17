import assert from "node:assert/strict";
import test from "node:test";

import { splitSearchHighlight } from "./searchHighlight";

test("splits every case-insensitive search match without changing source text", () => {
  const parts = splitSearchHighlight("Alpha 项目 alpha", "ALPHA");

  assert.deepEqual(parts, [
    { text: "Alpha", matched: true },
    { text: " 项目 ", matched: false },
    { text: "alpha", matched: true },
  ]);
  assert.equal(parts.map((part) => part.text).join(""), "Alpha 项目 alpha");
});
