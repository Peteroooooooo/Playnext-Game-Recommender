import { forwardRef, useEffect, useId, useRef, useState } from "react";
import { api, type GameHit } from "../api";
import { useT } from "../i18n";
import { Guide } from "./Guide";

interface Props {
  text: string;
  onText: (t: string) => void;
  onSubmit: () => void;
  /** × : drop everything and go back to the home screen. */
  onReset: () => void;
  running: boolean;
  busy: boolean;
  /** false: free text is unavailable, the field searches for one game to start from. */
  llm: boolean | null;
  onPickGame: (g: GameHit) => void;
  guideOpen: boolean;
  onGuide: (open: boolean) => void;
  /** The example sentence the home screen shows right now; typed out as the placeholder, Tab fills it in. */
  ghost: string;
  onExample: (text: string, appid: number) => void;
  onFocusGame: (appid: number) => void;
  onOpenSteam: () => void;
  libCount: number | null;
}

/** Seconds between the "?" hops on the idle home screen. */
const HOP_EVERY_MS = 6000;
const HOP_FIRST_MS = 1500;

export const Search = forwardRef<HTMLInputElement, Props>(function Search(props, ref) {
  const { text, onText, onSubmit, onReset, running, busy, llm, onPickGame, guideOpen, onGuide, ghost } = props;
  const id = useId();
  const t = useT();
  const games = llm === false;
  const hits = useGameHits(games ? text : "");
  const [active, setActive] = useState(0);
  const [listOpen, setListOpen] = useState(false);
  const has = text.trim().length > 0;
  const showList = games && listOpen && has && hits.length > 0;
  const placeholder = useTyped(games ? t.gamePlaceholder : ghost, !games);
  const hop = useHop(!has && !guideOpen && !running, has || guideOpen);

  useEffect(() => setActive(0), [hits]);

  useEffect(() => {
    if (!guideOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onGuide(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [guideOpen, onGuide]);

  function pick(g: GameHit) {
    setListOpen(false);
    onPickGame(g);
  }

  return (
    <>
      <div className="search-wrap">
        <form
          className={`search${has ? " has-text" : ""}`}
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            if (showList && hits[active]) pick(hits[active]);
            else if (!games && has && !busy) onSubmit();
          }}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="6" />
            <path d="m13 13 5 5" />
          </svg>
          <label htmlFor={`${id}-q`} className="sr-only">
            {games ? t.gameLabel : t.askLabel}
          </label>
          <input
            id={`${id}-q`}
            ref={ref}
            autoComplete="off"
            enterKeyHint="search"
            maxLength={300}
            value={text}
            placeholder={placeholder}
            onChange={(e) => {
              onText(e.target.value);
              setListOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (!games && !has && e.key === "Tab" && !e.shiftKey && ghost) {
                e.preventDefault();
                onText(ghost);
                return;
              }
              if (!showList) return;
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                const d = e.key === "ArrowDown" ? 1 : -1;
                setActive((a) => (a + d + hits.length) % hits.length);
              } else if (e.key === "Escape") {
                e.stopPropagation();
                setListOpen(false);
              }
            }}
            onBlur={() => window.setTimeout(() => setListOpen(false), 120)}
            {...(games
              ? {
                  role: "combobox",
                  "aria-expanded": showList,
                  "aria-controls": `${id}-list`,
                  "aria-autocomplete": "list" as const,
                  "aria-activedescendant": showList ? `${id}-o${active}` : undefined,
                }
              : {})}
          />
          {!games && !has && (
            <kbd className="kbd" aria-hidden="true">
              {t.tabKey}
            </kbd>
          )}
          {(has || running) && (
            <button className="clear" type="button" aria-label={t.clear} onClick={onReset}>
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <circle cx="10" cy="10" r="9" fill="currentColor" />
                <path d="M7 7l6 6M13 7l-6 6" stroke="#2c2c30" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          )}
          {!games && (
            <button
              className={`help${hop ? " hint" : ""}`}
              key={hop}
              type="button"
              aria-expanded={guideOpen}
              aria-controls={`${id}-guide`}
              aria-label={t.help}
              onClick={() => onGuide(!guideOpen)}
            >
              ?
            </button>
          )}
          {has && !games && (
            <button className="go" type="submit" aria-label={t.send} disabled={busy}>
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M10 16V4M4.5 9.5 10 4l5.5 5.5" />
              </svg>
            </button>
          )}
        </form>
        {showList && (
          <ul className="hits" id={`${id}-list`} role="listbox" aria-label={t.games}>
            {hits.map((h, i) => (
              <li
                key={h.appid}
                id={`${id}-o${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(h);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <span>{h.name}</span>
                {h.year && <small>{h.year}</small>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {guideOpen && !games && (
        <Guide
          id={`${id}-guide`}
          text={text}
          onText={(s) => {
            onText(s);
            if (ref && typeof ref !== "function") ref.current?.focus();
          }}
          onExample={props.onExample}
          onFocusGame={props.onFocusGame}
          onOpenSteam={props.onOpenSteam}
          libCount={props.libCount}
        />
      )}
    </>
  );
});

/** The placeholder typed out one character at a time; plain text under reduced motion. */
function useTyped(s: string, animate: boolean): string {
  const [n, setN] = useState(animate ? 0 : s.length);
  useEffect(() => {
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setN(s.length);
      return undefined;
    }
    setN(0);
    const id = window.setInterval(() => setN((k) => (k >= s.length ? k : k + 1)), 45);
    return () => window.clearInterval(id);
  }, [s, animate]);
  return s.slice(0, n);
}

/**
 * A counter that goes up every few seconds while `idle`, so the "?" hops (the key replays its animation).
 * Stops for this visit once `done` turns true (the user typed or opened the guide); nothing is stored.
 */
function useHop(idle: boolean, done: boolean): number {
  const [n, setN] = useState(0);
  const stopped = useRef(false);
  if (done) stopped.current = true;
  useEffect(() => {
    if (!idle || stopped.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    let id = window.setTimeout(function tick() {
      setN((k) => k + 1);
      id = window.setTimeout(tick, HOP_EVERY_MS);
    }, n === 0 ? HOP_FIRST_MS : HOP_EVERY_MS);
    return () => window.clearTimeout(id);
  }, [idle]);
  return stopped.current ? 0 : n;
}

/** /api/search as you type (only used when free text is unavailable). */
function useGameHits(q: string): GameHit[] {
  const [hits, setHits] = useState<GameHit[]>([]);
  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setHits([]);
      return undefined;
    }
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      api
        .search(term, 6, ctl.signal)
        .then(setHits)
        .catch(() => setHits([]));
    }, 200);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [q]);
  return hits;
}
