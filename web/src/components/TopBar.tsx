import { useEffect, useRef, useState } from "react";
import type { LibrarySummary, Region } from "../api";
import type { LibState } from "../types";
import { Avatar, Logo } from "./Icons";
import { LibraryConnect } from "./LibraryConnect";

interface Props {
  region: Region;
  onRegion: (r: Region) => void;
  sessionId: string | null;
  myLib: LibState | undefined;
  onConnected: (sessionId: string, member: number, summary: LibrarySummary) => void;
  onLogin: (member: number) => void;
  onDisconnect: () => void;
}

export function TopBar({ region, onRegion, sessionId, myLib, onConnected, onLogin, onDisconnect }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const connected = Boolean(myLib);

  return (
    <header className="top">
      <div className="wrap">
        <a className="brand" href="/" aria-label="Playnext 首页">
          <Logo />
          <b>Playnext</b>
          <small>下一款玩什么</small>
        </a>
        <div className="top-actions">
          <label className="region" htmlFor="region">
            <span>商店区</span>
            <select id="region" value={region} onChange={(e) => onRegion(e.target.value as Region)}>
              <option value="CN">CN · ¥</option>
              <option value="US">US · $</option>
            </select>
          </label>
          <div className="pop-wrap" ref={wrapRef}>
            <button
              ref={btnRef}
              type="button"
              className={`steam-btn${connected ? "" : " off"}`}
              aria-expanded={open}
              aria-controls="steam-pop"
              onClick={() => setOpen((o) => !o)}
            >
              {connected ? (
                <>
                  <Avatar name="我" index={0} small />
                  <span>
                    Steam<span className="lbl-long"> · 已连接</span>
                  </span>
                </>
              ) : (
                <>
                  连接 Steam<span className="lbl-long">（可选）</span>
                </>
              )}
            </button>
            {open && (
              <div className="pop" id="steam-pop" role="dialog" aria-label="Steam 游戏库">
                <b>{connected ? "你的 Steam 游戏库" : "连接你的 Steam 游戏库"}</b>
                <LibraryConnect
                  member={0}
                  who="你"
                  sessionId={sessionId}
                  lib={myLib}
                  onConnected={(sid, m, s) => {
                    onConnected(sid, m, s);
                  }}
                  onLogin={onLogin}
                  onDisconnect={() => {
                    onDisconnect();
                    setOpen(false);
                  }}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
