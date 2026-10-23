import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  errorMessage,
  setApiLang,
  type CardActionKind,
  type GameHit,
  type Health,
  type LibrarySummary,
  type RecommendResult,
  type Region,
  type RelaxKey,
} from "./api";
import { Backdrop } from "./components/Backdrop";
import { nearMisses, Results, SteamNudge, Understood, type Opened } from "./components/Results";
import { Search } from "./components/Search";
import { Sheet, type ReasonState, type SheetItem } from "./components/Sheet";
import { TopBar } from "./components/TopBar";
import { EXAMPLES } from "./guide";
import { DICTS, initialLang, LangContext, saveLang, useT, type Lang } from "./i18n";
import HOME_ART from "./home_art.json";
import { art, FORM_STEPS, nextRound, progressAt, RELAX_STEPS, shortName, TEXT_STEPS, type Step } from "./present";
import { emptyPrefs, singleForm, type Libs } from "./types";

// ---------- draft kept across the Steam OpenID round trip (no Steam ID in it) ----------

const DRAFT_KEY = "playnext.draft.v2";
const REGION_KEY = "playnext.region";

interface Draft {
  region: Region;
  text: string;
  /** Results were on screen: after the round trip the same request runs again with the library. */
  ran?: boolean;
}

function readBoot(): { draft: Draft | null; sessionId: string | null; connected: number | null } {
  const params = new URLSearchParams(window.location.search);
  const sid = params.get("session_id");
  const connectedRaw = params.get("connected");
  let draft: Draft | null = null;
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY);
    if (raw) draft = JSON.parse(raw) as Draft;
    window.sessionStorage.removeItem(DRAFT_KEY);
  } catch {
    draft = null;
  }
  if (sid || connectedRaw) window.history.replaceState(null, "", window.location.pathname);
  const connected = connectedRaw != null && /^\d+$/.test(connectedRaw) ? Number(connectedRaw) : null;
  return { draft: sid ? draft : null, sessionId: sid, connected };
}

const bootLang = initialLang();
const boot = readBoot();
setApiLang(bootLang);

/** The store the user buys from: their last choice, else CN for Chinese and US for English. */
function initialRegion(lang: Lang): Region {
  if (boot.draft) return boot.draft.region;
  try {
    const r = window.localStorage.getItem(REGION_KEY);
    if (r === "CN" || r === "US") return r;
  } catch {
    /* storage unavailable */
  }
  return lang === "zh" ? "CN" : "US";
}

/** Milliseconds between home-screen examples (sentence typed into the field + its game behind the page). */
const HOME_CYCLE_MS = 7000;
/** How long the played picks stay greyed before the new picks replace them. */
const PLAYED_OUT_MS = 1600;

type Phase = { kind: "loading"; steps: Step[]; t0: number } | { kind: "action" } | null;

