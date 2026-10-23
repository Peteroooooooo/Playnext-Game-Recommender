// Typed client for the Playnext FastAPI backend (src/playnext/api.py).
// Shapes follow web_fixtures/api_samples.json; optional fields are the ones the backend only sets sometimes.
import { DICTS, type Lang } from "./i18n";

/** Language sent with every request; the backend writes its text in it. */
let apiLang: Lang = "zh";
export function setApiLang(l: Lang) {
  apiLang = l;
}
const T = () => DICTS[apiLang];

export type Region = "CN" | "US";
export type Platform = "windows" | "mac" | "linux" | "deck";
export type AvoidContent = "gore" | "sexual";
export type SetupKind = "online" | "local" | "remote" | "hybrid";
export type Interaction = "coop" | "versus" | "any";
export type PriceIntent = "none" | "cheap" | "near_record_low";
export type LibraryPolicy = "none" | "prefer_owned" | "exclude_owned";
export type BudgetScope = "per_person" | "team_total";
/** played / owned / not_interested change this session; liked / disliked are taste feedback kept for later sessions. */
export type CardActionKind = "played" | "owned" | "not_interested" | "liked" | "disliked";
export type FeedbackKind = Extract<CardActionKind, "liked" | "disliked">;
export type ReportField = "players" | "modes" | "price" | "tags" | "other";

// ---------- reference data ----------

export interface Health {
  ok: boolean;
  games: number;
  llm: boolean;
  /** Date of the price snapshot the backend serves (YYYY-MM-DD, may carry a time part). */
  price_snapshot?: string | null;
  pg?: boolean;
}

export interface GameHit {
  appid: number;
  name: string;
  name_en: string;
  year: number | null;
  header: string;
}

export interface Tag {
  tagid: number;
  name: string;
  name_en: string;
}

export interface TagsResponse {
  common: Tag[];
  all: Tag[];
}

// ---------- library ----------

export interface LibrarySummary {
  public: boolean;
  owned: number;
  in_core: number;
  played: number;
  playtime_hidden: boolean;
  /** Most-played owned games outside the core library, named from the light index. */
  outside_top?: string[];
  top: { name: string; hours: number }[];
}

export interface LibraryResponse {
  session_id: string;
  member: number;
  library: LibrarySummary;
}

// ---------- request ----------

export interface MemberForm {
  name: string;
  region: Region;
  seeds: number[];
  feel_want: number[];
  feel_avoid: number[];
  avoid_tags: number[];
  avoid_content: AvoidContent[];
  language: "schinese" | null;
  platform: Platform | null;
  owned_extra: number[];
  site: number | null;
  /** Free-text taste for this member ("想玩什么"), max 200 chars; omitted when empty. */
  preference_text?: string;
}

export interface RecommendForm {
  members: MemberForm[];
  seeds: number[];
  feel_want: number[];
  feel_avoid: number[];
  budget: number | null;
  budget_scope: BudgetScope;
  price_intent: PriceIntent;
  interaction: Interaction;
  setup: SetupKind | null;
  library_policy: LibraryPolicy;
  /** Solo only: the player will play alone, so the game needs a single-player mode. */
  single_player?: boolean;
}

export interface RecommendBody {
  session_id?: string | null;
  text?: string | null;
  form?: RecommendForm | null;
}

// ---------- result ----------

export interface PriceFacts {
  region: Region;
  text: string;
  free?: boolean;
  final?: number | null;
  low?: number | null;
  low_time?: string | null;
  discount_pct?: number;
  /** Current price within 5% of the record low. */
  near_low?: boolean;
  source?: string;
  as_of?: string;
  note?: string;
}

export interface Diff {
  more: string[];
  less: string[];
  anchor: string;
}

export interface Colike {
  anchor: string;
  co_count: number;
  rank: number;
  text: string;
}

export interface Like {
  anchor?: string | null;
  shared_core_tags?: string[];
  feel_hits?: string[];
  feel_bad?: string[];
  quote?: string | null;
}

export interface Rating {
  pct_positive: number | null;
  reviews: number;
  smoothed: number;
  text: string;
  below_floor: boolean;
}

export interface Setup {
  kind: SetupKind;
  kind_zh: string;
  players: number;
  max_players: number | null;
  max_source: string | null;
  steps: string[];
  controller: string | null;
  purchase?: string;
  /** Other ways to buy, e.g. "也可以由小李当主机：$9.99". */
  alternatives?: string[];
  mode_text: string;
  friends_pass?: string;
  note: string;
}

