import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Backup, Card, CardActionKind, NearMiss, RelaxKey } from "../api";
import { useT } from "../i18n";
import { art, englishName, missLabel, priceLabel, revealCps, revealed, shortName, shortTime } from "../present";
import { FactReportForm } from "./FactReport";

export interface ReasonState {
  /** null while the LLM reason is still being written. */
  text: string | null;
  llm: boolean;
  /** performance.now() when it arrived; the reveal runs from there, also while the sheet is closed. */
  at: number;
}

export type SheetItem =
  | { kind: "pick"; card: Card; reason: ReasonState }
  | { kind: "backup"; backup: Backup }
  | { kind: "miss"; miss: NearMiss };

interface Props {
  item: SheetItem | null;
  group: boolean;
  busy: boolean;
  sessionId: string | null;
  onAction: (appid: number, action: CardActionKind) => void;
  onRelax: (key: RelaxKey) => void;
  onClose: () => void;
}

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const itemId = (i: SheetItem) => (i.kind === "pick" ? i.card.appid : i.kind === "backup" ? i.backup.appid : i.miss.appid);
const storeUrl = (appid: number) => `https://store.steampowered.com/app/${appid}/`;

export function Sheet({ item, group, busy, sessionId, onAction, onRelax, onClose }: Props) {
  const dlg = useRef<HTMLDialogElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const appid = item ? itemId(item) : null;

  useEffect(() => {
    const d = dlg.current;
    if (!d) return;
    if (item && !d.open) {
      d.showModal();
      d.querySelector<HTMLElement>("#s-title")?.focus({ preventScroll: true });
    } else if (!item && d.open) d.close();
  }, [item]);

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
  }, [appid]);

  return (
    <dialog
      className="sheet"
      ref={dlg}
      aria-labelledby="s-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === dlg.current) dlg.current.close();
      }}
    >
      <div className="sheet-scroll" ref={scroller}>
        {item?.kind === "pick" && (
          <PickBody key={item.card.appid} card={item.card} reason={item.reason} group={group} busy={busy} sessionId={sessionId} onAction={onAction} />
        )}
        {item?.kind === "backup" && <BackupBody key={item.backup.appid} b={item.backup} busy={busy} onAction={onAction} />}
        {item?.kind === "miss" && <MissBody key={item.miss.appid} m={item.miss} busy={busy} onRelax={onRelax} />}
      </div>
    </dialog>
  );
}

function Hero({ appid, name }: { appid: number; name: string }) {
  const t = useT();
  const [fb, setFb] = useState(false);
  return (
    <div className="s-hero">
      <img src={art(appid, fb ? "header.jpg" : "library_hero.jpg")} alt="" decoding="async" onError={() => setFb(true)} />
      <form method="dialog">
        <button className="close" aria-label={t.close(name)}>
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
            <path d="M2 2l8 8M10 2l-8 8" />
          </svg>
        </button>
      </form>
    </div>
  );
}

function Head({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <div className="s-head">
      <h2 id="s-title" tabIndex={-1}>
        {title}
      </h2>
      {sub && <div className="sub">{sub}</div>}
      <div className="s-actions">{children}</div>
    </div>
  );
}

const Tile = ({ k, v, s }: { k: string; v: string; s?: string | null }) => (
  <div className="tile">
    <div className="k">{k}</div>
    <div className="v">{v}</div>
    {s && <div className="s">{s}</div>}
  </div>
);

function StoreLink({ href }: { href: string }) {
  const t = useT();
  return (
    <a className="btn" href={href} target="_blank" rel="noopener noreferrer">
      {t.storeBtn}
      <span className="sr-only">{t.newWindow}</span>
    </a>
  );
}

/** Ticks once per frame while the reason is still being revealed. */
function useReveal(r: ReasonState): number {
  const full = r.text?.length ?? 0;
  const calc = () => (r.text == null ? 0 : reduced() ? full : revealed(r.text, performance.now() - r.at, revealCps(r.text)));
  const [n, setN] = useState(calc);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = calc();
      setN(v);
      if (v < full) raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [r]);
  return n;
}

