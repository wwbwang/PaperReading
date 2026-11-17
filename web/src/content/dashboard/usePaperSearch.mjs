import { useEffect, useState } from "react";
import { searchPapers } from "./paper-loader.mjs";

export function usePaperSearch(metadata, query, keywords = "", keywordScope = "all", authors = "", topics = []) {
  const key = JSON.stringify([metadata.year, metadata.revision, query.trim(), keywords.trim(), keywordScope, authors.trim(), topics]);
  const active = Boolean(query.trim() || keywords.trim() || authors.trim() || topics.length);
  const [result, setResult] = useState({ key: "", ids: null, error: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setResult({ key, ids: null, error: null });
    // Invalidate old results immediately; debounce only the network request.
    const timer = setTimeout(() => {
      searchPapers(metadata, query, controller.signal, keywords, keywordScope, authors, topics).then(ids => {
        if (!controller.signal.aborted) setResult({ key, ids, error: null });
      }).catch(error => {
        if (!controller.signal.aborted) setResult({ key, ids: null, error: error.message });
      });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [metadata, key, active, attempt]);
  return {
    active,
    ids: active && result.key === key ? result.ids : null,
    loading: active && (result.key !== key || (!result.ids && !result.error)),
    error: active && result.key === key ? result.error : null,
    retry: () => setAttempt(value => value + 1),
  };
}
