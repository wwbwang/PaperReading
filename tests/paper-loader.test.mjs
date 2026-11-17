import test from "node:test";
import assert from "node:assert/strict";
import { loadWordCloud, searchPapers } from "../web/src/content/dashboard/paper-loader.mjs";

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

test("fuzzy search includes abstracts by default and respects explicit scope", async t => {
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
  await searchPapers(metadata, "", undefined, "diff", "abstract");
  await searchPapers(metadata, "", undefined, "diff", "both");
  assert.deepEqual(scopes, ["all", "keywords", "title", "abstract", "both"]);
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

test("topic selections travel with existing author, text and keyword queries", async t => {
  t.mock.method(globalThis, "fetch", async url => {
    const params = new URL(url, "http://localhost").searchParams;
    assert.deepEqual(JSON.parse(params.get("topics")), ["video super resolution", "diffusion"]);
    assert.equal(params.get("authors"), "Alice");
    return new Response(JSON.stringify({ revision: metadata.revision, ids: ["paper-a"] }));
  });
  assert.deepEqual([...await searchPapers(metadata, "image", undefined, "restor", "all", "Alice", ["video super resolution", "diffusion"])], ["paper-a"]);
});

test("wordcloud requests include all filtered IDs and reject stale or malformed results", async t => {
  const result = { revision: metadata.revision, paper_count: 2, keyword_papers: 1, missing_keywords: 1, topic_count: 1,
    words: [{ key: "diffusion", label: "Diffusion", count: 1, percentage: 50 }] };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/wordcloud");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { year: 2027, revision: metadata.revision, ids: ["a", "b"] });
    return new Response(JSON.stringify(result));
  });
  assert.deepEqual(await loadWordCloud(metadata, ["a", "b"]), result);
  for (const invalid of [{ ...result, revision: "other" }, { ...result, paper_count: 1 },
    { ...result, words: [{ key: "diffusion", label: "Diffusion", count: 3, percentage: 150 }] }]) {
    t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify(invalid)));
    await assert.rejects(loadWordCloud(metadata, ["a", "b"]), /不一致/);
  }
});
