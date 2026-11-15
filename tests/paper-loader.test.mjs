import test from "node:test";
import assert from "node:assert/strict";
import { searchPapers } from "../web/src/content/dashboard/paper-loader.mjs";

const metadata = { year: 2027, revision: "test-snapshot" };

test("author queries combine with title and keyword queries", async t => {
  t.mock.method(globalThis, "fetch", async url => {
    const params = new URL(url, "http://localhost").searchParams;
    assert.equal(params.get("authors"), "Alice Zhang");
    assert.equal(params.get("q"), "image");
    assert.equal(params.get("keywords"), "diff");
    assert.equal(params.get("keyword_scope"), "title");
    return new Response(JSON.stringify({ revision: metadata.revision, ids: ["paper-a"] }));
  });
  assert.deepEqual([...await searchPapers(metadata, "image", undefined, "diff", "title", "  Alice Zhang  ")], ["paper-a"]);
});

test("missing author data is not presented as an empty search result", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response("{}", { status: 422 }));
  await assert.rejects(searchPapers(metadata, "", undefined, "", "both", "Alice"), /未提供作者信息/);
});

test("fuzzy search sends both fields by default and respects explicit scope", async t => {
  const scopes = [];
  t.mock.method(globalThis, "fetch", async url => {
    const params = new URL(url, "http://localhost").searchParams;
    assert.equal(params.get("keywords"), "diff");
    scopes.push(params.get("keyword_scope"));
    return new Response(JSON.stringify({ revision: metadata.revision, ids: [] }));
  });
  await searchPapers(metadata, "", undefined, "diff");
  await searchPapers(metadata, "", undefined, "diff", "keywords");
  await searchPapers(metadata, "", undefined, "diff", "title");
  assert.deepEqual(scopes, ["both", "keywords", "title"]);
});

test("malformed search responses are errors, not empty results", async t => {
  for (const ids of [undefined, null, "paper-a", {}, [12], [null], [""]]) {
    t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ revision: metadata.revision, ids })));
    await assert.rejects(searchPapers(metadata, "image"), /格式异常/);
    t.mock.restoreAll();
  }
});

test("genuine empty results and paper IDs remain valid", async t => {
  for (const ids of [[], ["paper-a", "paper-b"]]) {
    t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ revision: metadata.revision, ids })));
    assert.deepEqual([...await searchPapers(metadata, "image")], ids);
    t.mock.restoreAll();
  }
});

test("search rejects a different snapshot and preserves cancellation", async t => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ revision: "other", ids: [] })));
  await assert.rejects(searchPapers(metadata, "image"), /版本不一致/);
  t.mock.restoreAll();
  const controller = new AbortController();
  controller.abort();
  t.mock.method(globalThis, "fetch", async (url, { signal }) => {
    assert.equal(signal, controller.signal);
    signal.throwIfAborted();
  });
  await assert.rejects(searchPapers(metadata, "image", controller.signal), { name: "AbortError" });
});
