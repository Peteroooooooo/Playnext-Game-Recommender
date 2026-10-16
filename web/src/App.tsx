import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  errorMessage,
  type CardActionKind,
  type Health,
  type LibrarySummary,
  type RecommendBody,
  type RecommendResult,
  type ReasonsResponse,
  type Region,
  type TagsResponse,
} from "./api";
import { AskBox } from "./components/AskBox";
import { LoadingSteps } from "./components/LoadingSteps";
import { PartyPanel } from "./components/PartyPanel";
import { Questionnaire } from "./components/Questionnaire";
import { ResultView, type ReasonsState } from "./components/ResultView";
import { TopBar } from "./components/TopBar";
import {
  defaultParty,
  emptyPrefs,
  groupForm,
  hasSingleInput,
  MAX_MEMBERS,
  newMember,
  singleForm,
  type CardNote,
  type Libs,
  type Mode,
  type Party,
  type Prefs,
} from "./types";

// ---------- draft kept across the Steam OpenID round trip (no Steam ID in it, only counts) ----------

const DRAFT_KEY = "playnext.draft.v1";

interface Draft {
  mode: Mode;
  region: Region;
  prefs: Prefs;
  party: Party;
  texts: Record<Mode, string>;
  libs: Libs;
}

interface Boot {
  draft: Draft | null;
  sessionId: string | null;
  connected: number | null;
}

function readBoot(): Boot {
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
  if (sid || connectedRaw) {
    // Drop the query string so a reload does not replay it.
    window.history.replaceState(null, "", window.location.pathname);
  }
  const connected = connectedRaw != null && /^\d+$/.test(connectedRaw) ? Number(connectedRaw) : null;
  return { draft: sid ? draft : null, sessionId: sid, connected };
}

const boot = readBoot();

/** "2026-10-14T03:00:00Z" → "2026-10-14"; anything else is shown as sent. */
function snapshotDate(s: string): string {
  return /^\d{4}-\d{2}-\d{2}/.exec(s)?.[0] ?? s;
}

type Phase = { kind: "loading"; slow: boolean; follow?: boolean } | { kind: "action" } | null;

