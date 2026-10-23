import { useEffect, useState } from "react";
import { BOOST_DEMO, EXAMPLES, STORE_DEMO, addPart, removePart, splitParts } from "../guide";
import { useT } from "../i18n";
import { art } from "../present";
import { LockIcon, SteamIcon } from "./icons";

interface Props {
  id: string;
  text: string;
  onText: (t: string) => void;
  /** An example was picked: fill the field, close the guide, show its game behind the page. */
  onExample: (text: string, appid: number) => void;
  onFocusGame: (appid: number) => void;
  onOpenSteam: () => void;
  /** null: no library; a number: games imported (NaN when the count is not known yet). */
  libCount: number | null;
}

/** Two looks of one demo card that alternate every 3.2 s until the user touches it. */
function useAlternate<T extends string>(a: T, b: T): [T, (v: T) => void, () => void] {
  const [v, setV] = useState<T>(a);
  const [auto, setAuto] = useState(true);
  useEffect(() => {
    if (!auto || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    const id = window.setInterval(() => setV((x) => (x === a ? b : a)), 3200);
    return () => window.clearInterval(id);
  }, [auto, a, b]);
  return [v, (x: T) => { setAuto(false); setV(x); }, () => setAuto(false)];
}

function Seg<T extends string>({ value, options, label, onPick }: { value: T; options: [T, string][]; label: string; onPick: (v: T) => void }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button type="button" key={v} aria-pressed={value === v} onClick={() => onPick(v)}>
          {text}
        </button>
      ))}
    </div>
  );
}

export function Guide({ id, text, onText, onExample, onFocusGame, onOpenSteam, libCount }: Props) {
  const t = useT();
  const [boost, setBoost, stopBoost] = useAlternate<"before" | "after">("before", "after");
  const [store, setStore, stopStore] = useAlternate<"CN" | "US">("CN", "US");
  const sep = t.comma;
  const have = new Set(splitParts(text, sep));

  function togglePart(i: number, p: string) {
    if (i === t.partNeedsLib && libCount == null) {
      onOpenSteam();
      return;
    }
    onText(have.has(p) ? removePart(text, p, sep) : addPart(text, p, sep));
  }

  return (
    <div className="guide" id={id}>
      <section>
        <div className="anatomy">
          {t.anatomy.map(([b, i]) => (
            <span key={b}>
              <b>{b}</b>
              <i>{i}</i>
            </span>
          ))}
        </div>
        <div className="parts">
          <span className="parts-lbl">{t.partsLbl}</span>
          {t.parts.map((p, i) => (
            <button type="button" key={p} className={`part${have.has(p) ? " added" : ""}`} aria-pressed={have.has(p)} onClick={() => togglePart(i, p)}>
              {p}
            </button>
          ))}
        </div>
      </section>

      <section className="duo">
        <div className={`gcard${boost === "after" ? " after" : ""}`} onMouseEnter={stopBoost}>
          <h2>{t.boostTitle}</h2>
          <Seg value={boost} label={t.boostTitle} options={[["before", t.boostBefore], ["after", t.boostAfter]]} onPick={setBoost} />
          <div className="gshelf" aria-hidden="true">
            {BOOST_DEMO.map((x) => (
              <div className={`bp${x.after ? " swap" : ""}${x.before ? " owned" : ""}`} key={x.appid}>
                <div className="pic">
                  <img className="a" src={art(x.appid, "library_600x900.jpg")} alt="" />
                  {x.after && <img className="b" src={art(x.after, "library_600x900.jpg")} alt="" />}
                  {x.before && <em className="a">{t.boostPlayed}</em>}
                  {x.label && <em className="b">{x.label === "like" ? t.boostLike : t.boostTaste}</em>}
                </div>
              </div>
            ))}
          </div>
          <p className="gcap">{boost === "after" ? t.boostCapAfter : t.boostCapBefore}</p>
          {libCount != null ? (
            <p className="done">{t.boostDone(Number.isNaN(libCount) ? null : libCount)}</p>
          ) : (
            <div>
              <button type="button" className="cta" onClick={onOpenSteam}>
                <SteamIcon />
                {t.steamImport}
              </button>
              <p className="fine">{t.steamFine}</p>
            </div>
          )}
        </div>

        <div className="gcard store" onMouseEnter={stopStore}>
          <h2>{t.storeTitle}</h2>
          <Seg value={store} label={t.storeTitle} options={[["CN", `¥ ${t.regionName.CN}`], ["US", `$ ${t.regionName.US}`]]} onPick={setStore} />
          <div className="gshelf" aria-hidden="true">
            {STORE_DEMO.map((x) => {
              const blocked = store === "CN" && x.cn == null;
              return (
                <div className={`bp${blocked ? " blocked" : ""}`} key={x.appid}>
                  <div className="pic">
                    <img className="a" src={art(x.appid, "library_600x900.jpg")} alt="" />
                    {x.cn == null && <em className="a">{t.storeBlocked}</em>}
                  </div>
                  <p className="price">{blocked ? t.storeNotShown : store === "CN" ? x.cn : x.us}</p>
                </div>
              );
            })}
          </div>
          <p className="gcap">{store === "CN" ? t.storeCapCN : t.storeCapUS}</p>
          <p className="lock-note">
            <LockIcon />
            <span>
              {t.lockNote[0]} <b className="x-glyph" aria-label="×">×</b> {t.lockNote[1]}
            </span>
          </p>
        </div>
      </section>

      <section>
        <h2 className="g-title">{t.exTitle}</h2>
        <p className="g-sub">{t.exSub}</p>
        <div className="gallery">
          {t.exGroups.map((name, gi) => (
            <div className="ex-group" key={name}>
              <h3>{name}</h3>
              <div className="ex-grid">
                {EXAMPLES.map((x, i) =>
                  x.group !== gi ? null : (
                    <button
                      type="button"
                      className="ex"
                      key={x.appid}
                      onClick={() => onExample(t.examples[i][0], x.appid)}
                      onMouseEnter={() => onFocusGame(x.appid)}
                      onFocus={() => onFocusGame(x.appid)}
                    >
                      <div className="art">
                        <img src={art(x.appid, "header.jpg")} alt="" decoding="async" />
                      </div>
                      <p>{t.examples[i][0]}</p>
                      <small>{t.exFind(t.examples[i][1])}</small>
                    </button>
                  ),
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
