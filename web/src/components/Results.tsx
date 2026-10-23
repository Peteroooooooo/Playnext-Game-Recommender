import { useState } from "react";
import type { Backup, Card, NearMiss, RecommendResult } from "../api";
import { useT } from "../i18n";
import { art, cardBadges, metaText, missLabel, priceLabel, shortName, understoodChips, understoodNotes } from "../present";

const BACKUPS_SHOWN = 10;

export type Opened = { kind: "pick" | "backup" | "miss"; appid: number };

interface Props {
  result: RecommendResult;
  busy: boolean;
  /** Picks about to be replaced after a library import (they have Steam playtime): greyed with a label first. */
  playedOut?: number[];
  onOpen: (o: Opened) => void;
  onFocusGame: (appid: number) => void;
  /** A relax option was picked: re-run with that change. */
  onRelax: (text: string) => void;
}

/** Near misses in rank order: games that only lack a fact first, then the ones that broke a condition. */
export function nearMisses(r: RecommendResult): NearMiss[] {
  const seen = new Set<number>();
  // an older backend sends these without price / miss; leave them out rather than break the page
  return [...(r.unknown ?? []), ...(r.failed ?? [])].filter((m) => m.price && m.miss && !seen.has(m.appid) && seen.add(m.appid));
}

/** Shown once above the first results while no library is imported. */
export function SteamNudge({ picks, onImport, onDismiss }: { picks: number[]; onImport: () => void; onDismiss: () => void }) {
  const t = useT();
  return (
    <div className="nudge" role="note">
      <div className="stack" aria-hidden="true">
        {picks.slice(0, 3).map((a) => (
          <img key={a} src={art(a, "library_600x900.jpg")} alt="" />
        ))}
      </div>
      <p>
        {t.nudgeQ}
        <span>{t.nudgeLine}</span>
      </p>
      <button type="button" className="cta" onClick={onImport}>
        {t.nudgeGo}
      </button>
      <button type="button" className="x" aria-label={t.nudgeNo} onClick={onDismiss}>
        ×
      </button>
    </div>
  );
}

export function Understood({ result: r }: { result: RecommendResult }) {
  const t = useT();
  const notes = [...understoodNotes(r.understood, t), ...r.notes];
  return (
    <>
      <div className="understood">
        <span className="lbl">{t.understoodLbl}</span>
        {understoodChips(r.understood, t).map((c) => (
          <span className="chip" key={c}>
            {c}
          </span>
        ))}
      </div>
      {notes.map((n) => (
        <p className="note-line" key={n}>
          {n}
        </p>
      ))}
    </>
  );
}

function Poster({ appid }: { appid: number }) {
  const [fallback, setFallback] = useState(false);
  return (
    <div className={`poster${fallback ? " fallback" : ""}`}>
      {fallback && <img className="blur" src={art(appid, "header.jpg")} alt="" />}
      <img
        className="main"
        src={art(appid, fallback ? "header.jpg" : "library_600x900.jpg")}
        alt=""
        decoding="async"
        onError={() => setFallback(true)}
      />
    </div>
  );
}

interface TileProps {
  appid: number;
  name: string;
  peek?: string;
  meta: string;
  badges: { text: string; tone: "good" | "warn" }[];
  onOpen: () => void;
  onFocusGame: (appid: number) => void;
  out?: boolean;
}

/** One poster; the picks and the near misses look the same, a near miss only carries its orange badge. */
function GameTile({ appid, name, peek, meta, badges, onOpen, onFocusGame, out }: TileProps) {
  const t = useT();
  return (
    <button
      type="button"
      className={`game${out ? " played-out" : ""}`}
      aria-label={t.openDetail(name)}
      onClick={onOpen}
      onMouseEnter={() => onFocusGame(appid)}
      onFocus={() => onFocusGame(appid)}
    >
      <div className="poster-wrap">
        <Poster appid={appid} />
        {out && <em className="out-lbl">{t.playedSwap}</em>}
        {peek && (
          <div className="peek" aria-hidden="true">
            {peek}
          </div>
        )}
      </div>
      <div className="g-name">{name}</div>
      <div className="g-meta">
        {meta && <span>{meta}</span>}
        {badges.map((b) => (
          <span className={`badge ${b.tone}`} key={b.text}>
            {b.text}
          </span>
        ))}
      </div>
    </button>
  );
}

