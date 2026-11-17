import test from "node:test";
import assert from "node:assert/strict";
import { additionalReviewerAliases, notesForReviewer } from "../web/src/content/dashboard/review-matching.mjs";

test("distinct notes from the same anonymous reviewer remain accessible", () => {
  const notes = [{ id: "first", reviewer: "qBAk", rating: 2 },
    { id: "other", reviewer: "4eR9", rating: 2 }, { id: "second", reviewer: "qBAk", rating: 3 }];
  assert.deepEqual(notesForReviewer(notes, "qBAk").map(note => note.id), ["first", "second"]);
  assert.equal(notes.length, 3);
});

test("missing and unmatched aliases never borrow another review", () => {
  const notes = [{ id: "a", reviewer: null }, { id: "b", reviewer: "A" }];
  for (const alias of [null, undefined, "", "B"]) assert.deepEqual(notesForReviewer(notes, alias), []);
});

test("additional reviewer count counts people rather than review notes", () => {
  const scores = [{ reviewer: "A" }];
  const notes = [{ reviewer: "A" }, { reviewer: "B" }, { reviewer: "B" }, { reviewer: null }];
  assert.deepEqual(additionalReviewerAliases(scores, notes), ["B"]);
});
