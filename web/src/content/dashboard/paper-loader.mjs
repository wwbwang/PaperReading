// Share requests while retaining only a small number of detail chunks in memory.
const chunks = new Map();

export function loadPaperDetails(metadata, paper) {
  const url = `${metadata.detailBase}${paper.detail_chunk}.json`;
  if (!chunks.has(url)) {
    const request = fetch(url).then(response => {
      if (!response.ok) throw new Error("无法读取论文详情，请重试。");
      return response.json();
    }).catch(error => { chunks.delete(url); throw error; });
    chunks.set(url, request);
    if (chunks.size > 16) chunks.delete(chunks.keys().next().value);
  }
  return chunks.get(url).then(rows => {
    if (!rows[paper.id]) throw new Error("论文详情与当前快照不一致，请刷新页面。");
    return rows[paper.id];
  });
}

export async function searchPapers(metadata, query, signal, keywords = "", keywordScope = "both") {
  const params = new URLSearchParams({ conference: "iclr", year: metadata.year, revision: metadata.revision, q: query.trim() });
  if (keywords.trim()) { params.set("keywords", keywords.trim()); params.set("keyword_scope", keywordScope); }
  const response = await fetch(`/api/search?${params}`, { signal });
  if (!response.ok) throw new Error(response.status === 409 ? "数据已更新，请刷新页面后搜索。" : "搜索暂不可用，请重试。");
  const result = await response.json();
  if (result.revision !== metadata.revision) throw new Error("搜索结果版本不一致，请刷新页面。");
  if (!Array.isArray(result.ids) || result.ids.some(id => typeof id !== "string" || !id)) throw new Error("搜索结果格式异常，请重试。");
  return new Set(result.ids);
}

export async function loadKeywords(metadata, ids, signal) {
  if (!ids.length) return {};
  const params = new URLSearchParams({ year: metadata.year, revision: metadata.revision, ids: ids.join(",") });
  const response = await fetch(`/api/keywords?${params}`, { signal });
  if (!response.ok) throw new Error("关键词暂不可用，请重试。");
  const result = await response.json();
  if (result.revision !== metadata.revision || ids.some(id => typeof result.keywords?.[id] !== "string")) throw new Error("关键词与当前快照不一致，请刷新页面。");
  return result.keywords;
}

// Reviews are fetched only after a visitor opens an evaluation preview.
const reviewRequests = new Map();
export function loadReviewText(metadata, paperId) {
  const params = new URLSearchParams({ year: metadata.year, revision: metadata.revision, paper_id: paperId });
  const key = params.toString();
  if (!reviewRequests.has(key)) {
    reviewRequests.set(key, fetch(`/api/reviews?${params}`).then(async response => {
      const result = await response.json();
      if (result.paper_id && result.paper_id !== paperId) throw new Error("评价正文与当前论文不一致，请刷新页面。 ");
      if (!Array.isArray(result.reviews)) throw new Error("无法读取评价正文，请在 OpenReview 查看。");
      if (!response.ok) reviewRequests.delete(key);
      return result;
    }).catch(error => { reviewRequests.delete(key); throw error; }));
    if (reviewRequests.size > 50) reviewRequests.delete(reviewRequests.keys().next().value);
  }
  return reviewRequests.get(key);
}
