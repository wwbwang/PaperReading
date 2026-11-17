import React, { useMemo } from "react";
import katex from "../assets/katex/katex.mjs";
import { abstractParts, normalizeTex } from "./abstract-math.mjs";
import "../assets/katex/katex.css";

export function AbstractText({ text, className = "iclr-abstract", fallback = "来源未提供摘要。" }) {
  const parts = useMemo(() => abstractParts(text || fallback).map(part => {
    if (part.tex === undefined) return part;
    try {
      return { ...part, html: katex.renderToString(normalizeTex(part.tex), {
        displayMode: part.display, output: "htmlAndMathml", trust: false,
        throwOnError: true, strict: "ignore", maxExpand: 1000, maxSize: 20,
      }) };
    } catch {
      return { ...part, text: part.source };
    }
  }), [text, fallback]);

  return <div className={`iclr-rich-text ${className}`}>{parts.map((part, index) => part.html
    ? <span key={index} className={part.display ? "iclr-math-block" : "iclr-math-inline"}
        dangerouslySetInnerHTML={{ __html: part.html }} />
    : <React.Fragment key={index}>{part.text}</React.Fragment>)}</div>;
}
