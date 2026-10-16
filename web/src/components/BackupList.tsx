import { useId, useMemo, useState } from "react";
import type { Backup, PriceFacts } from "../api";
import { CURRENCY, parseBudget, SETUP_ZH } from "../types";
import { SeriesButton, SeriesList } from "./Series";

const BACKUPS_SHOWN = 6;

type PriceFilter = "all" | "discount" | "near_low" | "free";

const isFree = (p: PriceFacts) => p.free === true || p.final === 0;

const FILTERS: { key: PriceFilter; label: string; test: (p: PriceFacts) => boolean }[] = [
  { key: "all", label: "全部", test: () => true },
  { key: "discount", label: "正在打折", test: (p) => (p.discount_pct ?? 0) > 0 },
  { key: "near_low", label: "接近史低", test: (p) => p.near_low === true },
  { key: "free", label: "免费", test: isFree },
];

/** Price cap in the backup's own currency; a game with no known price never passes a cap. */
function underCap(p: PriceFacts, cap: number | null): boolean {
  if (cap == null || isFree(p)) return true;
  return p.final != null && p.final <= cap;
}

/** The shortlist, filtered by live price on the client (no new request). */
export function BackupList({ backups }: { backups: Backup[] }) {
  const uid = useId();
  const [filter, setFilter] = useState<PriceFilter>("all");
  const [capText, setCapText] = useState("");
  const [all, setAll] = useState(false);
  const cap = parseBudget(capText);

  const regions = Array.from(new Set(backups.map((b) => b.price.region)));
  const symbol = regions.length === 1 ? CURRENCY[regions[0]] : regions.map((r) => CURRENCY[r]).join(" / ");

  const counts = useMemo(() => {
    const capped = backups.filter((b) => underCap(b.price, cap));
    return Object.fromEntries(FILTERS.map((f) => [f.key, capped.filter((b) => f.test(b.price)).length])) as Record<
      PriceFilter,
      number
    >;
  }, [backups, cap]);

  const test = FILTERS.find((f) => f.key === filter)?.test ?? (() => true);
  const matched = backups.filter((b) => test(b.price) && underCap(b.price, cap));
  const shown = all ? matched : matched.slice(0, BACKUPS_SHOWN);
  const filtering = filter !== "all" || cap != null;

  return (
    <section className="sub" aria-labelledby="backups-title">
      <div className="sub-head">
        <h3 id="backups-title">备选</h3>
        <span className="hint">也符合条件，排在后面</span>
      </div>

      <div className="backup-filter">
        <div className="chips" role="group" aria-label="按价格筛选备选">
          {FILTERS.map((f) => (
            <button
              type="button"
              className="toggle"
              key={f.key}
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
              <span className="count mono" aria-hidden="true">
                {counts[f.key]}
              </span>
              <span className="sr-only">，{counts[f.key]} 款</span>
            </button>
          ))}
        </div>
        <div className="money-input price-cap">
          <label htmlFor={`${uid}-cap`}>价格不超过</label>
          <span aria-hidden="true">{symbol}</span>
          <input
            id={`${uid}-cap`}
            className="input sm"
            type="number"
            inputMode="decimal"
            min={0}
            step="any"
            placeholder="不限"
            value={capText}
            onChange={(e) => setCapText(e.target.value)}
            aria-describedby={regions.length > 1 ? `${uid}-cap-hint` : undefined}
          />
          {regions.length > 1 && (
            <span className="hint" id={`${uid}-cap-hint`}>
              各按自己商店区的币种比较
            </span>
          )}
        </div>
        <p className="hint backup-count" role="status">
          显示 <span className="mono">{matched.length}</span> / <span className="mono">{backups.length}</span> 款
        </p>
      </div>

      {matched.length > 0 ? (
        <ul className="backup-list">
          {shown.map((b) => (
            <BackupRow b={b} key={b.appid} />
          ))}
        </ul>
      ) : (
        <div className="filter-empty">
          <p>没有符合筛选的备选</p>
          {filtering && (
            <button
              type="button"
              className="link"
              onClick={() => {
                setFilter("all");
                setCapText("");
              }}
            >
              清除筛选
            </button>
          )}
        </div>
      )}
      {matched.length > BACKUPS_SHOWN && (
        <button type="button" className="more" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? "收起" : `再看 ${matched.length - BACKUPS_SHOWN} 款`}
        </button>
      )}
    </section>
  );
}

function BackupRow({ b }: { b: Backup }) {
  const uid = useId();
  const [seriesOpen, setSeriesOpen] = useState(false);
  const names = b.series_names ?? [];
  const seriesCount = Math.max(b.same_series ?? 0, names.length);
  const labels: { text: string; cls: string }[] = [];
  if (b.label) labels.push({ text: b.label, cls: "warn" });
  if (b.owned) labels.push({ text: b.owned, cls: "good" });
  if (b.price.near_low) labels.push({ text: "接近史低", cls: "good" });
  if (seriesCount && !names.length) labels.push({ text: `同系列另有 ${seriesCount} 款`, cls: "neutral" });
  if (b.setup) labels.push({ text: SETUP_ZH[b.setup], cls: "accent" });
  return (
    <li className="backup">
      <div className="backup-main">
        <a href={`https://store.steampowered.com/app/${b.appid}/`} target="_blank" rel="noopener noreferrer">
          {b.name}
          <span className="sr-only">（Steam 商店页，新窗口打开）</span>
        </a>
        <span className="labels">
          {b.pct_positive != null && !b.label && <span className="pill neutral">好评 {b.pct_positive}%</span>}
          {labels.map((l) => (
            <span className={`pill ${l.cls}`} key={l.text}>
              {l.text}
            </span>
          ))}
          {names.length > 0 && (
            <SeriesButton
              className="pill neutral pill-btn"
              count={seriesCount}
              open={seriesOpen}
              onToggle={() => setSeriesOpen((o) => !o)}
              controls={`${uid}-series`}
            />
          )}
        </span>
      </div>
      <span className="backup-price mono">{b.price.text}</span>
      {names.length > 0 && <SeriesList id={`${uid}-series`} names={names} count={seriesCount} open={seriesOpen} />}
    </li>
  );
}
