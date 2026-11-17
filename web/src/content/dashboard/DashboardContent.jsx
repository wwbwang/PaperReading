import React, { useEffect, useMemo, useState } from "react";
import { DataComponent, MetricCard, Section, useDataApp } from "../../data-app-public.jsx";
import { binLabel, exactHistogram, meanLabel, histogram, pageOf, selectPapers, STATUS_LABELS } from "./paper-data.mjs";
import { loadKeywords, loadPaperDetails } from "./paper-loader.mjs";
import { usePaperSearch } from "./usePaperSearch.mjs";
import { ReviewTable } from "./ReviewPreview.jsx";
import { TopicCloud } from "./TopicCloud.jsx";
import { AbstractText } from "./AbstractText.jsx";
import "./iclr.css";

const number = value => value.toLocaleString("zh-CN");
const score = value => value === null ? "—" : value.toFixed(2);
const FUZZY_SCOPES = { all: "全部（标题 + Keywords + 摘要）", both: "标题 + Keywords", keywords: "只查 Keywords", title: "只查标题", abstract: "只查摘要" };

function Keywords({ text = "", onSelect }) {
  const values = text.split(";").map(value => value.trim()).filter(Boolean);
  return <div className="iclr-keywords" aria-label="论文关键词">{values.map((value, index) =>
    <button key={index} type="button" className="iclr-keyword" onClick={() => onSelect(value)} title={`按关键词筛选：${value}`}>{value}</button>)}</div>;
}

function Scores({ paper, positiveThreshold }) {
  const values = JSON.parse(paper.ratings_json);
  return <div className="iclr-scores" aria-label={`审稿人评分：${values.map(v => v ?? "缺失").join("、") || "无评分"}`}>
    {values.length ? values.map((value, index) => <span key={index}
      className={`iclr-score-chip ${value === null ? "is-missing" : value >= positiveThreshold ? "is-positive" : ""}`}>{value ?? "—"}</span>)
      : <span className="iclr-muted">无公开评分</span>}
  </div>;
}

function PaperDetails({ paper, metadata, keywords, keywordError, onKeywordSelect }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setDetail(null); setError(null);
    loadPaperDetails(metadata, paper).then(value => { if (active) setDetail(value); })
      .catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [metadata, paper, attempt]);
  if (error) return <div className="iclr-details" role="alert">{error} <button className="iclr-button" onClick={() => setAttempt(attempt + 1)}>重试</button></div>;
  if (!detail) return <div className="iclr-details iclr-muted" role="status">正在加载摘要与评分详情…</div>;
  const reviews = JSON.parse(detail.reviews_json);
  const reviewFields = metadata.reviewFields;
  return <div className="iclr-details" data-reviewed-rows="papers">
    <div className="iclr-detail-links">
      <a href={detail.paper_url} target="_blank" rel="noopener noreferrer">{detail.paper_url.includes("openreview.net") ? "OpenReview" : "论文原始页面"} ↗</a>
      {detail.pdf_url && <a href={detail.pdf_url} target="_blank" rel="noopener noreferrer">论文 PDF ↗</a>}
      <span className="iclr-muted">{paper.id}</span>
    </div>
    <h3>作者</h3><p>{detail.authors?.length ? detail.authors.join("；") : (!metadata.venue || metadata.venue === "iclr") && metadata.year === 2027 ? "当前快照未提供公开作者名单；本届在双盲审稿结束后公开作者身份。" : "当前快照未提供公开作者信息。"}</p>
    <h3>Keywords</h3>{keywordError ? <p role="alert">{keywordError} 请点击列表上方“重试关键词”。</p> : keywords === undefined ? <p className="iclr-muted">正在加载关键词…</p> : keywords ? <Keywords text={keywords} onSelect={onKeywordSelect} /> : <p className="iclr-muted">来源未提供关键词。</p>}
    <h3>摘要</h3><AbstractText text={detail.abstract} />
    <h3>审稿人评分</h3>
    {reviews.length ? <ReviewTable key={paper.id} paper={{ ...paper, paper_url: detail.paper_url }}
      reviews={reviews} fields={reviewFields} metadata={metadata} />
      : <p className="iclr-muted">当前来源未提供这篇论文的公开评分或审稿正文；缺失评分不计为零分。</p>}
  </div>;
}

