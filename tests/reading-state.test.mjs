import assert from "node:assert/strict";
import test from "node:test";
import { readingState } from "../web/portal/reading-state.mjs";

function memoryStorage(value = null) {
  return { getItem: () => value, setItem: (_key, next) => { value = next; } };
}

test("initial author follows persist even after explicitly unfollowing everyone", () => {
  const storage = memoryStorage(), state = readingState(["dong"], storage);
  assert.ok(state.follows("dong"));
  state.follow("dong");
  assert.equal(readingState(["dong"], storage).follows("dong"), false);
  state.follow("dong");
  assert.equal(readingState(["dong"], storage).follows("dong"), true);
});

test("reading state isolates author, venue and year and preserves new unread records", () => {
  const storage = memoryStorage(), state = readingState(["dong", "alice"], storage);
  state.mark("dong", ["cvpr/2025/same"], true);
  const restored = readingState(["dong", "alice"], storage);
  assert.ok(restored.isRead("dong", "cvpr/2025/same"));
  assert.equal(restored.isRead("alice", "cvpr/2025/same"), false);
  assert.equal(restored.isRead("dong", "cvpr/2026/same"), false);
  assert.equal(restored.isRead("dong", "iclr/2025/same"), false);
  assert.equal(restored.isRead("dong", "cvpr/2025/new"), false);
  restored.mark("dong", ["cvpr/2025/same"], false);
  assert.equal(readingState(["dong"], storage).isRead("dong", "cvpr/2025/same"), false);
});

test("blocked or damaged storage keeps interactions usable and reports the limitation", () => {
  for (const storage of [memoryStorage("broken"), { getItem() { throw new Error("Denied"); }, setItem() { throw new Error("Full"); } }]) {
    const state = readingState(["dong"], storage);
    assert.equal(state.available, false);
    state.mark("dong", ["paper"], true);
    assert.ok(state.isRead("dong", "paper"));
    state.follow("dong");assert.equal(state.follows("dong"), false);
  }
});
