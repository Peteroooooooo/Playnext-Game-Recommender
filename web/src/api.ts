// Typed client for the Playnext FastAPI backend (src/playnext/api.py).
// Shapes follow web_fixtures/api_samples.json; optional fields are the ones the backend only sets sometimes.

export type Region = "CN" | "US";
export type Platform = "windows" | "mac" | "linux" | "deck";
export type AvoidContent = "gore" | "sexual";
export type SetupKind = "online" | "local" | "remote" | "hybrid";
export type Interaction = "coop" | "versus" | "any";
export type PriceIntent = "none" | "cheap" | "near_record_low";
export type LibraryPolicy = "none" | "prefer_owned" | "exclude_owned";
export type BudgetScope = "per_person" | "team_total";
export type CardActionKind = "played" | "owned" | "not_interested";

// ---------- reference data ----------

export interface Health {
  ok: boolean;
  games: number;
  llm: boolean;
  encoder: boolean;
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
  mode_text: string;
  friends_pass?: string;
  note: string;
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
  same_series_folded?: string[];
  lineage?: string[];
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
  setup?: SetupKind;
}

export interface UnknownItem {
  appid: number;
  name: string;
  why: string[];
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
}

export interface ReasonEntry {
  reason: string;
  source: string;
}

export type ReasonsResponse = Record<string, ReasonEntry>;

// ---------- transport ----------

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** Backend `detail` values that are not in Chinese, mapped to text a user can act on. */
const DETAIL_ZH: Record<string, string> = {
  "session expired": "会话已过期，请重新提交一次需求",
  "no earlier request in this session": "还没有可以修改的推荐，请先提交一次需求",
  "no earlier request": "还没有推荐结果，请先提交一次需求",
  "no result": "还没有推荐结果",
  "text or form required": "请先输入需求或填写问卷",
};

function detailText(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return DETAIL_ZH[detail] ?? detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors: [{loc, msg, type}]
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    return `请求格式有误${msgs.length ? `：${msgs.join("；")}` : ""}`;
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
    throw new ApiError(0, "连不上推荐服务，请确认后端已启动");
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw new ApiError(res.status, detailText(body) ?? `请求失败（HTTP ${res.status}）`);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),

  search: (q: string, limit = 8, signal?: AbortSignal) =>
    request<GameHit[]>(`/api/search?${new URLSearchParams({ q, limit: String(limit) })}`, { signal }),

  tags: () => request<TagsResponse>("/api/tags"),

  library: (sessionId: string | null, member: number, profile: string) =>
    request<LibraryResponse>("/api/library", { json: { session_id: sessionId, member, profile } }),

  /** Full-page navigation target for Steam OpenID login (path B). */
  steamLoginUrl: (sessionId: string | null, member: number) => {
    const p = new URLSearchParams({ member: String(member) });
    if (sessionId) p.set("session_id", sessionId);
    return `/api/auth/steam/login?${p}`;
  },

  recommend: (body: RecommendBody) => request<RecommendResult>("/api/recommend", { json: body }),

  followup: (sessionId: string, text: string) =>
    request<RecommendResult>("/api/followup", { json: { session_id: sessionId, text } }),

  card: (sessionId: string, appid: number, action: CardActionKind, member = 0) =>
    request<RecommendResult>("/api/card", { json: { session_id: sessionId, appid, action, member } }),

  reasons: (sessionId: string) => request<ReasonsResponse>("/api/reasons", { json: { session_id: sessionId } }),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "出了点问题，请稍后再试";
}
