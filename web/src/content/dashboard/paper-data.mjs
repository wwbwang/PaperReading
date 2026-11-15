export const PAGE_SIZE = 25;
export const STATUS_LABELS = {
  Active: "Active · 审稿中",
  Poster: "Poster · 录用", Oral: "Oral · 录用", Reject: "Reject · 拒稿",
  Withdraw: "Withdraw · 撤稿", "Desk Reject": "Desk Reject · 直接拒稿",
};

export const DEFAULT_SCALE = { min: 1, max: 4 };

export function binCount(scale = DEFAULT_SCALE) {
  return 2 * (scale.max - scale.min);
}

export function binLabel(index, scale = DEFAULT_SCALE) {
  return `[${(scale.min + index / 2).toFixed(1)}, ${(scale.min + (index + 1) / 2).toFixed(1)}${index === binCount(scale) - 1 ? "]" : ")"}`;
}

export function scoreBin(scores, scale = DEFAULT_SCALE) {
  const valid = scores.filter(value => value !== null);
  if (valid.some(value => !Number.isFinite(value) || value < scale.min || value > scale.max)) throw new RangeError("Rating is outside the conference scale");
  return valid.length ? Math.min(binCount(scale) - 1,
    Math.floor((2 * valid.reduce((a, b) => a + b, 0) - 2 * scale.min * valid.length) / valid.length)) : null;
}

export function exactMeanKey(scores) {
  const valid = scores.filter(value => value !== null);
  if (!valid.length) return null;
  if (valid.some(value => !Number.isInteger(value))) throw new RangeError("Ratings must be integers");
  const sum = valid.reduce((a, b) => a + b, 0);
  let a = Math.abs(sum), b = valid.length;
  while (b) [a, b] = [b, a % b];
  return `${sum / a}/${valid.length / a}`;
}

export function meanLabel(key) {
  const [numerator, denominator] = key.split("/").map(Number);
  return (numerator / denominator).toFixed(2);
}

export function exactHistogram(rows, domain = rows) {
  const bins = new Map(domain.filter(row => row.bin !== null).map(row => [row.bin,
    { bin: row.bin, range: meanLabel(row.bin), count: 0, share: 0 }]));
  let scored = 0;
  for (const row of rows) {
    if (row.bin === null) continue;
    bins.get(row.bin).count += 1;
    scored += 1;
  }
  return [...bins.values()].sort((a, b) => {
    const [an, ad] = a.bin.split("/").map(Number);
    const [bn, bd] = b.bin.split("/").map(Number);
    return an * bd - bn * ad;
  }).map(row => ({ ...row, share: scored ? row.count / scored : 0 }));
}

export function createPaperIndex(rows) {
  const search = new Map(rows.map(row => [row.id, `${row.title}\n${row.abstract || ""}`.toLowerCase()]));
  return { rows, search };
}

export function filterPapers(index, { query = "", status = "all" } = {}) {
  const needle = query.trim().toLowerCase();
  return index.rows.filter(row => (status === "all" || row.status === status)
    && (!needle || index.search.get(row.id).includes(needle)));
}

export function histogram(rows, scale = DEFAULT_SCALE) {
  const bins = Array.from({ length: binCount(scale) }, (_, bin) => ({ bin, range: binLabel(bin, scale), count: 0, share: 0 }));
  let scored = 0;
  for (const row of rows) {
    if (row.bin === null) continue;
    bins[row.bin].count += 1;
    scored += 1;
  }
  return bins.map(row => ({ ...row, share: scored ? row.count / scored : 0 }));
}

export function selectPapers(rows, selection = "all", order = "desc") {
  return rows.filter(row => selection === "all" || (selection === "missing" ? row.bin === null : row.bin === selection))
    .sort((a, b) => {
      if (a.rating_mean === null && b.rating_mean !== null) return 1;
      if (a.rating_mean !== null && b.rating_mean === null) return -1;
      const difference = a.rating_mean === null ? 0 : (a.rating_mean - b.rating_mean) * (order === "asc" ? 1 : -1);
      return difference || a.id.localeCompare(b.id, "en");
    });
}

export function pageOf(rows, requestedPage) {
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const page = Math.min(Math.max(0, requestedPage), pages - 1);
  return { rows: rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), page, pages };
}
