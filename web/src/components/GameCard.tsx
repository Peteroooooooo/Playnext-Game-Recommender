import { useState } from "react";
import type { Card, CardActionKind } from "../api";
import { ExtIcon } from "./Icons";

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
}

function Kind({ children }: { children: string }) {
  return <span className="kind">〔{children}〕</span>;
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

export function GameCard({ card, index, group, memberNames, reason, busy, onAction }: Props) {
  const [imgOk, setImgOk] = useState(true);
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
          {card.lineage && card.lineage.length > 0 && (
            <div>
              <dt>血统</dt>
              <dd>
                <ul className="plain-list">
                  {card.lineage.map((l) => (
                    <li key={l}>{l}</li>
                  ))}
                </ul>
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

        {card.same_series_folded && card.same_series_folded.length > 0 && (
          <details className="folded">
            <summary>同系列另有 {card.same_series_folded.length} 款，已合并</summary>
            <ul className="plain-list">
              {card.same_series_folded.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </details>
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
              {card.setup.controller && <p className="muted">手柄：{card.setup.controller}</p>}
              {card.setup.friends_pass && <p className="muted">{card.setup.friends_pass}</p>}
            </div>
            <p className="src">{card.setup.note}</p>
          </div>
        )}

        <div className="card-foot">
          <div className="price">
            <span className="price-text mono">{card.price.text}</span>
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
      </div>
    </article>
  );
}