export default function App() {
  const d = boot.draft;
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [tags, setTags] = useState<TagsResponse | null>(null);

  const [region, setRegion] = useState<Region>(d?.region ?? "CN");
  const [mode, setMode] = useState<Mode>(d?.mode ?? "single");
  const [sessionId, setSessionId] = useState<string | null>(boot.sessionId);
  const [libs, setLibs] = useState<Libs>(() => {
    const base: Libs = { ...(d?.libs ?? {}) };
    if (boot.connected != null) base[boot.connected] = base[boot.connected] ?? { summary: null };
    return base;
  });
  const [texts, setTexts] = useState<Record<Mode, string>>(d?.texts ?? { single: "", group: "" });
  const [prefs, setPrefs] = useState<Prefs>(d?.prefs ?? emptyPrefs());
  const [quizOpen, setQuizOpen] = useState(false);
  const [party, setParty] = useState<Party>(d?.party ?? defaultParty(d?.region ?? "CN"));

  const [result, setResult] = useState<RecommendResult | null>(null);
  const [resultMode, setResultMode] = useState<Mode>("single");
  const [phase, setPhase] = useState<Phase>(null);
  const [error, setError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(
    boot.connected != null ? `已通过 Steam 登录连接${boot.connected === 0 ? "你的" : `第 ${boot.connected + 1} 位成员的`}游戏库。` : null,
  );
  const [reasons, setReasons] = useState<ReasonsResponse>({});
  const [reasonsState, setReasonsState] = useState<ReasonsState>("idle");
  const [followText, setFollowText] = useState("");
  const [cardNote, setCardNote] = useState<CardNote | null>(null);

  const reasonsSeq = useRef(0);
  const resultsRef = useRef<HTMLElement>(null);
  const followRef = useRef<HTMLTextAreaElement>(null);

  const llm = health ? health.llm : null;
  const text = texts[mode];
  const busy = phase !== null;

  // ---------- reference data ----------
  const loadHealth = useCallback(() => {
    setHealthError(null);
    api
      .health()
      .then(setHealth)
      .catch((e: unknown) => setHealthError(errorMessage(e)));
    api
      .tags()
      .then(setTags)
      .catch(() => setTags({ common: [], all: [] }));
  }, []);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  useEffect(() => {
    if (llm === false) setQuizOpen(true);
  }, [llm]);

  // ---------- libraries ----------
  const onConnected = useCallback((sid: string, member: number, summary: LibrarySummary) => {
    setSessionId(sid);
    setLibs((l) => ({ ...l, [member]: { summary } }));
  }, []);

  function onLogin(member: number) {
    const draft: Draft = { mode, region, prefs, party, texts, libs };
    try {
      window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* storage unavailable: the form is lost after the round trip, the connection still works */
    }
    window.location.assign(api.steamLoginUrl(sessionId, member));
  }

  function resetSession(msg: string) {
    setSessionId(null);
    setLibs({});
    setResult(null);
    setReasons({});
    setCardNote(null);
    reasonsSeq.current += 1;
    setBanner(msg);
  }

  function onRegion(r: Region) {
    setRegion(r);
    setParty((p) => ({ ...p, members: p.members.map((m, i) => (i === 0 ? { ...m, region: r } : m)) }));
  }

  // ---------- party ----------
  function addMember() {
    setParty((p) =>
      p.members.length >= MAX_MEMBERS
        ? p
        : { ...p, members: [...p.members, newMember(`朋友 ${p.members.length + 1}`, region, p.members.length + 1)] },
    );
  }

  function removeMember(i: number) {
    // The backend keys libraries by member position; removing someone before a connected member would
    // attach a library to the wrong person, so start a fresh session in that case.
    const affected = Object.keys(libs)
      .map(Number)
      .some((k) => k >= i);
    setParty((p) => ({
      ...p,
      members: p.members.filter((_, j) => j !== i).map((m) => ({ ...m, site: Math.min(m.site, p.members.length - 1) })),
    }));
    if (affected) resetSession("成员顺序变了，已重新开始会话；需要的话请重新连接 Steam。");
  }

  // ---------- requests ----------
  function applyResult(r: RecommendResult, forMode: Mode) {
    setResult(r);
    setResultMode(forMode);
    setSessionId(r.session_id);
    setLibs((l) => {
      const next = { ...l };
      Object.entries(r.libraries ?? {}).forEach(([k, s]) => {
        next[Number(k)] = { summary: s };
      });
      return next;
    });
    const seq = ++reasonsSeq.current;
    setReasons({});
    if (r.picks.length) {
      setReasonsState("loading");
      api
        .reasons(r.session_id)
        .then((res) => {
          if (seq === reasonsSeq.current) {
            setReasons(res);
            setReasonsState("done");
          }
        })
        .catch(() => {
          if (seq === reasonsSeq.current) setReasonsState("error");
        });
    } else {
      setReasonsState("idle");
    }
  }

  async function run(call: () => Promise<RecommendResult>, p: Exclude<Phase, null>, forMode: Mode): Promise<boolean> {
    setError(null);
    setCardNote(null);
    setPhase(p);
    if (p.kind === "loading") {
      window.requestAnimationFrame(() =>
        resultsRef.current?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
          block: "start",
        }),
      );
    }
    try {
      const r = await call();
      applyResult(r, forMode);
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setPhase(null);
    }
  }

  function submit() {
    if (busy) return;
    const t = llm === false ? "" : text.trim();
    let body: RecommendBody;
    if (mode === "single") {
      if (!t && !hasSingleInput(prefs) && !libs[0]) {
        setError("先说说想玩什么，或在问卷里选一款喜欢的游戏、想要的感觉，也可以连接 Steam 游戏库。");
        setQuizOpen(true);
        return;
      }
      body = { session_id: sessionId, text: t || null, form: singleForm(region, prefs) };
    } else {
      body = { session_id: sessionId, text: t || null, form: groupForm(party) };
    }
    setBanner(null);
    void run(() => api.recommend(body), { kind: "loading", slow: Boolean(t) }, mode);
  }

  function cardAction(appid: number, action: CardActionKind, member = 0) {
    if (!result || busy) return;
    const sid = result.session_id;
    const name = result.picks.find((c) => c.appid === appid)?.name ?? "";
    // Goes through run/applyResult like every card action, so the reasonsSeq guard still drops stale reasons.
    void run(
      async () => {
        const r = await api.card(sid, appid, action, member);
        if ((action === "liked" || action === "disliked") && r.feedback) {
          setCardNote({ appid, name, action, member, saved: r.feedback.saved, text: r.feedback.message });
        }
        return r;
      },
      { kind: "action" },
      resultMode,
    );
  }

  async function followUp() {
    const t = followText.trim();
    if (!result || !t || busy) return;
    const ok = await run(() => api.followup(result.session_id, t), { kind: "loading", slow: true, follow: true }, resultMode);
    if (ok) setFollowText("");
  }

  const showResult = result && resultMode === mode;

  return (
    <>
      <a className="skip" href="#results">
        跳到推荐结果
      </a>
      <TopBar
        region={region}
        onRegion={onRegion}
        sessionId={sessionId}
        myLib={libs[0]}
        onConnected={onConnected}
        onLogin={onLogin}
        onDisconnect={() => resetSession("已断开 Steam 游戏库，并重新开始会话。")}
      />
      <main className="wrap" id="top">
        {healthError && (
          <div className="notice bad" role="alert">
            {healthError}
            <button type="button" className="link" onClick={loadHealth}>
              重试
            </button>
          </div>
        )}
        {!health && !healthError && (
          <p className="hint loading-line" role="status">
            正在连接推荐服务（第一次启动要加载数据，可能需要几秒）…
          </p>
        )}

        <AskBox
          mode={mode}
          onMode={(m) => {
            setMode(m);
            setError(null);
          }}
          text={text}
          onText={(t) => setTexts((x) => ({ ...x, [mode]: t }))}
          onSubmit={submit}
          llm={llm}
          busy={busy}
        />

        {banner && (
          <p className="notice info banner" role="status">
            {banner}
            <button type="button" className="x" aria-label="关闭提示" onClick={() => setBanner(null)}>
              ×
            </button>
          </p>
        )}

        {mode === "single" ? (
          <Questionnaire
            prefs={prefs}
            onChange={setPrefs}
            tags={tags}
            region={region}
            open={quizOpen}
            onToggle={() => setQuizOpen((o) => !o)}
            onSubmit={submit}
            busy={busy}
            textInUse={llm !== false && text.trim() !== ""}
            libConnected={Boolean(libs[0])}
          />
        ) : (
          <PartyPanel
            party={party}
            onChange={setParty}
            tags={tags}
            libs={libs}
            sessionId={sessionId}
            defaultRegion={region}
            onConnected={onConnected}
            onLogin={onLogin}
            onAddMember={addMember}
            onRemoveMember={removeMember}
            onSubmit={submit}
            busy={busy}
            textInUse={llm !== false && text.trim() !== ""}
          />
        )}

        {error && (
          <div className="notice bad error-box" role="alert">
            {error}
          </div>
        )}

        <section id="results" ref={resultsRef} className="results-anchor" aria-label="推荐结果" tabIndex={-1}>
          {phase?.kind === "loading" ? (
            <LoadingSteps slow={phase.slow} title={phase.follow ? "正在按新条件重新挑选" : "正在挑选"} />
          ) : showResult ? (
            <ResultView
              ref={followRef}
              result={result}
              reasons={reasons}
              reasonsState={reasonsState}
              busy={phase?.kind === "action"}
              onAction={cardAction}
              cardNote={cardNote}
              followText={followText}
              onFollowText={setFollowText}
              onFollowSubmit={() => void followUp()}
              followBusy={busy}
              llm={llm}
            />
          ) : (
            <div className="empty">
              <p>
                {mode === "single"
                  ? "写下你想玩什么，或打开问卷点选，推荐会出现在这里。"
                  : "填好一起玩的人和条件，推荐会出现在这里。"}
              </p>
            </div>
          )}
        </section>

        <footer className="foot">
          <p>
            推荐只用公开的游戏数据：标签、同好推荐、开发商和系列、价格与史低、人数上限。口碑标为〔主观〕，价格只陈述事实，不做购买建议。
            {health && <> 推荐库共 {health.games.toLocaleString("zh-CN")} 款游戏。</>}
          </p>
          <p>数据来源：Steam 商店、IGDB、IsThereAnyDeal、Kaggle「steam-reviews-100m」（sergiodelcarpio，MIT）与 Steam 评测接口。价格数据由 IsThereAnyDeal 提供。</p>
          {health?.price_snapshot && (
            <p className="muted">
              价格快照：<span className="mono">{snapshotDate(health.price_snapshot)}</span>
            </p>
          )}
        </footer>
      </main>
    </>
  );
}
