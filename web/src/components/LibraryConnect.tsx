import { useId, useState } from "react";
import { api, errorMessage, type LibrarySummary } from "../api";
import { STEAM_DEMO } from "../guide";
import { useT } from "../i18n";
import { art } from "../present";
import type { LibState } from "../types";
import { SteamIcon } from "./Icons";

interface Props {
  member: number;
  /** Used in copy: the dictionary's "you", or a friend's name. */
  who: string;
  sessionId: string | null;
  lib: LibState | undefined;
  onConnected: (sessionId: string, member: number, summary: LibrarySummary) => void;
  onLogin: (member: number) => void;
  onDisconnect?: () => void;
}

/** Library summary text. Never shows a Steam ID: only counts and top games. */
export function LibrarySummaryView({ summary, who }: { summary: LibrarySummary; who: string }) {
  const t = useT();
  if (!summary.public) {
    return (
      <div className="notice warn" role="status">
        <b>{t.libPrivate(who)}</b>
        <span>{t.libPrivateHelp}</span>
      </div>
    );
  }
  return (
    <div className="lib-summary">
      <p>{t.libRead(summary.owned, summary.in_core, summary.played)}</p>
      {summary.outside_top && summary.outside_top.length > 0 && <p className="hint">{t.libOutside(summary.outside_top.join(t.comma))}</p>}
      {summary.top.length > 0 && (
        <p className="muted">
          {t.libTop(
            summary.top
              .slice(0, 4)
              .map((x) => t.libTopItem(x.name, x.hours))
              .join(t.comma),
          )}
        </p>
      )}
      {summary.playtime_hidden && <p className="notice warn">{t.libHidden}</p>}
    </div>
  );
}

/** The popover shows what an import does with three posters instead of explaining it. */
function LibDemo() {
  const t = useT();
  return (
    <div className="lib-demo" aria-hidden="true">
      <figure className="played">
        <img src={art(STEAM_DEMO.played, "library_600x900.jpg")} alt="" />
        <figcaption>{t.demoPlayed}</figcaption>
      </figure>
      <figure className="fav">
        <img src={art(STEAM_DEMO.hours, "library_600x900.jpg")} alt="" />
        <figcaption>{t.demoHours}</figcaption>
      </figure>
      <figure className="rec">
        <img src={art(STEAM_DEMO.rec, "library_600x900.jpg")} alt="" />
        <figcaption>{t.demoRec}</figcaption>
      </figure>
    </div>
  );
}

export function LibraryConnect({ member, who, sessionId, lib, onConnected, onLogin, onDisconnect }: Props) {
  const t = useT();
  const id = useId();
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paste, setPaste] = useState(false);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const v = profile.trim();
    if (!v) {
      setError(t.libNeedLink);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.library(sessionId, member, v);
      setProfile(""); // the link can contain a Steam ID; do not keep it around
      onConnected(r.session_id, r.member, r.library);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (lib) {
    return (
      <div className="lib-connected">
        {lib.summary ? <LibrarySummaryView summary={lib.summary} who={who} /> : <p>{t.libLoginDone}</p>}
        {onDisconnect && (
          <button type="button" className="link" onClick={onDisconnect}>
            {t.libDisconnect}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="lib-connect">
      <p className="lib-lead">{t.steamLead}</p>
      <LibDemo />
      <p className="lib-line">{t.steamLine}</p>
      <button type="button" className="cta wide" onClick={() => onLogin(member)}>
        <SteamIcon />
        {t.libLogin}
      </button>
      <button type="button" className="alt" aria-expanded={paste} aria-controls={`${id}-paste`} onClick={() => setPaste((v) => !v)}>
        {t.pasteToggle}
      </button>
      {paste && (
        <form className="paste" id={`${id}-paste`} onSubmit={connect} aria-busy={busy}>
          <div className="inline-row">
            <input
              id={`${id}-profile`}
              className="input"
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              autoFocus
              placeholder="steamcommunity.com/id/…"
              aria-label={t.libPaste(who)}
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${id}-err` : undefined}
            />
            <button className="btn ghost" type="submit" disabled={busy}>
              {busy ? t.libReading : t.libConnect}
            </button>
          </div>
          {error && (
            <p className="field-error" id={`${id}-err`} role="alert">
              {error}
            </p>
          )}
        </form>
      )}
      <p className="fine">{t.steamFine}</p>
    </div>
  );
}