export interface LineagePath {
  text: string;
  source: string;
}

export interface RankStep {
  window: number;
  redundancy: number;
  base: number;
}

export interface Card {
  appid: number;
  name: string;
  name_en: string;
  year: number | null;
  developer: string | null;
  store_url: string;
  header: string;
  relevance: number;
  diff?: Diff;
  colike?: Colike;
  like: Like;
  rating: Rating;
  price: PriceFacts;
  library?: string;
  library_hint?: string;
  time_to_beat?: string;
  /** Set when a requested mechanic is only a secondary tag of this game (filled in after the strict matches). */
  mechanics_note?: string;
  same_series_folded?: string[];
  lineage?: string[];
  /** Anchor → … → this game, e.g. "Hades —开发→ Supergiant Games —开发→ Transistor". */
  lineage_path?: LineagePath;
  setup?: Setup | null;
  rank_step?: RankStep;
  unknown?: string[];
  reason?: string;
  reason_source?: "template" | "llm";
}

export interface Backup {
  appid: number;
  name: string;
  relevance: number;
  price: PriceFacts;
  pct_positive: number | null;
  label?: string;
  owned?: string;
  same_series?: number;
  /** Names behind same_series; may be shorter than the count. */
  series_names?: string[];
  setup?: SetupKind;
}

/** Which condition "skip this condition" drops (POST /api/relax). */
export type RelaxKey = "budget" | "discount" | "mechanics" | "solo" | "setup" | "unknown";

export type MissCause =
  | "budget"
  | "players"
  | "mode"
  | "region"
  | "discount"
  | "mechanics"
  | "solo"
  | "players_unknown"
  | "unknown"
  | "other";

/** A near miss: a game that ranked high but broke one hard condition or lacks a fact. */
export interface NearMiss {
  appid: number;
  name: string;
  why: string[];
  price: PriceFacts;
  pct_positive: number | null;
  /** value: the player limit for "players", the setup kind for "mode", the price for "budget". */
  miss: { cause: MissCause; value: number | string | null };
  relax: RelaxKey | null;
}

/** A game that misses a fact (e.g. no player count anywhere). */
export type UnknownItem = NearMiss;

/** A game that would have ranked high but broke a hard condition. */
export interface FailedItem extends NearMiss {
  relevance: number;
}

export interface CardFeedback {
  /** true: kept for the member's Steam account; false: only for this session (guest). */
  saved: boolean;
  message: string;
}

export interface RuleRow {
  rule: string;
  pass: number;
  fail: number;
  unknown: number;
  relaxable: boolean;
}

export interface RelaxChange {
  key: string;
  text: string;
  value?: number | null;
}

export interface RelaxOption {
  changes: RelaxChange[];
  count: number;
  cost?: number;
  examples: string[];
}

export interface UnderstoodMember {
  name: string;
  region: Region;
  seeds: string[];
  played_elsewhere: string[];
  avoid: string[];
  language: string | null;
  platform: Platform | null;
  library: { public: boolean; owned: number; played: number; playtime_hidden: boolean } | null;
}

export interface Understood {
  seeds: string[];
  preference_text: string | null;
  feel_want: string[];
  feel_avoid: string[];
  mechanics: string[];
  budget: { amount: number | null; scope: BudgetScope } | null;
  price_intent: PriceIntent;
  only_discounted: boolean;
  library_policy: LibraryPolicy;
  party_size: number;
  interaction: Interaction;
  setups: SetupKind[];
  unresolved: string[];
  ambiguous: Record<string, string[]>;
  members: UnderstoodMember[];
}

export interface RecommendResult {
  session_id: string;
  understood: Understood;
  picks: Card[];
  backups: Backup[];
  unknown: UnknownItem[];
  rules: RuleRow[];
  relax: RelaxOption[];
  timings: Record<string, unknown>;
  notes: string[];
  need_input: string | null;
  libraries: Record<string, LibrarySummary>;
  failed?: FailedItem[];
  /** Only on /api/card answers to liked / disliked. */
  feedback?: CardFeedback;
  /** Only on /api/rerun: earlier picks now left out because the imported library shows playtime. */
  played_out?: number[];
}

export interface ReasonEntry {
  reason: string;
  source: string;
}

