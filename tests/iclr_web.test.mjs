import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createPaperIndex, exactMeanKey, meanLabel, exactHistogram, scoreBin, binLabel, histogram, filterPapers, selectPapers, pageOf } from "../web/src/content/dashboard/paper-data.mjs";

test("legacy half-point boundaries use the original 1–4 scale and include 4", () => {
  assert.equal(scoreBin([1, 1]), 0);
  assert.equal(scoreBin([1, 2]), 1);
  assert.equal(scoreBin([2, 2]), 2);
  assert.equal(scoreBin([2, 3]), 3);
  assert.equal(scoreBin([3, 4]), 5);
  assert.equal(scoreBin([4, 4]), 5);
  assert.equal(scoreBin([]), null);
  assert.equal(scoreBin([null]), null);
  assert.equal(scoreBin([null, 1]), 0);
  assert.equal(binLabel(0), "[1.0, 1.5)");
  assert.equal(binLabel(5), "[3.5, 4.0]");
  assert.throws(() => scoreBin([0]), RangeError);
  assert.throws(() => scoreBin([6]), RangeError);
});

test("historical 2026 data uses an explicit separate scale", () => {
  const scale = { min: 0, max: 10 };
  assert.equal(scoreBin([0, 0], scale), 0);
  assert.equal(scoreBin([0, 1], scale), 1);
  assert.equal(scoreBin([10, 10], scale), 19);
  assert.equal(binLabel(19, scale), "[9.5, 10.0]");
});

const rows = [
  { id: "a", title: "Diffusion", abstract: "image restoration", status: "Active", rating_mean: 3, bin: 4 },
  { id: "b", title: "Language", abstract: "Diffusion for text", status: "Desk Reject", rating_mean: 2, bin: 2 },
  { id: "c", title: "Unrated", abstract: "", status: "Withdraw", rating_mean: null, bin: null },
  { id: "d", title: "Another", abstract: "", status: "Active", rating_mean: 3, bin: 4 },
];

test("search and status filters intersect and search includes abstracts", () => {
  const index = createPaperIndex(rows);
  assert.deepEqual(filterPapers(index, { query: " DIFFUSION " }).map(r => r.id), ["a", "b"]);
  assert.deepEqual(filterPapers(index, { query: "diffusion", status: "Active" }).map(r => r.id), ["a"]);
  assert.equal(filterPapers(index, { query: "missing" }).length, 0);
});

test("empty bins are retained and unscored papers are excluded from shares", () => {
  const bins = histogram(rows);
  assert.equal(bins.length, 6);
  assert.equal(bins[4].count, 2);
  assert.equal(bins[4].share, 2 / 3);
  assert.equal(bins[0].count, 0);
  assert.equal(histogram([]).reduce((n, r) => n + r.share, 0), 0);
});

test("range selection changes records without changing the parent distribution", () => {
  const before = histogram(rows);
  assert.deepEqual(selectPapers(rows, 4).map(r => r.id), ["a", "d"]);
  assert.deepEqual(selectPapers(rows, "missing").map(r => r.id), ["c"]);
  assert.equal(selectPapers(rows, 5).length, 0);
  assert.deepEqual(histogram(rows), before);
});

test("both sort orders retain missing scores last and break ties by ID", () => {
  assert.deepEqual(selectPapers(rows).map(r => r.id), ["a", "d", "b", "c"]);
  assert.deepEqual(selectPapers(rows, "all", "asc").map(r => r.id), ["b", "a", "d", "c"]);
});

test("25-row pagination clamps after a filter reduces the result set", () => {
  const many = Array.from({ length: 51 }, (_, id) => ({ id }));
  assert.equal(pageOf(many, 0).rows.length, 25);
  assert.equal(pageOf(many, 1).rows[0].id, 25);
  assert.equal(pageOf(many, 2).rows.length, 1);
  assert.equal(pageOf(rows, 20).page, 0);
  assert.deepEqual(pageOf([], 0), { rows: [], page: 0, pages: 1 });
});