function BackupTile({ b, onOpen, onFocusGame }: { b: Backup } & Pick<Props, "onOpen" | "onFocusGame">) {
  const t = useT();
  const [img, setImg] = useState(true);
  return (
    <button
      type="button"
      className="mini"
      onClick={() => onOpen({ kind: "backup", appid: b.appid })}
      onMouseEnter={() => onFocusGame(b.appid)}
      onFocus={() => onFocusGame(b.appid)}
    >
      {img ? <img src={art(b.appid, "header.jpg")} alt="" decoding="async" onError={() => setImg(false)} /> : <span className="mini-ph" />}
      <b>{shortName(b.name)}</b>
      <span>{priceLabel(b.price, t) ?? ""}</span>
    </button>
  );
}

export function Results({ result: r, busy, playedOut, onOpen, onFocusGame, onRelax }: Props) {
  const t = useT();
  const [allBackups, setAllBackups] = useState(false);
  const group = r.understood.party_size > 1;
  const near = nearMisses(r);
  const head = r.picks.length
    ? group
      ? t.headGroup(r.understood.party_size, r.picks.length)
      : t.headSolo(r.picks.length)
    : r.need_input
      ? t.headNeedInput
      : t.headNone;

  const pickPeek = (c: Card) => {
    const tags = (c.like.shared_core_tags ?? []).slice(0, 3).join(" · ");
    return [tags, c.rating.pct_positive != null ? t.positive(c.rating.pct_positive) : null].filter(Boolean).join("　");
  };

  return (
    <div className={busy && !playedOut?.length ? "refreshing" : undefined} aria-busy={busy}>
      <section className="results" aria-labelledby="res-t">
        <h2 id="res-t">{head}</h2>
        {r.need_input && <p className="lead">{r.need_input}</p>}
        {r.picks.length > 0 && (
          <div className="shelf">
            {r.picks.map((c) => (
              <GameTile
                key={c.appid}
                appid={c.appid}
                name={shortName(c.name)}
                peek={pickPeek(c)}
                meta={metaText(c, group, t)}
                badges={cardBadges(c, t)}
                onOpen={() => onOpen({ kind: "pick", appid: c.appid })}
                onFocusGame={onFocusGame}
                out={playedOut?.includes(c.appid)}
              />
            ))}
          </div>
        )}
        {!r.picks.length && !r.need_input && (
          <div className="relax">
            {r.relax.length > 0 ? (
              <>
                <p className="lead">{t.relaxLead}</p>
                {r.relax.map((o) => {
                  const text = o.changes.map((c) => c.text).join(t.comma);
                  return (
                    <button type="button" className="fix" key={text} disabled={busy} onClick={() => onRelax(text)}>
                      <span>{text}</span>
                      <small>{t.relaxCount(o.count)}</small>
                    </button>
                  );
                })}
              </>
            ) : (
              <p className="lead">{t.relaxNone}</p>
            )}
          </div>
        )}
      </section>

      {r.backups.length > 0 && (
        <section className="more" aria-labelledby="more-t">
          <h3 id="more-t">{t.more}</h3>
          <div className="strip">
            {(allBackups ? r.backups : r.backups.slice(0, BACKUPS_SHOWN)).map((b) => (
              <BackupTile key={b.appid} b={b} onOpen={onOpen} onFocusGame={onFocusGame} />
            ))}
          </div>
          {r.backups.length > BACKUPS_SHOWN && (
            <button type="button" className="link more-btn" aria-expanded={allBackups} onClick={() => setAllBackups((v) => !v)}>
              {allBackups ? t.showLess : t.showMore(r.backups.length - BACKUPS_SHOWN)}
            </button>
          )}
        </section>
      )}

      {near.length > 0 && (
        <section className="more" aria-labelledby="near-t">
          <h3 id="near-t">{t.nearTitle}</h3>
          <div className="shelf">
            {near.map((m) => (
              <GameTile
                key={m.appid}
                appid={m.appid}
                name={shortName(m.name)}
                peek={m.pct_positive != null ? t.positive(m.pct_positive) : undefined}
                meta={priceLabel(m.price, t) ?? ""}
                badges={[{ text: missLabel(m.miss, t), tone: "warn" }]}
                onOpen={() => onOpen({ kind: "miss", appid: m.appid })}
                onFocusGame={onFocusGame}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
