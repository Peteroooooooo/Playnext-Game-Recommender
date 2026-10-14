import { useId, useState } from "react";
import { api, errorMessage, type LibrarySummary } from "../api";
import type { LibState } from "../types";

interface Props {
  member: number;
  /** Used in copy, e.g. "你" or a friend's name. */
  who: string;
  sessionId: string | null;
  lib: LibState | undefined;
  onConnected: (sessionId: string, member: number, summary: LibrarySummary) => void;
  onLogin: (member: number) => void;
  onDisconnect?: () => void;
  compact?: boolean;
}

/** Library summary text. Never shows a Steam ID: only counts and top games. */
export function LibrarySummaryView({ summary, who }: { summary: LibrarySummary; who: string }) {
  if (!summary.public) {
    return (
      <div className="notice warn" role="status">
        <b>{who}的 Steam 游戏详情不公开，读不到库。</b>
        <span>
          在 Steam 打开“个人资料 → 编辑个人资料 → 隐私设置”，把“游戏详情”改为“公开”，再连接一次；或者直接在问卷里点选喜欢的游戏。
        </span>
      </div>
    );
  }
  return (
    <div className="lib-summary">
      <p>
        读到 <b className="mono">{summary.owned}</b> 款游戏，其中 <b className="mono">{summary.in_core}</b> 款在推荐库里，玩过{" "}
        <b className="mono">{summary.played}</b> 款。
      </p>
      {summary.top.length > 0 && (
        <p className="muted">
          玩得最多：
          {summary.top
            .slice(0, 4)
            .map((t) => `${t.name}（${t.hours} 小时）`)
            .join("、")}
        </p>
      )}
      {summary.playtime_hidden && (
        <p className="notice warn">游戏时长都是 0，看起来隐藏了游玩时间：库只用来标“已拥有”，不当口味参考。</p>
      )}
    </div>
  );
}

export function LibraryConnect({ member, who, sessionId, lib, onConnected, onLogin, onDisconnect, compact }: Props) {
  const id = useId();
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const v = profile.trim();
    if (!v) {
      setError("先粘贴 Steam 个人主页链接");
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
        {lib.summary ? (
          <LibrarySummaryView summary={lib.summary} who={who} />
        ) : (
          <p>已通过 Steam 登录连接。库的摘要会在下一次推荐后显示。</p>
        )}
        {onDisconnect && (
          <button type="button" className="link" onClick={onDisconnect}>
            断开（会重新开始会话）
          </button>
        )}
      </div>
    );
  }

  return (
    <form className={`lib-form${compact ? " compact" : ""}`} onSubmit={connect} aria-busy={busy}>
      <label className="field-label" htmlFor={`${id}-profile`}>
        粘贴{who === "你" ? "" : `${who}的`} Steam 个人主页链接
      </label>
      <div className="inline-row">
        <input
          id={`${id}-profile`}
          className="input"
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="steamcommunity.com/id/…"
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-err` : undefined}
        />
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "读取中…" : "连接"}
        </button>
      </div>
      {error && (
        <p className="field-error" id={`${id}-err`} role="alert">
          {error}
        </p>
      )}
      <div className="inline-row">
        <span className="hint">或者</span>
        <button type="button" className="btn ghost" onClick={() => onLogin(member)}>
          用 Steam 登录
        </button>
      </div>
      {!compact && (
        <p className="note">
          只读取公开的游戏库和游玩时长：已有的游戏不再让你买，玩得多的游戏用来了解口味。页面不显示、也不保存 Steam ID。
        </p>
      )}
    </form>
  );
}
