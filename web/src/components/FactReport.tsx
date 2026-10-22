import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage, type ReportField } from "../api";
import { useT } from "../i18n";

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
  const t = useT();
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
    const v = text.trim();
    if (!v) {
      setError(t.reportNeedText);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.report({ ...(sessionId ? { session_id: sessionId } : {}), appid, field, text: v });
      if (r.ok) onSent();
      else setError(t.reportFailed);
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
      aria-label={t.reportAria(gameName)}
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
          {t.reportField}
        </label>
        <select
          id={`${uid}-field`}
          ref={selectRef}
          className="input sm report-select"
          value={field}
          onChange={(e) => setField(e.target.value as ReportField)}
        >
          {(Object.keys(t.reportFields) as ReportField[]).map((k) => (
            <option key={k} value={k}>
              {t.reportFields[k]}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${uid}-text`}>
          {t.reportDetail}
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
          placeholder={t.reportPlaceholder}
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
          {busy ? t.reportSending : t.reportSend}
        </button>
        <button type="button" className="btn ghost" onClick={onCancel}>
          {t.cancel}
        </button>
      </div>
    </form>
  );
}