export type ReasonsResponse = Record<string, ReasonEntry>;

export interface ReportBody {
  session_id?: string;
  appid: number;
  field: ReportField;
  text: string;
}

// ---------- transport ----------

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function detailText(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg, type}]
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    return T().errBadRequest(msgs.join("; "));
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const opts: RequestInit = { ...rest, headers: { Accept: "application/json", ...(rest.headers ?? {}) } };
  if (json !== undefined) {
    opts.method = opts.method ?? "POST";
    opts.body = JSON.stringify(json);
    opts.headers = { ...opts.headers, "Content-Type": "application/json" };
  }
  let res: Response;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, T().errOffline);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw new ApiError(res.status, detailText(body) ?? T().errHttp(res.status));
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  search: (q: string, limit = 8, signal?: AbortSignal) =>
    request<GameHit[]>(`/api/search?${new URLSearchParams({ q, limit: String(limit), lang: apiLang })}`, { signal }),

  tags: () => request<TagsResponse>(`/api/tags?lang=${apiLang}`),

  library: (sessionId: string | null, member: number, profile: string) =>
    request<LibraryResponse>("/api/library", { json: { session_id: sessionId, member, profile, lang: apiLang } }),

  /** Full-page navigation target for Steam OpenID login (path B). */
  steamLoginUrl: (sessionId: string | null, member: number) => {
    const p = new URLSearchParams({ member: String(member) });
    if (sessionId) p.set("session_id", sessionId);
    return `/api/auth/steam/login?${p}`;
  },

  recommend: (body: RecommendBody, onStep: OnStep) =>
    streamed<RecommendResult>("/api/recommend", { ...body, lang: apiLang }, onStep),

  followup: (sessionId: string, text: string, onStep: OnStep) =>
    streamed<RecommendResult>("/api/followup", { session_id: sessionId, text, lang: apiLang }, onStep),

  card: (sessionId: string, appid: number, action: CardActionKind, member = 0) =>
    request<RecommendResult>("/api/card", { json: { session_id: sessionId, appid, action, member, lang: apiLang } }),

  /** "Skip this condition" on a near miss: the last request again without it; no LLM call. */
  relax: (sessionId: string, key: RelaxKey, onStep: OnStep) =>
    streamed<RecommendResult>("/api/relax", { session_id: sessionId, key, lang: apiLang }, onStep),

  /** The last request again with the libraries imported since; no understanding step. */
  rerun: (sessionId: string, onStep: OnStep) =>
    streamed<RecommendResult>("/api/rerun", { session_id: sessionId, lang: apiLang }, onStep),

  reasons: (sessionId: string) =>
    request<ReasonsResponse>("/api/reasons", { json: { session_id: sessionId, lang: apiLang } }),

  /** "事实有误？": stored for the next data refresh, does not change the current result. */
  report: (body: ReportBody) => request<{ ok: boolean }>("/api/report", { json: body }),
};

/** The streamed pipeline steps (?stream=1, api.py `streamed`), in the order the backend runs them. */
export type StepId = "understand" | "pick" | "rerank" | "prices";
export type StepEvent =
  | { type: "plan"; steps: StepId[] }
  | { type: "step"; step: StepId; state: "start" | "done" | "skip" };
export type OnStep = (ev: StepEvent) => void;

/** POST with ?stream=1: one JSON object per line; step lines go to `onStep`, the last line is the result or an error. */
async function streamed<T>(path: string, json: unknown, onStep: OnStep): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${path}?stream=1`, {
      method: "POST",
      headers: { Accept: "application/x-ndjson", "Content-Type": "application/json" },
      body: JSON.stringify(json),
    });
  } catch {
    throw new ApiError(0, T().errOffline);
  }
  if (!res.ok || !res.body) {
    // request validation (422) fails before the stream starts and answers as plain JSON
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, detailText(body) ?? T().errHttp(res.status));
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch {
      throw new ApiError(0, T().errOffline);
    }
    buf += dec.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line) as StepEvent | { type: "result"; data: T } | { type: "error"; status: number; detail: unknown };
      if (ev.type === "result") return ev.data;
      if (ev.type === "error") throw new ApiError(ev.status, detailText(ev) ?? T().errHttp(ev.status));
      onStep(ev);
    }
    if (chunk.done) throw new ApiError(0, T().errOffline);
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return T().errGeneric;
}
