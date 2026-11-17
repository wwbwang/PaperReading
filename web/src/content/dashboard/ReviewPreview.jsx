import React, { useEffect, useId, useState } from "react";
import { loadReviewText } from "./paper-loader.mjs";
import { AbstractText } from "./AbstractText.jsx";

export function ReviewTable({ paper, reviews, fields, metadata }) {
  const [result, setResult] = useState(null);
  const aliases = new Set(reviews.map(review => review.reviewer));
  const additional = result?.reviews.filter(review => review.reviewer && !aliases.has(review.reviewer)) || [];
  return <>
    {additional.length > 0 && <p className="iclr-muted" role="status">新增 {additional.length} 位公开审稿人的评价；其评分不在当前快照中，以“—”显示。</p>}
    <div className="iclr-review-scroll"><table className="iclr-review-table">
      <caption className="iclr-sr-only">{paper.title} 的逐审稿人评分和公开评价</caption>
      <thead><tr><th>匿名审稿人</th>{fields.map(field => <th key={field}>{field === "rating" ? "总评分" : field[0].toUpperCase() + field.slice(1)}</th>)}</tr></thead>
      <tbody>{reviews.map((review, i) => <ReviewPreview key={`snapshot-${i}`} paper={paper}
        review={review} index={i} fields={fields} metadata={metadata} onLoaded={setResult} />)}
        {additional.map((review, i) => <ReviewPreview key={review.id} paper={paper}
          review={{ reviewer: review.reviewer }} index={reviews.length + i} fields={fields} metadata={metadata} onLoaded={setResult} />)}
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
      {result?.stale && review && <p className="iclr-muted" role="status">{result.message}</p>}
      {result && !review?.sections.length && <p className="iclr-muted">{result.message || (result.status === "empty" ? "当前未获取到公开评价正文。" : "尚未取得与此匿名审稿人唯一对应的评价正文。")}</p>}
      {(error || (result && !["available", "empty"].includes(result.status))) && <button type="button" className="iclr-button" onClick={() => { setResult(null); setError(null); setAttempt(value => value + 1); }}>重新获取</button>}
      {["verification_required", "login_required"].includes(result?.browser_status) && <p><a href="/browser/" target="_blank" rel="noopener noreferrer">打开当前机器的浏览器，完成验证或登录 ↗</a></p>}
      {review?.sections.map(section => <section key={section.field}><h4>{section.label}</h4><AbstractText text={section.text} className="iclr-review-rich-text" fallback="" /></section>)}
      {review && <p className="iclr-review-text-source">公开评价采集：{new Date(result.retrieved_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}（北京时间）。表格评分使用原有快照。</p>}
      <a href={review?.url || paper.paper_url || `https://openreview.net/forum?id=${paper.id}`} target="_blank" rel="noopener noreferrer">查看评价原始页面 ↗</a>
    </div>
    </td></tr>}
  </>;
}
