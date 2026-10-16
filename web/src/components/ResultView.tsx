import { forwardRef, useState } from "react";
import type { CardActionKind, FailedItem, RecommendResult, ReasonsResponse } from "../api";
import type { CardNote } from "../types";
import { BackupList } from "./BackupList";
import { UnderstoodChips } from "./Chips";
import { GameCard, noteLabel, type ReasonView } from "./GameCard";
import { ArrowIcon } from "./Icons";

export type ReasonsState = "idle" | "loading" | "done" | "error";

interface Props {
  result: RecommendResult;
  reasons: ReasonsResponse;
  reasonsState: ReasonsState;
  busy: boolean;
  onAction: (appid: number, action: CardActionKind, member?: number) => void;
  cardNote: CardNote | null;
  followText: string;
  onFollowText: (t: string) => void;
  onFollowSubmit: () => void;
  followBusy: boolean;
  llm: boolean | null;
}

export const ResultView = forwardRef<HTMLTextAreaElement, Props>(function ResultView(props, followRef) {
  const {
    result: r,
    reasons,
    reasonsState,
    busy,
    onAction,
    cardNote,
    followText,
    onFollowText,
    onFollowSubmit,
    followBusy,
    llm,
  } = props;
  const [relaxPicked, setRelaxPicked] = useState<string | null>(null);
  const failed = r.failed ?? [];
  // A 不喜欢 can drop the card from the picks; then its notice goes above the cards.
  const strayNote = cardNote && !r.picks.some((c) => c.appid === cardNote.appid) ? cardNote : null;
  const group = r.understood.party_size > 1;
  const memberNames = r.understood.members.map((m) => m.name);
  const total = r.rules.length ? r.rules[0].pass + r.rules[0].fail + r.rules[0].unknown : null;
  const head = r.picks.length
    ? group
      ? `适合你们 ${r.understood.party_size} 个人的 ${r.picks.length} 款`
      : `为你挑了 ${r.picks.length} 款`
    : r.need_input
      ? "还差一点信息"
      : "按现在的条件，没有合适的游戏";

  function reasonFor(appid: number, own?: string): ReasonView {
    const got = reasons[String(appid)];
    if (got) return { text: got.reason || own || null, source: got.source, pending: false };
    return { text: own ?? null, source: own ? "template" : null, pending: reasonsState === "loading" };
  }

  return (
    <div className={`results${busy ? " refresh" : ""}`} aria-busy={busy}>
      <UnderstoodChips u={r.understood} />

      {r.notes.map((n) => (
        <p className="notice info" key={n} role="note">
          {n}
        </p>
      ))}

      <div className="res-head">
        <h2>{head}</h2>
        {r.rules.length > 0 && (
          <details className="funnel-box">
            <summary className="funnel">
              {total != null && (
                <span>
                  推荐库 <b>{total}</b> 款
                </span>
              )}
              <span aria-hidden="true">→</span>
              <span>
                过了 <b>{r.rules.length}</b> 条规则
              </span>
              <span aria-hidden="true">→</span>
              <span>
                推荐 <b>{r.picks.length}</b>
              </span>
              <span aria-hidden="true">·</span>
              <span>
                备选 <b>{r.backups.length}</b>
              </span>
              <span aria-hidden="true">·</span>
              <span>
                待确认 <b>{r.unknown.length}</b>
              </span>
              <span className="funnel-more">每条规则的明细</span>
            </summary>
            <div className="table-wrap">
              <table className="rules">
                <caption className="sr-only">硬规则筛选明细</caption>
                <thead>
                  <tr>
                    <th scope="col">规则</th>
                    <th scope="col">通过</th>
                    <th scope="col">不符合</th>
                    <th scope="col">待确认</th>
                  </tr>
                </thead>
                <tbody>
                  {r.rules.map((row) => (
                    <tr key={row.rule}>
                      <th scope="row">
                        {row.rule}
                        {row.relaxable && <span className="kind">可放宽</span>}
                      </th>
                      <td className="mono">{row.pass}</td>
                      <td className="mono">{row.fail}</td>
                      <td className="mono">{row.unknown}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">每条规则都对整个推荐库单独计数；内容雷区、语言和平台不会被自动放宽。</p>
          </details>
        )}
      </div>

      {r.need_input && (
        <div className="panel">
          <h3>{r.need_input}</h3>
          <p>可以在上面写一两款喜欢的游戏，或打开问卷点选，也可以连接 Steam 游戏库。</p>
        </div>
      )}

      {strayNote && (
        <p className={`notice${strayNote.saved ? " info" : ""}`} role="status">
          <b>{noteLabel(strayNote, group, memberNames, true)}</b>
          <span>{strayNote.text}</span>
        </p>
      )}

      {r.picks.length > 0 && (
        <div className="cards">
          {r.picks.map((c, i) => (
            <GameCard
              key={c.appid}
              card={c}
              index={i}
              group={group}
              memberNames={memberNames}
              reason={reasonFor(c.appid, c.reason)}
              busy={busy}
              onAction={onAction}
              sessionId={r.session_id}
              note={cardNote?.appid === c.appid ? cardNote : null}
            />
          ))}
        </div>
      )}
      {reasonsState === "error" && r.picks.length > 0 && (
        <p className="hint">推荐理由暂时没能生成，卡片上的事实不受影响。</p>
      )}

      {!r.picks.length && !r.need_input && r.relax.length > 0 && (
        <div className="panel">
          <h3>改下面任意一条就有得选</h3>
          <p>点一下会把这条改法放进下面的“继续改条件”，确认后再发送。内容雷区不会被放宽。</p>
          {r.relax.map((o, i) => {
            const text = o.changes.map((c) => c.text).join("，");
            return (
              <button
                type="button"
                className="fix"
                key={i}
                aria-pressed={relaxPicked === text}
                onClick={() => {
                  setRelaxPicked(text);
                  onFollowText(text);
                  if (followRef && typeof followRef !== "function") followRef.current?.focus();
                }}
              >
                <span>
                  {text}
                  {o.examples.length > 0 && <small className="muted ex-list">比如：{o.examples.join("、")}</small>}
                </span>
                <b>{o.count} 款可以玩</b>
              </button>
            );
          })}
          {relaxPicked && (
            <p className="notice info" role="status">
              已选：{relaxPicked}
              {llm === false ? "。自然语言修改暂不可用，请按这条手动调整问卷后重新推荐。" : "。在下面确认后发送。"}
            </p>
          )}
        </div>
      )}
      {!r.picks.length && !r.need_input && r.relax.length === 0 && (
        <div className="panel">
          <p>没有找到放宽后就能有结果的单一改法。可以去掉一些条件再试。</p>
        </div>
      )}

      {r.backups.length > 0 && <BackupList backups={r.backups} />}

      {r.unknown.length > 0 && (
        <section className="sub" aria-labelledby="unknown-title">
          <div className="sub-head">
            <h3 id="unknown-title">待确认</h3>
            <span className="hint">缺一项事实，没放进推荐，买之前请自己去商店页确认</span>
          </div>
          {r.unknown.map((u) => (
            <div className="pend" key={u.appid}>
              <h4>
                <a href={`https://store.steampowered.com/app/${u.appid}/`} target="_blank" rel="noopener noreferrer">
                  {u.name}
                  <span className="sr-only">（Steam 商店页，新窗口打开）</span>
                </a>
              </h4>
              <p className="why">
                {u.why.map((w) => (
                  <span className="pill warn" key={w}>
                    {w}
                  </span>
                ))}
              </p>
            </div>
          ))}
        </section>
      )}

      {failed.length > 0 && <FailedList items={failed} />}

      <section className="sub follow" aria-labelledby="follow-title">
        <div className="sub-head">
          <h3 id="follow-title">继续改条件</h3>
          <span className="hint">比如“预算改成 100”“别要恐怖的”“改成客厅 4 个人”</span>
        </div>
        {llm === false ? (
          <p className="notice warn">自然语言输入暂不可用，请改问卷后重新推荐。</p>
        ) : (
          <form
            className="composer small"
            onSubmit={(e) => {
              e.preventDefault();
              onFollowSubmit();
            }}
          >
            <label htmlFor="follow-text" className="sr-only">
              继续改条件
            </label>
            <textarea
              id="follow-text"
              ref={followRef}
              rows={1}
              maxLength={300}
              value={followText}
              placeholder="想改什么，直接说"
              onChange={(e) => onFollowText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (!followBusy) onFollowSubmit();
                }
              }}
            />
            <button className="send" type="submit" disabled={followBusy || !followText.trim()} aria-label="发送修改">
              <span className="lbl">{followBusy ? "修改中" : "改"}</span>
              <ArrowIcon />
            </button>
          </form>
        )}
      </section>
    </div>
  );
});

/** Games that would have ranked high but broke a hard condition (prototype: failedHtml). */
function FailedList({ items }: { items: FailedItem[] }) {
  return (
    <details className="failed">
      <summary>没通过的 {items.length} 款，看看为什么</summary>
      <ul className="fail-list">
        {items.map((f) => (
          <li className="fail-row" key={f.appid}>
            <a href={`https://store.steampowered.com/app/${f.appid}/`} target="_blank" rel="noopener noreferrer">
              {f.name}
              <span className="sr-only">（Steam 商店页，新窗口打开）</span>
            </a>
            <span className="why">
              {f.why.map((w) => (
                // Budget / price misses are softer than player-count or mode misses, as in the prototype.
                <span className={`pill ${/预算|价格/.test(w) ? "warn" : "bad"}`} key={w}>
                  {w}
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
