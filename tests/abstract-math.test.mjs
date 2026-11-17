import test from "node:test";
import assert from "node:assert/strict";
import { abstractParts, normalizeTex } from "../web/src/content/dashboard/abstract-math.mjs";
import katex from "../web/src/content/assets/katex/katex.mjs";

test("real LFP abstract renders bold initials without changing the source", () => {
  const text = String.raw`We present $\textbf{L}$ight $\textbf{F}$ield $\textbf{P}$rimitives ($\textbf{LFP}$).`;
  const parts = abstractParts(text);
  assert.equal(parts.map(p => p.source ?? p.text).join(""), text);
  assert.equal(parts.filter(p => p.tex).length, 4);
  for (const part of parts.filter(p => p.tex)) {
    assert.match(katex.renderToString(part.tex), /class="mord textbf"/);
  }
});

test("OmniLV reviewer strengths use the same math rendering as abstracts", () => {
  const source = String.raw`$\textbf{Comprehensive scope and ambition.}$ The work systematically tackles over 100 sub-tasks.

$\textbf{Sound architectural reasoning.}$ The separation is well motivated.`;
  const parts = abstractParts(source);
  assert.equal(parts.filter(p => p.tex).length, 2);
  assert.equal(parts.map(p => p.source ?? p.text).join(""), source);
  for (const part of parts.filter(p => p.tex)) assert.match(katex.renderToString(part.tex), /class="mord textbf"/);
});

test("literal double-escaped review formatting renders without changing matrix row breaks", () => {
  const source = String.raw`$\\textbf{Comprehensive scope and ambition.}$`;
  const [part] = abstractParts(source);
  assert.match(katex.renderToString(normalizeTex(part.tex)), /class="mord textbf"/);
  assert.equal(part.source, source);
  const matrix = String.raw`\begin{matrix}a & b\\c & d\end{matrix}`;
  assert.equal(normalizeTex(matrix), matrix);
  const newlineThenCommand = String.raw`a\\\textbf{b}`;
  assert.equal(normalizeTex(newlineThenCommand), newlineThenCommand);
});

test("inline and display math, escaped delimiters, braces, and paragraphs", () => {
  const parts = abstractParts(String.raw`A $x_1$; \(y^2\).

$$\frac{a}{b}$$ \[\sum_i x_i\] $\text{cost $5}$ and \$10.`);
  assert.deepEqual(parts.filter(p => p.tex).map(p => [p.tex, p.display]), [
    ["x_1", false], ["y^2", false], [String.raw`\frac{a}{b}`, true],
    [String.raw`\sum_i x_i`, true], [String.raw`\text{cost $5}`, false],
  ]);
  assert.ok(parts.some(p => p.text?.includes("\n\n")));
});

test("ordinary prices, unpaired delimiters and code remain literal", () => {
  for (const text of ["Costs $10 and $20.", "unmatched $x", "$$x$", "`$x$`", "```\n$$x$$\n```", "$ spaced $", "\\$x\\$"]) {
    assert.deepEqual(abstractParts(text), [{ text }]);
  }
});

test("renderer escapes HTML and rejects malformed math without trusting TeX", () => {
  const options = { trust: false, throwOnError: true, maxExpand: 1000, maxSize: 20 };
  assert.throws(() => katex.renderToString(String.raw`\frac{a`, options));
  const html = katex.renderToString(String.raw`\text{<img src=x onerror=alert(1)>}`, options);
  assert.ok(!html.includes("<img"));
  const link = katex.renderToString(String.raw`\href{javascript:alert(1)}{click}`, options);
  assert.ok(!link.includes("href="));
});
