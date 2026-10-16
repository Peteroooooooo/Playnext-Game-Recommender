import { useId, useRef, useState } from "react";
import type { Card, CardActionKind, FeedbackKind } from "../api";
import type { CardNote } from "../types";
import { FactReportForm } from "./FactReport";
import { ExtIcon } from "./Icons";
import { SeriesButton, SeriesList } from "./Series";

export interface ReasonView {
  text: string | null;
  source: string | null;
  pending: boolean;
}

interface Props {
  card: Card;
  index: number;
  group: boolean;
  memberNames: string[];
  reason: ReasonView;
  busy: boolean;
  onAction: (appid: number, action: CardActionKind, member?: number) => void;
  sessionId: string | null;
  /** Answer to the last 喜欢 / 不喜欢 on this card, if any. */
  note: CardNote | null;
}

export const FEEDBACK_ZH: Record<FeedbackKind, string> = { liked: "喜欢", disliked: "不喜欢" };

/** Bold lead-in for a feedback notice, e.g. "小李：不喜欢". */
export function noteLabel(note: CardNote, group: boolean, memberNames: string[], withName = false): string {
  const prefix = [
    group ? (memberNames[note.member] ?? `成员 ${note.member + 1}`) : "",
    withName && note.name ? `《${note.name}》` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return prefix ? `${prefix}：${FEEDBACK_ZH[note.action]}` : FEEDBACK_ZH[note.action];
}

function Kind({ children }: { children: string }) {
  return <span className="kind">〔{children}〕</span>;
}

const normName = (s: string) => s.toLowerCase().replace(/[\s\p{P}\p{S}]/gu, "");

/**
 * Does a `lineage` line name the same two games as `lineage_path` (anchor → … → this card)?
 * The path uses the database's English names and lineage lines use display names, so the anchor is matched
 * against the path's first step or colike.anchor (the same anchor game); when unsure, keep the line.
 */
function sameGamesAsPath(line: string, path: string, card: Card): boolean {
  const steps = path
    .split(/\s*—[^→]*→\s*/)
    .map(normName)
    .filter(Boolean);
  if (steps.length < 2) return false;
  const starts = new Set([steps[0], normName(card.colike?.anchor ?? "")].filter(Boolean));
  const ends = new Set([steps[steps.length - 1], normName(card.name), normName(card.name_en ?? "")].filter(Boolean));
  const games = Array.from(line.matchAll(/《([^》]+)》/g), (m) => normName(m[1]));
  if (!games.length || !starts.has(games[0])) return false;
  return games.length > 1 ? ends.has(games[games.length - 1]) : line.includes("本作");
}

function Tags({ items, tone }: { items: string[]; tone?: "dim" | "bad" }) {
  return (
    <>
      {items.map((t) => (
        <span className={`tag${tone ? ` ${tone}` : ""}`} key={t}>
          {t}
        </span>
      ))}
    </>
  );
}

/** 喜欢 / 不喜欢: two small buttons alone, a per-member menu in group mode. */
function RateControls({
  card,
  group,
  memberNames,
  busy,
  onAction,
}: Pick<Props, "card" | "group" | "memberNames" | "busy" | "onAction">) {
  const menuRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);

  if (!group || memberNames.length === 0) {
    return (
      <div className="rate" role="group" aria-label={`你对《${card.name}》的口味反馈，会用于以后的推荐`}>
        {(Object.keys(FEEDBACK_ZH) as FeedbackKind[]).map((k) => (
          <button type="button" className="link sm" key={k} disabled={busy} onClick={() => onAction(card.appid, k, 0)}>
            {FEEDBACK_ZH[k]}
          </button>
        ))}
      </div>
    );
  }

  function rate(member: number, k: FeedbackKind) {
    if (menuRef.current) menuRef.current.open = false;
    summaryRef.current?.focus();
    onAction(card.appid, k, member);
  }

  return (
    <details className="owned-menu rate-menu" ref={menuRef}>
      <summary className="link sm" ref={summaryRef}>
        喜欢 / 不喜欢
      </summary>
      <div className="menu rate-list" role="group" aria-label={`谁喜欢或不喜欢《${card.name}》`}>
        {memberNames.map((n, i) => (
          <div className="rate-row" key={i}>
            <span>{n}</span>
            {(Object.keys(FEEDBACK_ZH) as FeedbackKind[]).map((k) => (
              <button type="button" key={k} disabled={busy} aria-label={`${n}${FEEDBACK_ZH[k]}`} onClick={() => rate(i, k)}>
                {FEEDBACK_ZH[k]}
              </button>
            ))}
          </div>
        ))}
      </div>
    </details>
  );
}