for (const year of [2026, 2027]) test(`ICLR ${year}: lean bootstrap and lazy details reconcile every source paper`, () => {
  const root = new URL(`../web/dist/iclr/${year}/`, import.meta.url);
  const build = JSON.parse(readFileSync(new URL("data-app-build.json", root)));
  const snapshot = JSON.parse(readFileSync(new URL(build.snapshot.path, root)));
  const manifest = JSON.parse(readFileSync(new URL(`../iclr${year}/manifest.json`, import.meta.url)));
  const source = readFileSync(new URL(`../iclr${year}/papers.jsonl`, import.meta.url), "utf8").trim().split("\n").map(JSON.parse);
  const website = snapshot.queries.papers.rows;
  const original = new Map(source.map(row => [row.id, row]));
  const scale = snapshot.iclr.ratingScale;
  const chunks = new Map();
  assert.equal(snapshot.title, "PaperReading");
  assert.equal(snapshot.iclr.year, year);
  assert.equal(snapshot.iclr.conference, `ICLR ${year}`);
  assert.deepEqual(scale.values, year === 2027 ? [1, 2, 3, 4] : [0, 2, 4, 6, 8, 10]);
  assert.equal(website.length, manifest.paper_count);
  assert.equal(new Set(website.map(r => r.id)).size, manifest.paper_count);
  assert.equal(website.filter(r => r.bin === null).length, manifest.papers_without_ratings);
  assert.equal((year === 2027 ? exactHistogram(website) : histogram(website, scale)).reduce((total, bin) => total + bin.count, 0), manifest.paper_count - manifest.papers_without_ratings);
  let zeros = 0;
  for (const row of website) {
    const raw = original.get(row.id);
    assert.ok(raw);
    assert.ok(!("keywords" in row), "keywords load only for the visible page");
    assert.ok(!("abstract" in row));
    assert.ok(!("reviews_json" in row));
    for (const key of ["title", "rating_mean", "status"]) assert.equal(row[key], raw[key]);
    const ratings = JSON.parse(row.ratings_json);
    assert.deepEqual(ratings, raw.ratings);
    assert.equal(row.bin, year === 2027 ? exactMeanKey(raw.ratings) : scoreBin(raw.ratings, scale));
    if (!chunks.has(row.detail_chunk)) chunks.set(row.detail_chunk, JSON.parse(readFileSync(
      new URL(`../web/dist${snapshot.iclr.detailBase}${row.detail_chunk}.json`, import.meta.url))));
    const detail = chunks.get(row.detail_chunk)[row.id];
    assert.equal(detail.id, row.id);
    for (const key of ["abstract", "paper_url", "pdf_url"]) assert.equal(detail[key], raw[key]);
    const reviews = JSON.parse(detail.reviews_json);
    assert.equal(reviews.length, raw.reviews.length);
    for (let i = 0; i < reviews.length; i++) {
      for (const key of ["reviewer", "rating", "confidence", "soundness", "presentation", "contribution", "informativeness"]) assert.equal(reviews[i][key], raw.reviews[i][key] ?? null);
    }
    zeros += ratings.filter(value => value === 0).length;
  }
  assert.equal(zeros, manifest.zero_ratings_preserved);
  assert.equal(snapshot.buildStatus, "complete");
  assert.ok(readFileSync(new URL(build.snapshot.path + ".gz", root)).length < 3_000_000, "initial data stays below 3 MB compressed");
});