function Why({ r }: { r: ReasonState }) {
  const t = useT();
  const n = useReveal(r);
  const writing = r.text == null || n < r.text.length;
  if (r.text == null) {
    return (
      <div aria-busy="true">
        <p className="wait">
          {t.writing}
          <span className="caret" aria-hidden="true" />
        </p>
      </div>
    );
  }
  const paras = r.text
    .slice(0, n)
    .split(/\n\s*\n/)
    .map((x) => x.trim())
    .filter(Boolean);
  if (writing && !paras.length) paras.push("");
  return (
    <div aria-busy={writing}>
      <span className="sr-only">{r.text}</span>
      <div aria-hidden="true">
        {paras.map((p, i) => (
          <p key={i}>
            {p}
            {writing && i === paras.length - 1 && <span className="caret" />}
          </p>
        ))}
      </div>
      {!r.llm && !writing && <p className="note">{t.templateNote}</p>}
    </div>
  );
}

function PriceTile({ p, each }: { p: Card["price"]; each: boolean }) {
  const t = useT();
  const price = priceLabel(p, t);
  if (!price) return null;
  const low = p.low != null && !p.free ? t.recordLow(priceLabel({ ...p, final: p.low, free: false }, t) ?? "") : null;
  const s = [p.discount_pct ? t.discount(p.discount_pct) : null, low].filter(Boolean).join(" · ");
  return <Tile k={each && !p.free ? t.pricePer : t.price} v={price} s={s} />;
}

