import React, { useEffect, useId, useState } from "react";
import { loadReviewText } from "./paper-loader.mjs";

export function ReviewPreview({ paper, review: scores, index, fields, metadata }) {
  const reviewer = scores.reviewer;
  const alias = reviewer || `审稿人 ${index + 1}`;
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open || result) return;
    let active = true;
    setError(null);
    loadReviewText(metadata, paper.id).then(value => { if (active) setResult(value); })
      .catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [open, result, metadata, paper.id, attempt]);
  // Match the anonymous alias, never the position or score of a reviewer.
  const matches = reviewer ? result?.reviews.filter(review => review.reviewer === reviewer) || [] : [];
  const review = matches.length === 1 ? matches[0] : null;
  return <>
    <tr className="iclr-review-score-row">
      <th scope="row"><button type="button" className="iclr-review-toggle" aria-expanded={open}
        aria-controls={open ? panelId : undefined} aria-label={`${alias} 的审稿评价`} onClick={() => setOpen(value => !value)}>
        <span aria-hidden="true">{open ? "▾" : "▸"}</span><span>{alias}</span>
      </button></th>
      {fields.map(field => <td key={field}>{scores[field] ?? "—"}</td>)}
    </tr>
    {open && <tr className="iclr-review-detail-row"><td colSpan={fields.length + 1}>
    <div id={panelId} className="iclr-review-body" role="region" aria-label={`${alias} 的审稿评价正文`}>
      {!result && !error && <p className="iclr-muted" role="status">正在获取公开审稿评价…</p>}
      {error && <p role="alert">{error}</p>}
      {result && !review?.sections.length && <p className="iclr-muted">{result.message || (result.status === "empty" ? "当前未获取到公开评价正文。" : "尚未取得与此匿名审稿人唯一对应的评价正文。")}</p>}
      {(error || (result && !["available", "empty"].includes(result.status))) && <button type="button" className="iclr-button" onClick={() => { setResult(null); setError(null); setAttempt(value => value + 1); }}>重新获取</button>}
      {review?.sections.map(section => <section key={section.field}><h4>{section.label}</h4><p>{section.text}</p></section>)}
      {review && <p className="iclr-review-text-source">公开评价采集：{new Date(result.retrieved_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}（北京时间）。表格评分使用原有快照。</p>}
      <a href={review?.url || paper.paper_url || `https://openreview.net/forum?id=${paper.id}`} target="_blank" rel="noopener noreferrer">在 OpenReview 查看评价 ↗</a>
    </div>
    </td></tr>}
  </>;
}