test("the entry page links all 23 venues and three years without embedding the paper corpus", () => {
  const page = readFileSync(new URL("../web/dist/index.html", import.meta.url), "utf8");
  assert.ok(page.includes('href="/iclr/2026/"'));
  assert.ok(page.includes('href="/iclr/2027/"'));
  assert.ok(Buffer.byteLength(page) < 75_000, "69 year cards stay below 75 KB uncompressed");
  assert.ok(readFileSync(new URL("../web/dist/index.html.gz", import.meta.url)).length < 12_000, "entry transfer stays below 12 KB compressed");
  assert.ok(!page.includes("ratings_json"), "paper rows remain in lazy-loaded datasets");
  const catalog = JSON.parse(readFileSync(new URL("../web/dist/catalog.json", import.meta.url)));
  assert.equal(catalog.datasets.length, 69);
  const venues = [...new Set(catalog.datasets.map(row => row.venue))];
  assert.equal(venues.length, 23);
  for (const venue of venues) {
    assert.deepEqual(catalog.datasets.filter(row => row.venue === venue).map(row => row.year), [2027, 2026, 2025]);
    for (const year of [2025, 2026, 2027]) assert.ok(page.includes(`href="/${venue}/${year}/"`));
  }
});

test("exact mean keys merge equivalent fractions without merging nearby means", () => {
  assert.equal(exactMeanKey([1, 2, 4]), "7/3");
  assert.equal(exactMeanKey([1, 1, 2, 2, 4, 4]), "7/3");
  assert.equal(exactMeanKey([2, 2, 2]), "2/1");
  assert.equal(exactMeanKey([4]), "4/1");
  assert.equal(exactMeanKey([null, 2, 3]), "5/2");
  assert.equal(exactMeanKey([null]), null);
  assert.equal(exactMeanKey([]), null);
  assert.notEqual(exactMeanKey([2, 2, 3]), exactMeanKey([2, 2, 2, 3]));
  assert.equal(meanLabel("7/3"), "2.33");
  assert.equal(meanLabel("2/1"), "2.00");
});

test("exact columns sort numerically, reconcile counts, and retain the global domain after filtering", () => {
  const exact = [
    { id: "a", bin: "7/3", rating_mean: 7/3 },
    { id: "b", bin: "7/3", rating_mean: 7/3 },
    { id: "c", bin: "9/4", rating_mean: 9/4 },
    { id: "d", bin: "4/1", rating_mean: 4 },
    { id: "e", bin: null, rating_mean: null },
  ];
  const bins = exactHistogram(exact);
  assert.deepEqual(bins.map(b => b.bin), ["9/4", "7/3", "4/1"]);
  assert.equal(bins[1].count, 2);
  assert.equal(bins[1].share, .5);
  assert.deepEqual(selectPapers(exact, "7/3").map(p => p.id), ["a", "b"]);
  assert.deepEqual(selectPapers(exact, "missing").map(p => p.id), ["e"]);
  assert.deepEqual(exactHistogram([exact[2]], exact).map(b => b.count), [1, 0, 0]);
  assert.equal(exactHistogram([], exact).length, 3);
  assert.ok(exactHistogram([], exact).every(b => b.count === 0 && b.share === 0));
});

test("2027 renders all 33 actual exact means and selects only equal fractions", () => {
  const root = new URL("../web/dist/iclr/2027/", import.meta.url);
  const build = JSON.parse(readFileSync(new URL("data-app-build.json", root)));
  const snapshot = JSON.parse(readFileSync(new URL(build.snapshot.path, root)));
  const rows = snapshot.queries.papers.rows;
  const bins = exactHistogram(rows);
  assert.equal(bins.length, 33);
  assert.equal(bins.reduce((sum, b) => sum + b.count, 0), 40801);
  assert.equal(bins.find(b => b.bin === "2/1").count, 11816);
  assert.equal(bins.find(b => b.bin === "7/3").count, 8582);
  assert.equal(bins.find(b => b.bin === "4/1").count, 4);
  assert.equal(bins.find(b => b.bin === "12/7").count, 1);
  for (const bin of bins) {
    const selected = selectPapers(rows, bin.bin);
    assert.equal(selected.length, bin.count);
    assert.ok(selected.every(row => exactMeanKey(JSON.parse(row.ratings_json)) === bin.bin));
  }
});