const smooth = (): ScrollBehavior => (window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
const NO_REASON: ReasonState = { text: null, llm: false, at: 0 };
const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

export default function App() {
  const [lang, setLang] = useState<Lang>(bootLang);
  const t = DICTS[lang];
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [region, setRegion] = useState<Region>(() => initialRegion(bootLang));
  const [text, setText] = useState(boot.draft?.text ?? "");
  const [sessionId, setSessionId] = useState<string | null>(boot.sessionId);
  const [libs, setLibs] = useState<Libs>(() => (boot.connected != null ? { [boot.connected]: { summary: null } } : {}));

  const [started, setStarted] = useState(false);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [phase, setPhase] = useState<Phase>(null);
  const [error, setError] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<number, ReasonState>>({});
  const [opened, setOpened] = useState<Opened | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [steamOpen, setSteamOpen] = useState(false);
  const [nudgeOff, setNudgeOff] = useState(false);
  const [playedOut, setPlayedOut] = useState<number[]>([]);
  const [homeIdx, setHomeIdx] = useState(0);
  const [homeApp, setHomeApp] = useState<number>(EXAMPLES[0].appid);
  const artRound = useRef({ round: nextRound(HOME_ART, null), pos: 0 });
  const [focusApp, setFocusApp] = useState<number | null>(null);
  const [toast, setToast] = useState<{ text: string; n: number } | null>(null);

  const runSeq = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const llm = health ? health.llm : null;
  const busy = phase !== null;
  const typing = text.trim().length > 0;

  const say = useCallback((s: string) => setToast((o) => ({ text: s, n: (o?.n ?? 0) + 1 })), []);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.title = lang === "zh" ? "Playnext · 下一款玩什么" : "Playnext · What to play next";
  }, [lang]);

  useEffect(() => {
    if (!toast) return undefined;
    const id = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(id);
  }, [toast]);

  // ---------- reference data ----------
  const loadHealth = useCallback(() => {
    setHealthError(null);
    api
      .health()
      .then(setHealth)
      .catch((e: unknown) => setHealthError(errorMessage(e)));
  }, []);
  useEffect(loadHealth, [loadHealth]);

  // home screen: example sentences and their games take turns until the first search; paused while typing.
  // Without free text there are no sentences, so the backdrop cycles through the most-reviewed games instead.
  const gameMode = llm === false;
  useEffect(() => {
    if (started || typing) return undefined;
    const next = () => {
      if (gameMode) {
        const h = artRound.current;
        h.pos += 1;
        if (h.pos >= h.round.length) {
          h.round = nextRound(HOME_ART, h.round[h.round.length - 1]);
          h.pos = 0;
        }
        return h.round[h.pos];
      }
      return null;
    };
    const preload = (a: number) => {
      new Image().src = art(a, "library_hero.jpg");
    };
    if (gameMode) setHomeApp(artRound.current.round[artRound.current.pos]);
    else {
      setHomeApp(EXAMPLES[homeIdx].appid);
      preload(EXAMPLES[(homeIdx + 1) % EXAMPLES.length].appid);
    }
    const id = window.setInterval(() => {
      const a = next();
      if (a != null) setHomeApp(a);
      else setHomeIdx((i) => (i + 1) % EXAMPLES.length);
    }, HOME_CYCLE_MS);
    return () => window.clearInterval(id);
  }, [started, typing, gameMode, homeIdx]);

  function chooseLang(next: Lang) {
    setLang(next);
    setApiLang(next);
    saveLang(next);
  }

  function chooseRegion(r: Region) {
    setRegion(r);
    try {
      window.localStorage.setItem(REGION_KEY, r);
    } catch {
      /* storage unavailable */
    }
  }

  // ---------- results ----------
  function applyResult(r: RecommendResult, seq: number) {
    setResult(r);
    setSessionId(r.session_id);
    // a currency said in the text ("$20 以内") decides the store; show it on the switch
    const said = r.understood.members[0]?.region;
    if (said && said !== region) setRegion(said);
    setLibs((l) => {
      const next = { ...l };
      Object.entries(r.libraries ?? {}).forEach(([k, s]) => {
        next[Number(k)] = { summary: s };
      });
      return next;
    });
    const template = (appid: number, at: number): ReasonState => ({ text: r.picks.find((c) => c.appid === appid)?.reason ?? "", llm: false, at });
    // reasons already shown for a card that is still there are kept as they are
    setReasons((old) => Object.fromEntries(r.picks.map((c) => [c.appid, old[c.appid] ?? NO_REASON])));
    if (!r.picks.length) return;
    const fill = (got: Record<string, { reason: string; source: string }> | null) => {
      if (seq !== runSeq.current) return;
      const at = performance.now();
      setReasons((old) => {
        const next = { ...old };
        r.picks.forEach((c) => {
          if (next[c.appid]?.text != null) return;
          const g = got?.[String(c.appid)];
          next[c.appid] = g?.reason ? { text: g.reason, llm: g.source === "llm", at } : template(c.appid, at);
        });
        return next;
      });
    };
    api
      .reasons(r.session_id)
      .then(fill)
      .catch(() => fill(null));
  }

  async function start(call: () => Promise<RecommendResult>, steps: Step[]): Promise<RecommendResult | null> {
    const seq = ++runSeq.current;
    setStarted(true);
    setGuideOpen(false);
    setError(null);
    setOpened(null);
    setResult(null);
    setReasons({});
    setPlayedOut([]);
    setPhase({ kind: "loading", steps, t0: performance.now() });
    window.scrollTo({ top: 0, behavior: smooth() });
    try {
      const r = await call();
      if (seq !== runSeq.current) return null;
      applyResult(r, seq);
      setFocusApp(r.picks[0]?.appid ?? r.backups[0]?.appid ?? null);
      return r;
    } catch (e) {
      if (seq === runSeq.current) setError(errorMessage(e));
      return null;
    } finally {
      if (seq === runSeq.current) setPhase(null);
    }
  }

  function submit() {
    const s = text.trim();
    if (!s || busy) return;
    void start(() => api.recommend({ session_id: sessionId, text: s, form: singleForm(region, emptyPrefs()) }), TEXT_STEPS);
  }

  function pickGame(g: GameHit) {
    setText(g.name);
    const prefs = { ...emptyPrefs(), seeds: [{ appid: g.appid, name: g.name, year: g.year }] };
    void start(() => api.recommend({ session_id: sessionId, form: singleForm(region, prefs) }), FORM_STEPS);
  }

  function relaxText(change: string) {
    if (!result || busy) return;
    const sid = result.session_id;
    void start(() => api.followup(sid, change), TEXT_STEPS);
  }

  function relaxKey(key: RelaxKey) {
    if (!result || busy) return;
    const sid = result.session_id;
    void start(() => api.relax(sid, key), RELAX_STEPS).then((r) => r && say(t.relaxed));
  }

  /** × : drop the request, the results and any pending answer, and go back to the home screen. */
  function reset() {
    runSeq.current += 1;
    setStarted(false);
    setResult(null);
    setPhase(null);
    setError(null);
    setReasons({});
    setOpened(null);
    setGuideOpen(false);
    setPlayedOut([]);
    setText("");
    setFocusApp(null);
    window.scrollTo({ top: 0, behavior: smooth() });
    inputRef.current?.focus();
  }

  async function cardAction(appid: number, action: CardActionKind) {
    if (!result || busy) return;
    const seq = ++runSeq.current;
    const name = shortName([...result.picks, ...result.backups].find((c) => c.appid === appid)?.name ?? "");
    setPhase({ kind: "action" });
    try {
      const r = await api.card(result.session_id, appid, action, 0);
      if (seq !== runSeq.current) return;
      applyResult(r, seq);
      const stays = r.picks.some((c) => c.appid === appid) || r.backups.some((b) => b.appid === appid);
      if (!stays || action === "played" || action === "not_interested") setOpened(null);
      if (r.feedback && (action === "liked" || action === "disliked")) {
        say(t.feedbackToast(action === "liked" ? t.like : t.dislike, name, r.feedback.message));
      } else if (!stays) say(t.replaced(name));
    } catch (e) {
      if (seq === runSeq.current) say(errorMessage(e));
    } finally {
      if (seq === runSeq.current) setPhase(null);
    }
  }

  // ---------- Steam ----------
  /** Results are on screen and a library came in: run the same request again; played picks grey out, then go. */
  async function rerunWithLibrary(sid: string) {
    const old = result;
    const seq = ++runSeq.current;
    setPhase({ kind: "loading", steps: RELAX_STEPS, t0: performance.now() });
    try {
      const r = await api.rerun(sid);
      if (seq !== runSeq.current) return;
      const out = (r.played_out ?? []).filter((a) => old?.picks.some((c) => c.appid === a));
      if (out.length) {
        setPhase(null);
        setPlayedOut(out);
        await sleep(PLAYED_OUT_MS);
        if (seq !== runSeq.current) return;
        setPlayedOut([]);
      }
      applyResult(r, seq);
      const names = out.map((a) => shortName(old?.picks.find((c) => c.appid === a)?.name ?? ""));
      say(out.length === 1 ? t.swappedOne(names[0]) : out.length > 1 ? t.swappedN(out.length) : t.libApplied);
    } catch (e) {
      if (seq === runSeq.current) say(errorMessage(e));
    } finally {
      if (seq === runSeq.current) setPhase(null);
    }
  }

  const onConnected = (sid: string, member: number, summary: LibrarySummary) => {
    setSessionId(sid);
    setLibs((l) => ({ ...l, [member]: { summary } }));
    setSteamOpen(false);
    if (result && !busy && summary.public) void rerunWithLibrary(result.session_id);
    else say(t.steamConnectedToast);
  };

  // back from Steam sign-in: if results were on screen, bring them back with the library applied
  useEffect(() => {
    if (boot.connected == null) return;
    if (boot.sessionId && boot.draft?.ran) {
      const sid = boot.sessionId;
      void start(() => api.rerun(sid), RELAX_STEPS).then((r) => r && say(DICTS[bootLang].libApplied));
    } else say(DICTS[bootLang].steamConnectedToast);
  }, []);

  function onLogin(member: number) {
    try {
      window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ region, text, ran: !!result } satisfies Draft));
    } catch {
      /* storage unavailable: the text is lost after the round trip, the connection still works */
    }
    window.location.assign(api.steamLoginUrl(result?.session_id ?? sessionId, member));
  }

  function disconnect() {
    reset();
    setSessionId(null);
    setLibs({});
    say(t.steamDisconnected);
  }

  function openSteam() {
    window.scrollTo({ top: 0, behavior: smooth() });
    setSteamOpen(true);
  }

  // ---------- render ----------
  const group = (result?.understood.party_size ?? 1) > 1;
  let sheetItem: SheetItem | null = null;
  if (opened && result) {
    if (opened.kind === "pick") {
      const card = result.picks.find((c) => c.appid === opened.appid);
      if (card) sheetItem = { kind: "pick", card, reason: reasons[card.appid] ?? NO_REASON };
    } else if (opened.kind === "backup") {
      const backup = result.backups.find((b) => b.appid === opened.appid);
      if (backup) sheetItem = { kind: "backup", backup };
    } else {
      const miss = nearMisses(result).find((m) => m.appid === opened.appid);
      if (miss) sheetItem = { kind: "miss", miss };
    }
  }
  const backdropApp = started && focusApp != null ? focusApp : homeApp;
  const myLib = libs[0];
  const libCount = myLib ? (myLib.summary?.public ? myLib.summary.owned : NaN) : null;
  const nudge = !!result && result.picks.length > 0 && !myLib && !nudgeOff && phase?.kind !== "loading";

  return (
    <LangContext.Provider value={lang}>
      <div className={`app${started ? " running" : ""}${guideOpen ? " guiding" : ""}`}>
        <Backdrop appid={backdropApp} />
        <TopBar
          lang={lang}
          onLang={chooseLang}
          region={region}
          onRegion={chooseRegion}
          storeLocked={started}
          sessionId={result?.session_id ?? sessionId}
          myLib={myLib}
          steamOpen={steamOpen}
          onSteamOpen={setSteamOpen}
          ping={nudge}
          onConnected={onConnected}
          onLogin={onLogin}
          onDisconnect={disconnect}
        />
        <main>
          <section className="hero">
            <h1>{t.title}</h1>
            <Search
              ref={inputRef}
              text={text}
              onText={setText}
              onSubmit={submit}
              onReset={reset}
              running={started}
              busy={busy}
              llm={llm}
              onPickGame={pickGame}
              guideOpen={guideOpen}
              onGuide={setGuideOpen}
              ghost={t.examples[homeIdx][0]}
              onExample={(s, appid) => {
                setText(s);
                setGuideOpen(false);
                if (started) setFocusApp(appid);
                else setHomeApp(appid);
                window.scrollTo({ top: 0, behavior: smooth() });
                inputRef.current?.focus();
              }}
              onFocusGame={(a) => (started ? setFocusApp(a) : setHomeApp(a))}
              onOpenSteam={openSteam}
              libCount={libCount}
            />
            {healthError && (
              <p className="error-line" role="alert">
                {healthError}
                <button type="button" className="link" onClick={loadHealth}>
                  {t.retry}
                </button>
              </p>
            )}
          </section>

          <div className="stage" aria-live="polite">
            {result && <Understood result={result} />}
            {phase?.kind === "loading" && <Status steps={phase.steps} t0={phase.t0} />}
            {error && (
              <p className="error-line" role="alert">
                {error}
              </p>
            )}
            {nudge && result && <SteamNudge picks={result.picks.map((c) => c.appid)} onImport={openSteam} onDismiss={() => setNudgeOff(true)} />}
            {result && (
              <Results
                result={result}
                busy={phase?.kind === "action" || playedOut.length > 0}
                playedOut={playedOut}
                onOpen={(o) => {
                  setOpened(o);
                  setFocusApp(o.appid);
                }}
                onFocusGame={setFocusApp}
                onRelax={relaxText}
              />
            )}
          </div>

          {result && (
            <footer className="foot">
              {t.footer}
              {health?.price_snapshot && <> · {t.snapshot(/^\d{4}-\d{2}-\d{2}/.exec(health.price_snapshot)?.[0] ?? health.price_snapshot)}</>}
            </footer>
          )}
        </main>

        <Sheet
          item={sheetItem}
          group={group}
          busy={phase?.kind === "action"}
          sessionId={result?.session_id ?? sessionId}
          onAction={(a, k) => void cardAction(a, k)}
          onRelax={relaxKey}
          onClose={() => setOpened(null)}
        />
        <div className={`toast${toast ? " show" : ""}`} role="status">
          {toast?.text}
        </div>
      </div>
    </LangContext.Provider>
  );
}

/** One line and a thin bar while a request runs; the steps advance on measured timings. */
function Status({ steps, t0 }: { steps: Step[]; t0: number }) {
  const t = useT();
  const [sec, setSec] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setSec((performance.now() - t0) / 1000), 200);
    return () => window.clearInterval(id);
  }, [t0]);
  const { label, frac } = progressAt(steps, sec);
  return (
    <>
      <div className="status" role="status">
        <span className="spin" aria-hidden="true" />
        <span>{t[label]}</span>
      </div>
      <div className="pbar" aria-hidden="true">
        <i style={{ width: `${frac * 100}%` }} />
      </div>
    </>
  );
}
