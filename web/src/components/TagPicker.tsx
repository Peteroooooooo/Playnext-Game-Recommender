import { useId, useState } from "react";
import type { Tag } from "../api";
import { XIcon } from "./Icons";

interface Props {
  label: string;
  hint?: string;
  common: Tag[];
  all: Tag[];
  selected: Tag[];
  onChange: (next: Tag[]) => void;
  /** Tag ids not offered here (e.g. content handled by separate switches). */
  hide?: number[];
  tone?: "want" | "avoid";
}

/** Toggle chips for the common Steam tags, plus a search over all 446 tags. */
export function TagPicker({ label, hint, common, all, selected, onChange, hide = [], tone = "want" }: Props) {
  const id = useId();
  const [q, setQ] = useState("");
  const chosen = new Set(selected.map((t) => t.tagid));
  const hidden = new Set(hide);
  const commonIds = new Set(common.map((t) => t.tagid));

  // 446 tags: a plain filter per keystroke is cheap enough.
  const term = q.trim().toLowerCase();
  const matches = term
    ? all
        .filter((t) => !hidden.has(t.tagid))
        .filter((t) => t.name.toLowerCase().includes(term) || t.name_en.toLowerCase().includes(term))
        .slice(0, 10)
    : [];

  const toggle = (t: Tag) =>
    onChange(chosen.has(t.tagid) ? selected.filter((x) => x.tagid !== t.tagid) : [...selected, t]);

  const extra = selected.filter((t) => !commonIds.has(t.tagid));

  return (
    <div className="field" role="group" aria-labelledby={`${id}-label`}>
      <span className="field-label" id={`${id}-label`}>
        {label}
        {hint && <span className="hint"> {hint}</span>}
      </span>
      <div className="chips">
        {common
          .filter((t) => !hidden.has(t.tagid))
          .map((t) => (
            <button
              type="button"
              key={t.tagid}
              className={`toggle ${tone}`}
              aria-pressed={chosen.has(t.tagid)}
              onClick={() => toggle(t)}
            >
              {t.name}
            </button>
          ))}
        {extra.map((t) => (
          <span className={`chip ${tone === "avoid" ? "chip-avoid" : "fixed-ish"}`} key={t.tagid}>
            {t.name}
            <button type="button" className="x" aria-label={`去掉 ${t.name}`} onClick={() => toggle(t)}>
              <XIcon />
            </button>
          </span>
        ))}
      </div>
      <div className="tag-search">
        <label className="sr-only" htmlFor={`${id}-q`}>
          在全部标签里搜索：{label}
        </label>
        <input
          id={`${id}-q`}
          className="input sm"
          type="search"
          placeholder="搜索更多标签，如 类 Rogue、Roguelike"
          autoComplete="off"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {q.trim() && (
          <div className="chips tag-results" aria-live="polite">
            {matches.length === 0 && <span className="hint">没有匹配的标签</span>}
            {matches.map((t) => (
              <button
                type="button"
                key={t.tagid}
                className={`toggle ${tone}`}
                aria-pressed={chosen.has(t.tagid)}
                onClick={() => toggle(t)}
                title={t.name_en}
              >
                {t.name}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