function PickBody({ card: c, reason, group, busy, sessionId, onAction }: { card: Card; reason: ReasonState } & Omit<Props, "item" | "onClose" | "onRelax">) {
  const t = useT();
  const [report, setReport] = useState<"closed" | "open" | "sent">("closed");
  const like = c.like;
  const name = shortName(c.name);
  const sub = [englishName(c), c.year, c.developer].filter(Boolean).join(" · ");

  const tiles: ReactNode[] = [<PriceTile key="p" p={c.price} each={group} />];
  if (c.rating.pct_positive != null) {
    tiles.push(<Tile key="r" k={t.rating} v={`${c.rating.pct_positive}%`} s={t.reviews(c.rating.reviews.toLocaleString())} />);
  }
  if (c.time_to_beat) tiles.push(<Tile key="t" k={t.timeToBeat} v={shortTime(c.time_to_beat, t)} />);
  if (group && c.setup) tiles.push(<Tile key="s" k={t.howToPlay} v={c.setup.kind_zh} s={t.upTo(c.setup.max_players ?? "?")} />);
  else if (c.library) tiles.push(<Tile key="l" k={t.yourLibrary} v={c.library} s={c.library_hint} />);

  const warns = [
    like.feel_bad?.length ? t.avoidHit(like.feel_bad.join(t.comma)) : null,
    ...(c.unknown ?? []).map((w) => t.unconfirmed(w)),
    c.mechanics_note ?? null,
  ].filter(Boolean);

  const basis: [string, ReactNode][] = [];
  if (c.colike) basis.push([t.basisColike, c.colike.text]);
  if (like.shared_core_tags?.length) {
    basis.push([
      t.basisShared(like.anchor ?? null),
      like.shared_core_tags.map((x) => (
        <span className="tag" key={x}>
          {x}
        </span>
      )),
    ]);
  }
  if (like.feel_hits?.length) basis.push([t.basisFeel, like.feel_hits.join(t.comma)]);
  if (c.diff && (c.diff.more.length || c.diff.less.length)) {
    const d = [c.diff.more.length ? t.diffMore(c.diff.more.join(t.comma)) : "", c.diff.less.length ? t.diffLess(c.diff.less.join(t.comma)) : ""];
    basis.push([t.basisDiff(c.diff.anchor), d.filter(Boolean).join("　")]);
  }
  if (c.lineage_path?.text) basis.push([t.basisLineage, c.lineage_path.text]);
  else if (c.lineage?.length) basis.push([t.basisLineage, c.lineage.join("; ")]);
  if (c.same_series_folded?.length) basis.push([t.basisSeries, c.same_series_folded.join(t.comma)]);
  if (like.quote) basis.push([t.basisQuote, `“${like.quote}”`]);
  if (c.rating.text) basis.push([t.basisRating, c.rating.text]);
  if (c.price.text) basis.push([t.basisPrice, `${c.price.text}${c.price.as_of ? ` (${c.price.as_of})` : ""}`]);

  const act = (k: CardActionKind, label: string) => (
    <button type="button" className="btn ghost" disabled={busy} onClick={() => onAction(c.appid, k)}>
      {label}
    </button>
  );

  return (
    <>
      <Hero appid={c.appid} name={name} />
      <Head title={name} sub={sub}>
        <StoreLink href={c.store_url} />
        {act("liked", t.like)}
        {act("disliked", t.dislike)}
        {act("played", t.played)}
        {act("not_interested", t.notInterested)}
      </Head>
      <div className="s-body">
        <section className="why" aria-labelledby="why-t">
          <h3 className="sec-t" id="why-t">
            {t.why}
          </h3>
          <Why r={reason} />
        </section>
        <div className="tiles">{tiles}</div>
        {group && c.setup && (
          <section aria-labelledby="plan-t">
            <h3 className="sec-t" id="plan-t">
              {t.plan}
            </h3>
            <div className="plan">
              <ol>
                {c.setup.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
              {c.setup.purchase && <p>{c.setup.purchase}</p>}
              {c.setup.alternatives?.map((a) => (
                <p className="muted" key={a}>
                  {a}
                </p>
              ))}
              {c.setup.controller && <p className="muted">{t.controller(c.setup.controller)}</p>}
              {c.setup.friends_pass && <p className="muted">{c.setup.friends_pass}</p>}
            </div>
          </section>
        )}
        {warns.length > 0 && <div className="warn-box">{warns.join("; ")}</div>}
        {basis.length > 0 && (
          <details className="basis">
            <summary>{t.basis}</summary>
            <dl>
              {basis.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </details>
        )}
        <div className="s-foot">
          {report === "open" ? (
            <FactReportForm
              id={`report-${c.appid}`}
              appid={c.appid}
              gameName={name}
              sessionId={sessionId}
              onSent={() => setReport("sent")}
              onCancel={() => setReport("closed")}
            />
          ) : report === "sent" ? (
            <p className="note" role="status">
              {t.reportSent}
            </p>
          ) : (
            <button type="button" className="link" onClick={() => setReport("open")}>
              {t.reportOpen}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

function BackupBody({ b, busy, onAction }: { b: Backup } & Pick<Props, "busy" | "onAction">) {
  const t = useT();
  const name = shortName(b.name);
  const sub = [b.label, b.owned].filter(Boolean).join(" · ");
  return (
    <>
      <Hero appid={b.appid} name={name} />
      <Head title={name} sub={sub}>
        <StoreLink href={storeUrl(b.appid)} />
        <button type="button" className="btn ghost" disabled={busy} onClick={() => onAction(b.appid, "liked")}>
          {t.like}
        </button>
        <button type="button" className="btn ghost" disabled={busy} onClick={() => onAction(b.appid, "played")}>
          {t.played}
        </button>
      </Head>
      <div className="s-body">
        <div className="tiles">
          <PriceTile p={b.price} each={false} />
          {b.pct_positive != null && <Tile k={t.rating} v={`${b.pct_positive}%`} />}
        </div>
        {b.series_names?.length ? <p className="note">{t.series(b.series_names.join(t.comma))}</p> : null}
      </div>
    </>
  );
}

/** A near miss: what keeps it out, the facts, and one button to drop that condition. */
function MissBody({ m, busy, onRelax }: { m: NearMiss } & Pick<Props, "busy" | "onRelax">) {
  const t = useT();
  const name = shortName(m.name);
  return (
    <>
      <Hero appid={m.appid} name={name} />
      <Head title={name} sub="">
        <StoreLink href={storeUrl(m.appid)} />
        {m.relax && (
          <button type="button" className="btn ghost" disabled={busy} onClick={() => onRelax(m.relax!)}>
            {t.relaxBtn[m.relax]}
          </button>
        )}
      </Head>
      <div className="s-body">
        <section aria-labelledby="miss-t">
          <h3 className="sec-t" id="miss-t">
            {t.nearWhy}
          </h3>
          <div className="warn-box">
            <b>{missLabel(m.miss, t)}</b>
            {m.why.map((w) => (
              <p key={w}>{w}</p>
            ))}
            {m.miss.cause === "region" && <p>{t.regionHint}</p>}
          </div>
        </section>
        <div className="tiles">
          <PriceTile p={m.price} each={false} />
          {m.pct_positive != null && <Tile k={t.rating} v={`${m.pct_positive}%`} />}
        </div>
      </div>
    </>
  );
}