function Distribution({ bins, selection, onSelect, scale, exact }) {
  const [hovered, setHovered] = useState(null);
  const maximum = Math.max(1, ...bins.map(bin => bin.count));
  const step = 10 ** Math.floor(Math.log10(maximum));
  const ceiling = Math.ceil(maximum / step) * step;
  const selected = selection !== "all" && selection !== "missing";
  const active = bins.find(bin => bin.bin === (hovered ?? selection));
  return <div className="iclr-distribution">
    <div className="iclr-chart-caption" aria-live="polite">
      <span>{exact ? "每个精确均分一根柱 · 点击查看对应论文" : "每档 0.5 分 · 点击柱子查看论文"}</span>
      {active ? <strong>{active.range} · {number(active.count)} 篇 · {(active.share * 100).toFixed(2)}%</strong>
        : <span className="iclr-muted">纵轴：论文数量</span>}
    </div>
    <div className="iclr-chart-scroll">
      <div className="iclr-histogram" data-reviewed-rows="papers" style={exact ? { minWidth: Math.max(760, bins.length * 35 + 56) } : undefined}>
        <div className="iclr-y-axis" aria-hidden="true">{[1, .75, .5, .25, 0].map(fraction => <span key={fraction}>{number(Math.round(ceiling * fraction))}</span>)}</div>
        <div className="iclr-plot" role="group" aria-label={`平均分分布，${bins.length} 个${exact ? "精确均分" : "半分区间"}`}>
          <div className="iclr-grid-lines" aria-hidden="true">{[0, 1, 2, 3, 4].map(i => <span key={i} />)}</div>
          <div className={`iclr-bars ${exact ? "is-exact" : ""}`} style={{ gridTemplateColumns: `repeat(${bins.length}, minmax(0, 1fr))` }}>
            {/* Exact means use reduced fractions as keys, independent of display rounding. */}
            {bins.map(bin => <button key={bin.bin} type="button"
              className={`iclr-bin ${selection === bin.bin ? "is-selected" : ""} ${selected && selection !== bin.bin ? "is-dimmed" : ""}`}
              aria-pressed={selection === bin.bin}
              aria-label={`${bin.range} 分，${bin.count} 篇，占有评分论文 ${(bin.share * 100).toFixed(2)}%，查看${exact ? "该均分" : "该区间"}论文`}
              title={`${bin.range} 分 · ${number(bin.count)} 篇`}
              onMouseEnter={() => setHovered(bin.bin)} onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(bin.bin)} onBlur={() => setHovered(null)}
              onClick={() => onSelect(selection === bin.bin ? "all" : bin.bin)}>
              <span className="iclr-bin-body">
                <span className="iclr-bin-bar" style={{ height: `${100 * bin.count / ceiling}%` }}>
                  <span className="iclr-bin-count">{number(bin.count)}</span>
                </span>
              </span>
              <span className="iclr-bin-label">{exact ? bin.range : (scale.min + bin.bin / 2).toFixed(1)}</span>
            </button>)}
          </div>
        </div>
      </div>
    </div>
    <p className="iclr-chart-note">{exact
      ? `原始评分 ${scale.min}–${scale.max} 分。横轴为精确均分类别，按数值从低到高等距排列；显示保留两位小数，计数和筛选使用原始精确均分。相同均分合并，不同均分分别计数；无评分单独列出。`
      : <>原始评分 {scale.min}–{scale.max} 分，未换算为十分制。横轴为区间下界，左闭右开；末档 {binLabel(bins.length - 1, scale)} 包含 {scale.max}。分档使用未四舍五入的平均分。</>}</p>
  </div>;
}

