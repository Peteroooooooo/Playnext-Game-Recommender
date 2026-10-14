import { useEffect, useId, useRef, useState } from "react";
import { api, errorMessage, type GameHit } from "../api";
import type { GameRef } from "../types";
import { XIcon } from "./Icons";

interface Props {
  label: string;
  hint?: string;
  selected: GameRef[];
  max: number;
  placeholder?: string;
  onChange: (next: GameRef[]) => void;
}

/** Game autocomplete (ARIA combobox) over GET /api/search. */
export function GameSearch({ label, hint, selected, max, placeholder, onChange }: Props) {
  const id = useId();
  const inputId = `${id}-input`;
  const listId = `${id}-list`;
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<GameHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setHits([]);
      setLoading(false);
      setError(null);
      return undefined;
    }
    const ctl = new AbortController();
    setLoading(true);
    const t = window.setTimeout(() => {
      api
        .search(term, 8, ctl.signal)
        .then((r) => {
          setHits(r);
          setActive(r.length ? 0 : -1);
          setError(null);
          setLoading(false);
        })
        .catch((e: unknown) => {
          if (e instanceof DOMException && e.name === "AbortError") return;
          setError(errorMessage(e));
          setHits([]);
          setLoading(false);
        });
    }, 220);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [q]);

  const chosen = new Set(selected.map((g) => g.appid));
  const options = hits.filter((h) => !chosen.has(h.appid));
  const full = selected.length >= max;

  function pick(h: GameHit) {
    if (full) return;
    onChange([...selected, { appid: h.appid, name: h.name, year: h.year }]);
    setQ("");
    setHits([]);
    setOpen(false);
    inputRef.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => (options.length ? (a + 1) % options.length : -1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (options.length ? (a - 1 + options.length) % options.length : -1));
    } else if (e.key === "Enter") {
      if (open && active >= 0 && options[active]) {
        e.preventDefault();
        pick(options[active]);
      }
    } else if (e.key === "Escape") {
      if (open) {
        e.stopPropagation();
        setOpen(false);
      }
    }
  }

  const showList = open && q.trim() !== "";

  return (
    <div className="field">
      <label className="field-label" htmlFor={inputId}>
        {label}
        {hint && <span className="hint"> {hint}</span>}
      </label>
      {selected.length > 0 && (
        <div className="chips">
          {selected.map((g) => (
            <span className="chip" key={g.appid}>
              {g.name}
              {g.year ? <span className="muted">&nbsp;· {g.year}</span> : null}
              <button
                type="button"
                className="x"
                aria-label={`去掉 ${g.name}`}
                onClick={() => onChange(selected.filter((x) => x.appid !== g.appid))}
              >
                <XIcon />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="combo">
        <input
          ref={inputRef}
          id={inputId}
          className="input"
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 && options[active] ? `${id}-opt-${options[active].appid}` : undefined}
          autoComplete="off"
          placeholder={full ? `最多 ${max} 款` : placeholder ?? "输入游戏名，中英文都行"}
          disabled={full}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
        />
        {showList && (
          <ul className="menu listbox" id={listId} role="listbox" aria-label={`${label}的候选`}>
            {loading && options.length === 0 && <li className="menu-note">搜索中…</li>}
            {error && <li className="menu-note bad-text">{error}</li>}
            {!loading && !error && options.length === 0 && <li className="menu-note">没找到，换个叫法试试</li>}
            {options.map((h, i) => (
              <li
                key={h.appid}
                id={`${id}-opt-${h.appid}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "active" : undefined}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(h);
                }}
                onMouseEnter={() => setActive(i)}
              >
                <img
                  src={h.header}
                  alt=""
                  loading="lazy"
                  width={60}
                  height={22}
                  onError={(e) => {
                    e.currentTarget.style.visibility = "hidden";
                  }}
                />
                <span className="opt-name">
                  {h.name}
                  {h.name_en && h.name_en !== h.name && <small> {h.name_en}</small>}
                </span>
                {h.year && <span className="muted mono">{h.year}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
