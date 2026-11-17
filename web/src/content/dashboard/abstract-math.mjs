// Keep source text intact; only paired, unescaped math delimiters become TeX.
const delimiters = [["$$", "$$", true], ["\\[", "\\]", true], ["\\(", "\\)", false], ["$", "$", false]];

// Some public reviews contain a literal extra escape before text/formatting
// commands. Repair those commands for display without decoding TeX row breaks.
export function normalizeTex(tex) {
  return tex.replace(/(?<!\\)\\\\(?=(?:textbf|textit|textnormal|textrm|textsf|texttt|mathbf|mathrm|mathit|mathcal|mathbb|boldsymbol|operatorname|frac|dfrac|tfrac|sqrt)\b)/g, "\\");
}

function escaped(text, index) {
  let slashes = 0;
  while (index > 0 && text[--index] === "\\") slashes++;
  return slashes % 2 === 1;
}

export function abstractParts(source) {
  const text = String(source ?? "");
  const parts = [];
  let plain = 0;
  for (let i = 0; i < text.length; i++) {
    if (escaped(text, i)) continue;
    // Examples/code must remain literal, even when they contain dollars.
    if (text[i] === "`") {
      const marker = /^`+/.exec(text.slice(i))[0];
      const end = text.indexOf(marker, i + marker.length);
      if (end >= 0) { i = end + marker.length - 1; continue; }
    }
    const delimiter = delimiters.find(([open]) => text.startsWith(open, i));
    if (!delimiter) continue;
    const [open, close, display] = delimiter;
    const start = i + open.length;
    if (open === "$" && /\s/.test(text[start] ?? " ")) continue;
    let depth = 0;
    let end = -1;
    for (let j = start; j < text.length; j++) {
      if (escaped(text, j)) continue;
      if (!display && text.startsWith("\n\n", j)) break;
      if (!depth && text.startsWith(close, j)) {
        // Avoid treating ordinary prices such as "$10 and $20" as math.
        if (open === "$" && (/\s/.test(text[j - 1] ?? " ") || /\d/.test(text[j + 1] ?? ""))) break;
        end = j; break;
      }
      if (text[j] === "{") depth++;
      else if (text[j] === "}") depth = Math.max(0, depth - 1);
    }
    if (end < 0 || end === start) { i += open.length - 1; continue; }
    if (i > plain) parts.push({ text: text.slice(plain, i) });
    parts.push({ tex: text.slice(start, end), source: text.slice(i, end + close.length), display });
    i = end + close.length - 1;
    plain = i + 1;
  }
  if (plain < text.length) parts.push({ text: text.slice(plain) });
  return parts;
}