export function GameCard({ card, index, group, memberNames, reason, busy, onAction, sessionId, note }: Props) {
  const uid = useId();
  const [imgOk, setImgOk] = useState(true);
  const [seriesOpen, setSeriesOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportDone, setReportDone] = useState(false);
  const reportBtnRef = useRef<HTMLButtonElement>(null);
  const folded = card.same_series_folded ?? [];
  const alternatives = card.setup?.alternatives ?? [];
  const lineagePath = card.lineage_path?.text ? card.lineage_path : null;
  const lineage = (card.lineage ?? []).filter((l) => !lineagePath || !sameGamesAsPath(l, lineagePath.text, card));

  function closeReport(sent: boolean) {
    setReportOpen(false);
    setReportDone(sent);
    reportBtnRef.current?.focus();
  }
  const like = card.like ?? {};
  const meta = [card.name_en && card.name_en !== card.name ? card.name_en : null, card.year, card.developer]
    .filter(Boolean)
    .join(" · ");
  const titleId = `card-${card.appid}-title`;
  const shared = like.shared_core_tags ?? [];
  const feelHits = like.feel_hits ?? [];
  const feelBad = like.feel_bad ?? [];

  return (
    <article className={`card${imgOk ? "" : " no-cover"}`} aria-labelledby={titleId}>
      {imgOk && (
        <div className="cover">
          <img
            src={card.header}
            alt={card.name}
            loading="lazy"
            decoding="async"
            width={460}
            height={215}
            onError={() => setImgOk(false)}
          />
          <em aria-hidden="true">{index + 1}</em>
        </div>
      )}
      <div className="card-main">
        <div className="card-top">
          <div>
            <h3 id={titleId}>
              <span className="sr-only">第 {index + 1} 名：</span>
              {card.name}
            </h3>
            {meta && <div className="meta">{meta}</div>}
          </div>
          <a className="link store" href={card.store_url} target="_blank" rel="noopener noreferrer">
            Steam 商店页 <ExtIcon />
            <span className="sr-only">（新窗口打开）</span>
          </a>
        </div>

        {group && card.setup && (
          <div className="mode-row">
            <span className="pill accent">{card.setup.mode_text}</span>
          </div>
        )}

        <div className="reason-wrap" aria-live="polite" aria-busy={reason.pending}>
          {reason.text ? (
            <p className={`reason${reason.pending ? " pending" : ""}`}>
              {reason.text}
              {reason.source === "llm" && <span className="kind">〔AI 根据下列事实撰写〕</span>}
            </p>
          ) : reason.pending ? (
            <p className="reason pending">推荐理由生成中…</p>
          ) : null}
          {reason.pending && reason.text && <span className="gen">生成中…</span>}
        </div>

        <dl className="facts">
          {(shared.length > 0 || feelHits.length > 0 || like.quote) && (
            <div>
              <dt>像在哪</dt>
              <dd>
                {shared.length > 0 && (
                  <span className="fact-line">
                    {like.anchor ? <>和《{like.anchor}》都有：</> : <>核心玩法：</>}
                    <Tags items={shared} />
                  </span>
                )}
                {feelHits.length > 0 && (
                  <span className="fact-line">
                    你想要的感觉：
                    <Tags items={feelHits} />
                  </span>
                )}
                {like.quote && (
                  <blockquote className="quote">
                    <span className="muted">介绍原句：</span>“{like.quote}”
                  </blockquote>
                )}
                <Kind>Steam 标签</Kind>
              </dd>
            </div>
          )}
          {feelBad.length > 0 && (
            <div>
              <dt>注意</dt>
              <dd>
                带有你不想要的：
                <Tags items={feelBad} tone="bad" />
              </dd>
            </div>
          )}
          {card.diff && (card.diff.more.length > 0 || card.diff.less.length > 0) && (
            <div>
              <dt>差在哪</dt>
              <dd>
                {card.diff.more.length > 0 && (
                  <span className="fact-line">
                    比《{card.diff.anchor}》多了：
                    <Tags items={card.diff.more} />
                  </span>
                )}
                {card.diff.less.length > 0 && (
                  <span className="fact-line">
                    少了：
                    <Tags items={card.diff.less} tone="dim" />
                  </span>
                )}
                <Kind>标签对比</Kind>
              </dd>
            </div>
          )}
          {card.colike && (
            <div>
              <dt>同好</dt>
              <dd>
                {card.colike.text}
                <Kind>事实</Kind>
              </dd>
            </div>
          )}
          {(lineagePath || lineage.length > 0) && (
            <div>
              <dt>血统</dt>
              <dd>
                {lineagePath && (
                  <span className="fact-line lineage-path">
                    {lineagePath.text}
                    {lineagePath.source && <small className="src">{lineagePath.source}</small>}
                  </span>
                )}
                {lineage.length > 0 && (
                  <ul className="plain-list">
                    {lineage.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                )}
                <Kind>事实</Kind>
              </dd>
            </div>
          )}
          <div>
            <dt>口碑</dt>
            <dd>
              {card.rating.text}
              {card.rating.below_floor && <span className="pill warn">评价偏少或褒贬不一</span>}
              <Kind>主观</Kind>
            </dd>
          </div>
          {card.mechanics_note && (
            <div>
              <dt>玩法</dt>
              <dd>
                <span className="pill warn">{card.mechanics_note}</span>
                <Kind>事实</Kind>
              </dd>
            </div>
          )}
          {card.time_to_beat && (
            <div>
              <dt>时长</dt>
              <dd>
                {card.time_to_beat}
                <Kind>事实</Kind>
              </dd>
            </div>
          )}
          {!group && card.library && (
            <div>
              <dt>库状态</dt>
              <dd>
                <span className={`pill ${card.library === "未拥有" ? "neutral" : "good"}`}>{card.library}</span>
                {card.library_hint && <span className="muted"> {card.library_hint}</span>}
              </dd>
            </div>
          )}
          {group && card.library_hint && (
            <div>
              <dt>库</dt>
              <dd>{card.library_hint}</dd>
            </div>
          )}
          {card.unknown && card.unknown.length > 0 && (
            <div>
              <dt>待确认</dt>
              <dd>
                {card.unknown.map((w) => (
                  <span className="pill warn" key={w}>
                    {w}
                  </span>
                ))}
              </dd>
            </div>
          )}
        </dl>

        {folded.length > 0 && (
          <div className="folded">
            <SeriesButton
              className="series-btn"
              count={folded.length}
              suffix="，已合并"
              open={seriesOpen}
              onToggle={() => setSeriesOpen((o) => !o)}
              controls={`${uid}-series`}
            />
            <SeriesList id={`${uid}-series`} names={folded} count={folded.length} open={seriesOpen} />
          </div>
        )}

        {group && card.setup && (
          <div className="plan">
            <div>
              <h4>怎么开局</h4>
              <ol>
                {card.setup.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
            </div>
            <div className="pay">
              <h4>谁买谁免</h4>
              {card.setup.purchase && <p>{card.setup.purchase}</p>}
              {alternatives.length > 0 && (
                <div className="alts">
                  <span className="muted">其他方案</span>
                  <ul className="plain-list">
                    {alternatives.map((a) => (
                      <li key={a}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}
              {card.setup.controller && <p className="muted">手柄：{card.setup.controller}</p>}
              {card.setup.friends_pass && <p className="muted">{card.setup.friends_pass}</p>}
            </div>
            <p className="src">{card.setup.note}</p>
          </div>
        )}

        <div className="card-foot">
          <div className="price">
            <span className="price-text mono">{card.price.text}</span>
            {card.price.near_low && <span className="pill good">接近史低</span>}
            <Kind>事实，仅陈述</Kind>
            {card.price.note && <span className="src">{card.price.note}</span>}
          </div>
          <div className="actions">
            <button type="button" className="link" disabled={busy} onClick={() => onAction(card.appid, "played")}>
              玩过了
            </button>
            <button type="button" className="link" disabled={busy} onClick={() => onAction(card.appid, "not_interested")}>
              不感兴趣
            </button>
            {group && memberNames.length > 0 && (
              <details className="owned-menu">
                <summary className="link">我有这款</summary>
                <div className="menu" role="group" aria-label={`谁已经有《${card.name}》`}>
                  {memberNames.map((n, i) => (
                    <button type="button" key={i} disabled={busy} onClick={() => onAction(card.appid, "owned", i)}>
                      {n}已拥有
                    </button>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>

        <div className="card-more">
          <div className="card-more-row">
            <RateControls card={card} group={group} memberNames={memberNames} busy={busy} onAction={onAction} />
            <button
              ref={reportBtnRef}
              type="button"
              className="link sm"
              aria-expanded={reportOpen}
              aria-controls={reportOpen ? `${uid}-report` : undefined}
              onClick={() => {
                setReportDone(false);
                setReportOpen((o) => !o);
              }}
            >
              事实有误？
            </button>
          </div>
          <div role="status">
            {note && (
              <p className={`notice${note.saved ? " info" : ""} card-note`}>
                <b>{noteLabel(note, group, memberNames)}</b>
                <span>{note.text}</span>
              </p>
            )}
            {reportDone && <p className="notice card-note">已记录，下次刷新数据时会和源数据核对</p>}
          </div>
          {reportOpen && (
            <FactReportForm
              id={`${uid}-report`}
              appid={card.appid}
              gameName={card.name}
              sessionId={sessionId}
              onSent={() => closeReport(true)}
              onCancel={() => closeReport(false)}
            />
          )}
        </div>
      </div>
    </article>
  );
}
