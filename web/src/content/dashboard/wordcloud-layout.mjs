// Deterministic spiral packing; frequency controls font size, not color.
export function layoutWordCloud(words, width, height, measure) {
  if (!words.length || width < 80) return [];
  const candidates = words.slice(0, width < 600 ? 30 : 60);
  const maximum = Math.sqrt(candidates[0].count);
  const minimum = Math.sqrt(candidates.at(-1).count);
  const baseSize = word => 15 + (width < 600 ? 21 : 43)
    * (maximum === minimum ? .5 : (Math.sqrt(word.count) - minimum) / (maximum - minimum));
  const area = candidates.reduce((sum, word) => sum
    + (Math.min(measure(word.label, baseSize(word)), width - 24) + 12) * (baseSize(word) * 1.35 + 6), 0);
  const densityScale = Math.min(1, Math.sqrt(width * height * .5 / area));
  let best = [];
  for (let pass = 0; pass < 5; pass++) {
    const placed = [];
    for (const word of candidates) {
      const fontSize = Math.max(12, baseSize(word) * densityScale * Math.pow(.9, pass));
      let label = word.label;
      const maxWidth = Math.min(width - 24, width < 600 ? 320 : 600);
      while (label.length > 2 && measure(label, fontSize) > maxWidth) label = label.slice(0, -2).trimEnd() + "…";
      const boxWidth = measure(label, fontSize) + 12, boxHeight = fontSize * 1.35 + 6;
      for (let step = 0; step < 5000; step++) {
        const angle = step * .3, radius = 3.8 * Math.sqrt(step);
        const x = width / 2 + Math.cos(angle) * radius * (width / height);
        const y = height / 2 + Math.sin(angle) * radius;
        const box = { x: x - boxWidth / 2, y: y - boxHeight / 2, width: boxWidth, height: boxHeight };
        if (box.x < 4 || box.y < 4 || box.x + box.width > width - 4 || box.y + box.height > height - 4) continue;
        if (placed.some(other => box.x < other.box.x + other.box.width && box.x + box.width > other.box.x
          && box.y < other.box.y + other.box.height && box.y + box.height > other.box.y)) continue;
        let hash = 0;
        for (const char of word.key) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
        placed.push({ ...word, label, fullLabel: word.label, fontSize, x, y, box, color: hash % 5 + 1 });
        break;
      }
    }
    if (placed.length > best.length) best = placed;
    if (placed.length === candidates.length) return placed;
  }
  return best;
}
