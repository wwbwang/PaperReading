import React, { useEffect, useMemo, useRef, useState } from "react";
import { DataComponent } from "../../data-app-public.jsx";
import { loadWordCloud } from "./paper-loader.mjs";
import { layoutWordCloud } from "./wordcloud-layout.mjs";

export function TopicCloud({ metadata, rows, selected, onSelect, scopeFilters, busy, error, retryScope }) {
  const scope = useMemo(() => rows.map(row => row.id).sort().join(","), [rows]);
  const key = `${metadata.year}:${metadata.revision}:${scope}`;
  const [response, setResponse] = useState(null);
  const [failure, setFailure] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const plot = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (busy || error) return;
    const controller = new AbortController();
    setFailure(null);
    const timer = setTimeout(() => loadWordCloud(metadata, scope ? scope.split(",") : [], controller.signal)
      .then(value => { if (!controller.signal.aborted) setResponse({ key, value }); })
      .catch(value => { if (!controller.signal.aborted) setFailure({ key, message: value.message }); }), 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [metadata, key, busy, error, attempt]);
  const result = response?.key === key && !busy && !error ? response.value : null;
  const message = error || (failure?.key === key ? failure.message : null);
  useEffect(() => {
    if (!plot.current) return;
    const observer = new ResizeObserver(entries => setWidth(Math.floor(entries[0].contentRect.width)));
    observer.observe(plot.current);
    return () => observer.disconnect();
  }, [result]);
  const height = width < 600 ? 400 : 360;
  const words = useMemo(() => {
    if (!result || !width) return [];
    const context = document.createElement("canvas").getContext("2d");
    return layoutWordCloud(result.words, width, height, (label, size) => {
      context.font = `600 ${size}px system-ui, sans-serif`;
      return context.measureText(label).width;
    });
  }, [result, width, height]);
  const loading = busy || (!result && !message);
  return <DataComponent id="topic-cloud" queryId="papers" kind="custom" variant="card" title="主题词云" showHeading={false}
    loading={loading} loadingError={message || undefined} onRetry={() => error ? retryScope() : setAttempt(value => value + 1)}
    displayRows={result?.words || []} sourceRows={rows} scopeFilters={scopeFilters}>
    <div className="iclr-topic-cloud" data-reviewed-rows="papers">
      <p className="iclr-topic-summary">{result ? <>当前筛选 <strong>{result.paper_count.toLocaleString("zh-CN")}</strong> 篇 · {result.keyword_papers.toLocaleString("zh-CN")} 篇参与主题统计</> : "正在统计当前筛选的主题…"}</p>
      <p className="iclr-chart-note">来自论文 Keywords，同一主题每篇只计一次；字号越大，涉及论文越多。颜色用于区分主题，点击可叠加筛选。</p>
      {result?.words.length > 0 ? <>
        <div ref={plot} className="iclr-wordcloud-plot">
          <svg width="100%" height={height} viewBox={`0 0 ${Math.max(width, 1)} ${height}`} role="group" aria-label="当前筛选论文的主题词云">
            {words.map(word => {
              const active = selected.some(topic => topic.key === word.key);
              const disabled = !active && selected.length >= 12;
              return <g key={word.key} role="button" tabIndex={disabled ? -1 : 0} aria-disabled={disabled || undefined}
                aria-pressed={active} aria-label={`${word.fullLabel}，${word.count} 篇论文`}
                data-topic={word.key} data-count={word.count} transform={`translate(${word.x},${word.y})`}
                onClick={() => { if (!disabled) onSelect({ key: word.key, label: word.fullLabel }); }}
                onKeyDown={event => { if (!disabled && ["Enter", " "].includes(event.key)) { event.preventDefault(); onSelect({ key: word.key, label: word.fullLabel }); } }}>
                <title>{word.fullLabel} · {word.count.toLocaleString("zh-CN")} 篇 · {word.percentage.toFixed(2)}%{active ? " · 点击移除主题筛选" : " · 点击叠加主题筛选"}</title>
                <rect x={-word.box.width / 2} y={-word.box.height / 2} width={word.box.width} height={word.box.height} rx="5" />
                <text textAnchor="middle" dominantBaseline="central" style={{ fontSize: word.fontSize, fill: `color-mix(in srgb, var(--chart-${word.color}) 85%, var(--text))` }}>{word.label}</text>
              </g>;
            })}
          </svg>
        </div>
        <p className="iclr-chart-note">展示 {words.length} 个高频主题，共 {result.topic_count.toLocaleString("zh-CN")} 个主题；{result.missing_keywords.toLocaleString("zh-CN")} 篇未提供可统计的 Keywords。统计包含所有分页，并跟随搜索、状态、均分和结果内搜索更新。</p>
      </> : result && <p className="iclr-empty" role="status">{result.paper_count ? "这些论文未提供可统计的 Keywords。" : "当前筛选没有论文，可移除主题或调整其他筛选条件。"}</p>}
    </div>
  </DataComponent>;
}
