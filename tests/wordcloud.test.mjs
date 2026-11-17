import test from "node:test";
import assert from "node:assert/strict";
import { layoutWordCloud } from "../web/src/content/dashboard/wordcloud-layout.mjs";

const words = Array.from({ length: 60 }, (_, i) => ({ key: `topic ${i}`, label: `Topic ${i}`, count: 100 - i }));
const measure = (label, size) => label.length * size * .55;

test("desktop and mobile packing keeps every visible word inside the plot without overlaps", () => {
  for (const width of [330, 700, 1100]) {
    const height = width < 600 ? 400 : 360;
    const result = layoutWordCloud(words, width, height, measure);
    assert.ok(result.length >= (width < 600 ? 20 : 40), `${width}: ${result.length} words`);
    for (const item of result) {
      assert.ok(item.box.x >= 0 && item.box.y >= 0);
      assert.ok(item.box.x + item.box.width <= width && item.box.y + item.box.height <= height);
      for (const other of result) {
        if (item === other) continue;
        assert.ok(!(item.box.x < other.box.x + other.box.width && item.box.x + item.box.width > other.box.x
          && item.box.y < other.box.y + other.box.height && item.box.y + item.box.height > other.box.y));
      }
    }
    assert.ok(result[0].fontSize >= result.at(-1).fontSize);
    assert.deepEqual(result, layoutWordCloud(words, width, height, measure));
  }
});

test("empty sets and long labels remain safe while preserving the full source label", () => {
  assert.deepEqual(layoutWordCloud([], 1000, 360, measure), []);
  const label = "A very long keyword phrase ".repeat(12);
  const result = layoutWordCloud([{ key: "long", label, count: 1 }], 330, 400, measure);
  assert.equal(result.length, 1);
  assert.equal(result[0].fullLabel, label);
  assert.ok(result[0].label.endsWith("…"));
  assert.ok(Number.isFinite(result[0].fontSize));
});
