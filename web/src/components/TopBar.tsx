import { useEffect, useRef, useState } from "react";
import type { LibrarySummary, Region } from "../api";
import { useT, type Lang } from "../i18n";
import type { LibState } from "../types";
import { GlobeIcon, LockIcon, SteamIcon } from "./icons";
import { LibraryConnect } from "./LibraryConnect";

interface Props {
  lang: Lang;
  onLang: (l: Lang) => void;
  region: Region;
  onRegion: (r: Region) => void;
  /** Results are on screen: the store is fixed until × starts over. */
  storeLocked: boolean;
  sessionId: string | null;
  myLib: LibState | undefined;
  steamOpen: boolean;
  onSteamOpen: (open: boolean) => void;
  /** Ring the Steam pill once (the nudge above the results is showing). */
  ping: boolean;
  onConnected: (sessionId: string, member: number, summary: LibrarySummary) => void;
  onLogin: (member: number) => void;
  onDisconnect: () => void;
}

/** A pill that opens a popover; closes on a click outside or Escape (focus goes back to the pill). */
function usePopover(open: boolean, setOpen: (o: boolean) => void) {
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, setOpen]);
  return { wrap, btn };
}

export function TopBar(p: Props) {
  const t = useT();
  const [locOpen, setLocOpen] = useState(false);
  const loc = usePopover(locOpen, setLocOpen);
  const steam = usePopover(p.steamOpen, p.onSteamOpen);
  const lib = p.myLib;

  return (
    <header className="top">
      <a className="brand" href="/">
        Playnext
      </a>
      <div className="top-actions">
        <div className="pop-wrap" ref={loc.wrap}>
          <button
            ref={loc.btn}
            type="button"
            className="pill"
            aria-expanded={locOpen}
            aria-controls="loc-pop"
            aria-label={t.localeLabel}
            onClick={() => {
              setLocOpen(!locOpen);
              p.onSteamOpen(false);
            }}
          >
            <GlobeIcon />
            <span>{t.langName[p.lang]}</span>
            <span className="sep" aria-hidden="true" />
            <span className="dim">
              {p.region === "CN" ? "¥" : "$"} {t.regionName[p.region]}
            </span>
            {p.storeLocked && <LockIcon />}
          </button>
          {locOpen && (
            <div className="pop" id="loc-pop" role="dialog" aria-label={t.localeLabel}>
              <div className="row">
                <h3>{t.langLabel}</h3>
                <div className="seg" role="group" aria-label={t.langLabel}>
                  {(["zh", "en"] as Lang[]).map((l) => (
                    <button type="button" key={l} lang={l === "zh" ? "zh-CN" : "en"} aria-pressed={p.lang === l} onClick={() => p.onLang(l)}>
                      {t.langName[l]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="row">
                <h3>{t.storeQ}</h3>
                <div className="seg" role="group" aria-label={t.storeQ} aria-disabled={p.storeLocked || undefined}>
                  {(["CN", "US"] as Region[]).map((r) => (
                    <button type="button" key={r} aria-pressed={p.region === r} disabled={p.storeLocked} onClick={() => p.onRegion(r)}>
                      {r === "CN" ? "¥" : "$"} {t.regionName[r]}
                    </button>
                  ))}
                </div>
                {p.storeLocked ? (
                  <p className="cap lock-cap">
                    <LockIcon />
                    <span>{t.storeLocked(t.regionName[p.region])}</span>
                  </p>
                ) : (
                  <p className="cap">{t.storeCap}</p>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="pop-wrap" ref={steam.wrap}>
          <button
            ref={steam.btn}
            type="button"
            className={`pill${p.ping && !p.steamOpen ? " ping" : ""}`}
            aria-expanded={p.steamOpen}
            aria-controls="steam-pop"
            onClick={() => {
              p.onSteamOpen(!p.steamOpen);
              setLocOpen(false);
            }}
          >
            <SteamIcon />
            {lib ? (
              <span>
                <span className="dot-on" aria-hidden="true" /> {t.myLib}
                {lib.summary?.public && <span className="wide">{t.libCount(lib.summary.owned)}</span>}
              </span>
            ) : (
              <span>
                <span className="wide">{t.steamImport}</span>
                <span className="narrow">{t.steamShort}</span>
              </span>
            )}
          </button>
          {p.steamOpen && (
            <div className="pop" id="steam-pop" role="dialog" aria-label={t.steamLibrary}>
              <LibraryConnect
                member={0}
                who={t.you}
                sessionId={p.sessionId}
                lib={lib}
                onConnected={p.onConnected}
                onLogin={p.onLogin}
                onDisconnect={() => {
                  p.onDisconnect();
                  p.onSteamOpen(false);
                }}
              />
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