export function DashboardContent() {
  const { snapshot, queries, visible } = useDataApp();
  const allRows = queries.papers.rows;
  const metadata = snapshot.iclr;
  const scale = metadata.ratingScale;
  const venue = metadata.venue || "iclr";
  const iclr = venue === "iclr";
  const exact = metadata.exactScores ?? metadata.year === 2027;
  const hasRatings = allRows.some(row => row.rating_count > 0);
  const blind = iclr && metadata.year === 2027;
  const label = value => exact ? meanLabel(value) : binLabel(value, scale);
  const statuses = useMemo(() => [...new Set(allRows.map(row => row.status))], [allRows]);
  const [input, setInput] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [keywordScope, setKeywordScope] = useState("all");
  const [authorInput, setAuthorInput] = useState("");
  const [topics, setTopics] = useState([]);
  const topicKeys = useMemo(() => topics.map(topic => topic.key), [topics]);
  const toggleTopic = topic => setTopics(values => values.some(value => value.key === topic.key)
    ? values.filter(value => value.key !== topic.key) : values.length < 12 ? [...values, topic] : values);
  const [listInput, setListInput] = useState("");
  const query = input.trim(), keywordQuery = keywordInput.trim(), authorQuery = authorInput.trim(), listQuery = listInput.trim();
  const selectKeyword = value => setKeywordInput(value);
  const [status, setStatus] = useState("all");
  const [selection, setSelection] = useState("all");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState(null);
  const search = usePaperSearch(metadata, query, keywordQuery, keywordScope, authorQuery, topicKeys);
  const listSearch = usePaperSearch(metadata, listQuery);
  const searching = search.loading;
  const searchError = search.error;
  const retrySearch = search.retry;
  useEffect(() => { setPage(0); setExpanded(null); }, [query, keywordQuery, keywordScope, authorQuery, topicKeys, listQuery, status, selection, order]);
  const baseRows = useMemo(() => allRows.filter(row => (status === "all" || row.status === status)
    && (!search.active || search.ids?.has(row.id))), [allRows, status, search.active, search.ids]);
  const bins = useMemo(() => exact ? exactHistogram(baseRows, allRows) : histogram(baseRows, scale), [baseRows, allRows, scale, exact]);
  const selectedRows = useMemo(() => selectPapers(baseRows, selection, order), [baseRows, selection, order]);
  const matching = useMemo(() => listSearch.active ? selectedRows.filter(row => listSearch.ids?.has(row.id)) : selectedRows,
    [selectedRows, listSearch.active, listSearch.ids]);
  const pagination = pageOf(matching, page);
  const pageIds = pagination.rows.map(row => row.id).join(",");
  const [keywords, setKeywords] = useState({});
  const [keywordError, setKeywordError] = useState(null);
  const [keywordAttempt, setKeywordAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setKeywords({}); setKeywordError(null);
    loadKeywords(metadata, pageIds ? pageIds.split(",") : [], controller.signal)
      .then(value => { if (!controller.signal.aborted) setKeywords(value); })
      .catch(error => { if (!controller.signal.aborted) setKeywordError(error.message); });
    return () => controller.abort();
  }, [metadata, pageIds, keywordAttempt]);
  const scored = bins.reduce((sum, bin) => sum + bin.count, 0);
  const missing = baseRows.length - scored;
  const scopeFilters = [
    ...(status !== "all" ? [{ id: "status", label: "投稿状态", value: status }] : []),
    ...(query.trim() ? [{ id: "search", label: "标题或摘要", value: query.trim() }] : []),
    ...(keywordQuery.trim() ? [{ id: "keywords", label: FUZZY_SCOPES[keywordScope], value: keywordQuery.trim() }] : []),
    ...(authorQuery ? [{ id: "authors", label: "作者", value: authorQuery }] : []),
    ...topics.map(topic => ({ id: `topic-${topic.key}`, label: "主题 Keywords", value: topic.label })),
  ];
  const tableFilters = [...scopeFilters, ...(selection === "all" ? [] : [{ id: "score-range", label: exact ? "精确平均分" : "平均分区间", value: selection === "missing" ? "无评分" : label(selection) }]),
    ...(listQuery.trim() ? [{ id: "selection-search", label: "当前结果内搜索", value: listQuery.trim() }] : [])];
  const selectionLabel = selection === "all" ? "全部论文" : selection === "missing" ? "无评分论文" : `${label(selection)} 分`;
  const retrieved = new Date(snapshot.iclr.retrievedAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
  if (metadata.datasetStatus && !["available", "existing"].includes(metadata.datasetStatus)) return <article className="iclr-dashboard">
    <nav className="iclr-library-nav" aria-label="论文库导航"><a href="/">← 论文库首页</a><div><span>{metadata.label}</span>{[2025, 2026, 2027].map(year => <a key={year} href={`/${venue}/${year}/`} aria-current={metadata.year === year ? "page" : undefined}>{year}</a>)}</div></nav>
    <Section id="coverage-heading" title={`${metadata.conference} · ${metadata.datasetStatus === "not_held" ? "本年份不举办" : "公开数据暂未取得"}`}>
      <p className="iclr-source-note">{metadata.coverageMessage}</p>
      <p>已保存来源检查记录。可在<a href={metadata.homepage} target="_blank" rel="noopener noreferrer">官方网站 ↗</a>核实，后续可重新运行本地采集器更新。</p>
      <p className="iclr-muted">最近检查：{retrieved}（北京时间）。此状态不表示论文数量为零。</p>
    </Section>
  </article>;
  return <article className="iclr-dashboard">
    <nav className="iclr-library-nav" aria-label="论文库导航"><a href="/">← 论文库首页</a><div><span>{metadata.label || "ICLR"}</span>{[2025, 2026, 2027].map(year => <a key={year} href={`/${venue}/${year}/`} aria-current={metadata.year === year ? "page" : undefined}>{year}</a>)}</div></nav>
    <div className="iclr-source-note"><strong>{metadata.conference} {metadata.kind === "journal" ? "期刊" : metadata.kind === "workshop" ? "Workshop" : "主会"}</strong> · {hasRatings ? `原始评分 ${scale.min}–${scale.max} 分 · ` : "来源未提供公开评分 · "}{metadata.source} · 快照 {retrieved}（北京时间）{metadata.officialCoverageVerified ? "" : " · 尚未确认官方全量覆盖"}</div>
    {metadata.coverageMessage && <p className="iclr-author-note">{metadata.coverageMessage}</p>}
    <div className="iclr-filters">
      <label className="iclr-search"><span>搜索论文</span><input type="search" name="paper-search" maxLength={500} value={input} onChange={event => setInput(event.target.value)} placeholder="搜索标题或摘要…" /></label>
      <label className="iclr-keyword-filter"><span>论文模糊查询</span><input type="search" name="keywords" maxLength={500} value={keywordInput} onChange={event => setKeywordInput(event.target.value)} aria-describedby="fuzzy-search-scope" placeholder="多个词同时匹配，词序不限…" /></label>
      <label><span>模糊查询范围</span><select name="keyword-scope" value={keywordScope} onChange={event => setKeywordScope(event.target.value)}>
        {Object.entries(FUZZY_SCOPES).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select></label>
      <label className="iclr-author-filter"><span>作者搜索</span><input type="search" name="authors" maxLength={500} value={authorInput}
        onChange={event => setAuthorInput(event.target.value)} disabled={!metadata.authorPaperCount} aria-describedby="author-search-availability"
        placeholder={metadata.authorPaperCount ? "作者姓名，支持部分匹配…" : blind ? "作者尚未公开（双盲审稿中）" : "当前快照未提供公开作者"} /></label>
      <label><span>投稿状态</span><select name="paper-status" value={status} onChange={event => setStatus(event.target.value)}>
        <option value="all">全部状态</option>{statuses.map(value => <option key={value} value={value}>{STATUS_LABELS[value] || value}</option>)}
      </select></label>
      {(input || keywordInput || authorInput || topics.length > 0 || keywordScope !== "all" || listInput || status !== "all" || selection !== "all") && <button type="button" className="iclr-button" onClick={() => { setInput(""); setKeywordInput(""); setAuthorInput(""); setTopics([]); setKeywordScope("all"); setListInput(""); setStatus("all"); setSelection("all"); }}>重置筛选</button>}
    </div>
    <p id="fuzzy-search-scope" className="iclr-author-note iclr-muted">检索范围：{FUZZY_SCOPES[keywordScope]}。多个词须全部出现，可分布在不同字段；忽略大小写和词序，不自动扩展同义词。左侧“搜索论文”按连续文字匹配。</p>
    <p id="author-search-availability" className="iclr-author-note iclr-muted">{metadata.authorPaperCount
      ? `${number(metadata.authorPaperCount)} / ${number(allRows.length)} 篇有作者信息；支持姓名部分匹配，多个词需匹配同一位作者。`
      : blind
        ? <>本届快照尚无会议公开作者名单，作者搜索暂不可用。<a href="https://blog.iclr.cc/2026/09/02/submission-policies-for-iclr-2027/" target="_blank" rel="noopener noreferrer">官方政策</a>说明作者身份在双盲审稿结束后公开；名单公开并更新数据后自动启用。</>
        : "当前年份的快照未提供会议公开作者信息，暂不可按作者搜索。"}</p>
    {topics.length > 0 && <div className="iclr-topic-filters" aria-label="已选主题">
      <span>主题同时包含：</span>{topics.map(topic => <button key={topic.key} type="button" className="iclr-topic-pill"
        aria-label={`移除主题 ${topic.label}`} onClick={() => toggleTopic(topic)}>{topic.label}<span aria-hidden="true">×</span></button>)}
      <button type="button" className="iclr-button" onClick={() => setTopics([])}>清除主题</button>
      <span className="iclr-muted">按完整 Keywords 匹配，忽略大小写、空格和连字符差异。</span>
    </div>}
    {searching && <p className="iclr-search-status iclr-muted" role="status">正在搜索论文、关键词和作者…</p>}
    {searchError && <p role="alert">{searchError} <button className="iclr-button" onClick={retrySearch}>重试搜索</button></p>}
    <div className="iclr-metrics">
      {[
        ["paper-total", "论文总数", baseRows.length], ["paper-scored", "有评分论文", scored], ["paper-unscored", "无评分论文", missing],
      ].map(([id, title, count]) => visible(id) && <MetricCard key={id} id={id} queryId="papers" title={title} value={number(count)}
        loading={searching} loadingError={searchError || undefined} onRetry={retrySearch}
        displayRows={[{ category: title, count }]} sourceRows={baseRows} scopeFilters={scopeFilters} />)}
    </div>
    {hasRatings && <Section id="score-distribution-heading" title={exact ? "精确平均分分布" : "平均分分布"} spacing="after-metrics">
      {visible("score-distribution") && <DataComponent id="score-distribution" queryId="papers" kind="custom" variant="card"
        title="平均分分布" showHeading={false} loading={searching} loadingError={searchError || undefined} onRetry={retrySearch} displayRows={bins} sourceRows={baseRows} scopeFilters={scopeFilters}>
        <Distribution bins={bins} selection={selection} onSelect={setSelection} scale={scale} exact={exact} />
        <div className="iclr-range-controls">
          <button type="button" className={`iclr-button ${selection === "all" ? "is-active" : ""}`} aria-pressed={selection === "all"} onClick={() => setSelection("all")}>{exact ? "全部均分" : "全部区间"}</button>
          <button type="button" className={`iclr-button ${selection === "missing" ? "is-active" : ""}`} aria-pressed={selection === "missing"} onClick={() => setSelection("missing")}>无评分 · {number(missing)} 篇</button>
          {selection !== "all" && selection !== "missing" && <span className="iclr-selection-pill">已选 {label(selection)} <button type="button" aria-label={exact ? "清除均分选择" : "清除分数区间"} onClick={() => setSelection("all")}>×</button></span>}
        </div>
      </DataComponent>}
    </Section>}
    <Section id="topic-cloud-heading" title="主题词云">
      {visible("topic-cloud") && <TopicCloud metadata={metadata} rows={matching} selected={topics} onSelect={toggleTopic}
        scopeFilters={tableFilters} busy={searching || listSearch.loading} error={searchError || listSearch.error}
        retryScope={searchError ? retrySearch : listSearch.retry} />}
    </Section>
    <Section id="paper-list-heading" title="对应论文">
      {visible("paper-list") && <div className="iclr-list-search">
        <label><span>搜索当前筛选结果</span><input type="search" name="selection-search" maxLength={500} value={listInput}
          onChange={event => setListInput(event.target.value)} aria-describedby="selection-search-scope" placeholder="在已选论文中搜索标题或摘要…" /></label>
        {listInput && <button type="button" className="iclr-button" onClick={() => setListInput("")}>清除结果内搜索</button>}
        <p id="selection-search-scope" className="iclr-muted">{searchError ? "筛选范围暂不可用，请重试上方搜索。" : searching ? "正在更新筛选范围…" : `搜索范围：${metadata.conference} · 当前搜索、关键词、作者、状态及均分设置下的全部 ${number(selectedRows.length)} 篇论文（含所有分页）。`}</p>
        {listSearch.loading && <p className="iclr-list-search-status iclr-muted" role="status">正在搜索当前筛选结果…</p>}
        {listSearch.error && <p role="alert">{listSearch.error} <button className="iclr-button" onClick={listSearch.retry}>重试结果内搜索</button></p>}
      </div>}
      {visible("paper-list") && <DataComponent id="paper-list" queryId="papers" kind="table" title="对应论文" showHeading={false}
        loading={searching || listSearch.loading} loadingError={searchError || listSearch.error || undefined} onRetry={searchError ? retrySearch : listSearch.retry}
        displayRows={pagination.rows} sourceRows={matching} scopeFilters={tableFilters}>
        <div className="iclr-table-toolbar">
          <p aria-live="polite"><strong>{selectionLabel}</strong><span className="iclr-muted"> · {number(matching.length)} 篇</span></p>
          <label><span className="iclr-sr-only">排序方式</span><select value={order} onChange={event => setOrder(event.target.value)}>
            <option value="desc">平均分：从高到低</option><option value="asc">平均分：从低到高</option>
          </select></label>
        </div>
        {keywordError && <p role="alert">{keywordError} <button className="iclr-button" onClick={() => setKeywordAttempt(keywordAttempt + 1)}>重试关键词</button></p>}
        <div className="iclr-paper-scroll"><table className="iclr-paper-table" data-reviewed-rows="papers">
          <caption className="iclr-sr-only">{selectionLabel}，点击论文标题展开摘要和评分详情</caption>
          <thead><tr><th scope="col">论文 · 点击标题查看摘要</th><th scope="col" className="iclr-numeric">平均分</th><th scope="col">审稿人评分</th><th scope="col">投稿状态</th></tr></thead>
          <tbody>{pagination.rows.map(paper => <React.Fragment key={paper.id}>
            <tr className={expanded === paper.id ? "is-expanded" : ""}>
              <td><button className="iclr-paper-title" type="button" aria-expanded={expanded === paper.id} aria-controls={expanded === paper.id ? `details-${paper.id}` : undefined}
                onClick={() => setExpanded(expanded === paper.id ? null : paper.id)}><span className="iclr-expand-arrow" aria-hidden="true">{expanded === paper.id ? "−" : "+"}</span>{paper.title}</button>{keywords[paper.id] !== undefined ? <Keywords text={keywords[paper.id]} onSelect={selectKeyword} /> : <span className="iclr-muted">{keywordError ? "关键词加载失败" : "正在加载关键词…"}</span>}</td>
              <td className="iclr-numeric"><strong className="iclr-average" data-exact-mean={exact ? paper.bin : undefined} title={exact && paper.bin !== null ? `精确均分 ${meanLabel(paper.bin)}` : undefined}>{score(paper.rating_mean)}</strong><span className="iclr-rating-count">{paper.rating_count} 位评分</span></td>
              <td><Scores paper={paper} positiveThreshold={metadata.year === 2027 ? 3 : 6} /></td><td><span className="iclr-status" data-status={paper.status}>{STATUS_LABELS[paper.status] || paper.status}</span></td>
            </tr>
            {expanded === paper.id && <tr id={`details-${paper.id}`}><td colSpan={4}><PaperDetails paper={paper} metadata={metadata} keywords={keywords[paper.id]} keywordError={keywordError} onKeywordSelect={selectKeyword} /></td></tr>}
          </React.Fragment>)}</tbody>
        </table></div>
        {!matching.length && !searching && !listSearch.loading && !searchError && !listSearch.error && <div className="iclr-empty" role="status">{listSearch.active ? "当前筛选范围内没有匹配的论文，可清除结果内搜索或调整筛选条件。" : "没有符合当前筛选条件的论文。可切换均分或重置筛选。"}</div>}
        <nav className="iclr-pagination" aria-label="论文分页">
          <span className="iclr-muted">{matching.length ? `${number(pagination.page * 25 + 1)}–${number(pagination.page * 25 + pagination.rows.length)} / ${number(matching.length)} 篇` : "0 篇"} · 每页 25 篇</span>
          <div><button className="iclr-button" type="button" disabled={pagination.page === 0} onClick={() => { setPage(pagination.page - 1); setExpanded(null); }}>上一页</button>
            <span aria-live="polite">{pagination.page + 1} / {pagination.pages}</span>
            <button className="iclr-button" type="button" disabled={pagination.page + 1 >= pagination.pages} onClick={() => { setPage(pagination.page + 1); setExpanded(null); }}>下一页</button></div>
        </nav>
      </DataComponent>}
    </Section>
    <p className="iclr-footnote">{!iclr || metadata.year === 2025 ? "只展示当前公开来源已收录的记录；未提供的摘要、关键词和审稿信息保持缺失，录用状态以原始来源为准。" : metadata.year === 2027
      ? "ICLR 2027 正处于评审讨论阶段，评分可能更新。Active 表示审稿中，不代表已录用；缺失评分不作为零分计入均值。"
      : "ICLR 2026 评分包含真实 0 分，评审曾回退到 rebuttal 前状态；这些分数不代表逐轮讨论历史。"} PDF 链接尚未批量验证可访问性。</p>
  </article>;
}
