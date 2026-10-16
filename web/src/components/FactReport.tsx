import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage, type ReportField } from "../api";
import { REPORT_FIELD_ZH } from "../types";

const MAX_TEXT = 300;

interface Props {
  id: string;
  appid: number;
  gameName: string;
  sessionId: string | null;
  onSent: () => void;
  onCancel: () => void;
}

/** "事实有误？" inline form. Only records the report; the current result is not changed. */
export function FactReportForm({ id, appid, gameName, sessionId, onSent, onCancel }: Props) {
  const uid = useId();
  const [field, setField] = useState<ReportField>("players");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    selectRef.current?.focus();
  }, []);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) {
      setError("说一句哪里不对，比如“其实最多支持 8 人”");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.report({ ...(sessionId ? { session_id: sessionId } : {}), appid, field, text: t });
      if (r.ok) onSent();
      else setError("没能记录，请稍后再试");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      id={id}
      className="report"
      aria-label={`报告《${gameName}》的事实错误`}
      aria-busy={busy}
      onSubmit={send}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <div className="field">
        <label className="field-label" htmlFor={`${uid}-field`}>
          哪一项有误
        </label>
        <select
          id={`${uid}-field`}
          ref={selectRef}
          className="input sm report-select"
          value={field}
          onChange={(e) => setField(e.target.value as ReportField)}
        >
          {(Object.keys(REPORT_FIELD_ZH) as ReportField[]).map((k) => (
            <option key={k} value={k}>
              {REPORT_FIELD_ZH[k]}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${uid}-text`}>
          具体哪里不对
          <span className="hint" aria-hidden="true">
            {" "}
            {text.length} / {MAX_TEXT}
          </span>
        </label>
        <textarea
          id={`${uid}-text`}
          className="input"
          rows={3}
          maxLength={MAX_TEXT}
          value={text}
          placeholder="比如：商店页写的是最多 8 人在线"
          onChange={(e) => {
            setText(e.target.value);
            if (error) setError(null);
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${uid}-err` : undefined}
        />
      </div>
      {error && (
        <p className="field-error" id={`${uid}-err`} role="alert">
          {error}
        </p>
      )}
      <div className="inline-row">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? "发送中…" : "发送"}
        </button>
        <button type="button" className="btn ghost" onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}
