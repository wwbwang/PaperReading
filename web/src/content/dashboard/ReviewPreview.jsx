import React, { useEffect, useId, useState } from "react";
import { loadReviewText } from "./paper-loader.mjs";
import { AbstractText } from "./AbstractText.jsx";
import { additionalReviewerAliases, notesForReviewer } from "./review-matching.mjs";

export function ReviewTable({ paper, reviews, fields, metadata }) {
  const [result, setResult] = useState(null);
  const additional = additionalReviewerAliases(reviews, result?.reviews || []);
  return <>
    {additional.length > 0 && <p className="iclr-muted" role="status">新增 {additional.length} 位公开审稿人的评价；其评分不在当前快照中，以“—”显示。</p>}
    <div className="iclr-review-scroll"><table className="iclr-review-table">
      <caption className="iclr-sr-only">{paper.title} 的逐审稿人评分和公开评价</caption>
      <thead><tr><th>匿名审稿人</th>{fields.map(field => <th key={field}>{field === "rating" ? "总评分" : field[0].toUpperCase() + field.slice(1)}</th>)}</tr></thead>
      <tbody>{reviews.map((review, i) => <ReviewPreview key={`snapshot-${i}`} paper={paper}
        review={review} index={i} fields={fields} metadata={metadata} onLoaded={setResult} />)}
        {additional.map((alias, i) => <ReviewPreview key={alias} paper={paper}
          review={{ reviewer: alias }} index={reviews.length + i} fields={fields} metadata={metadata} onLoaded={setResult} />)}
      </tbody>
    </table></div>
  </>;
}

export function ReviewPreview({ paper, review: scores, index, fields, metadata, onLoaded }) {
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
    loadReviewText(metadata, paper.id).then(value => { if (active) { setResult(value); onLoaded?.(value); } })
      .catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [open, result, metadata, paper.id, attempt, onLoaded]);
  // Match the anonymous alias, never the position or score of a reviewer.
  const notes = notesForReviewer(result?.reviews || [], reviewer);
  const hasText = notes.some(note => note.sections.length > 0);
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
      {result?.stale && hasText && <p className="iclr-muted" role="status">{result.message}</p>}
      {result && !hasText && <p className="iclr-muted">{result.message || (result.status === "empty" ? "当前未获取到公开评价正文。" : "尚未取得与此匿名审稿人对应的评价正文。")}</p>}
      {(error || (result && !["available", "empty"].includes(result.status))) && <button type="button" className="iclr-button" onClick={() => { setResult(null); setError(null); setAttempt(value => value + 1); }}>重新获取</button>}
      {["verification_required", "login_required"].includes(result?.browser_status) && <p><a href="/browser/" target="_blank" rel="noopener noreferrer">打开当前机器的浏览器，完成验证或登录 ↗</a></p>}
      {notes.length > 1 && <p className="iclr-muted">此匿名审稿人对应 {notes.length} 条公开评价，分别列出；表格评分仍使用当前快照。</p>}
      {notes.map((note, i) => <div key={note.id} className="iclr-review-note" data-note-id={note.id}>
        {notes.length > 1 && <h4>公开评价 {i + 1} / {notes.length}</h4>}
        {note.sections.map(section => <section key={section.field}><h4>{section.label}</h4><AbstractText text={section.text} className="iclr-review-rich-text" fallback="" /></section>)}
        <a href={note.url} target="_blank" rel="noopener noreferrer">查看评价原始页面 ↗</a>
      </div>)}
      {hasText && <p className="iclr-review-text-source">公开评价采集：{new Date(result.retrieved_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}（北京时间）。表格评分使用原有快照。</p>}
      {!notes.length && <a href={paper.paper_url || `https://openreview.net/forum?id=${paper.id}`} target="_blank" rel="noopener noreferrer">查看评价原始页面 ↗</a>}
    </div>
    </td></tr>}
  </>;
}
