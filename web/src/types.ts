// UI-side draft state (what the user is filling in), and how it maps to the API form.
import type {
  AvoidContent,
  BudgetScope,
  FeedbackKind,
  Interaction,
  LibraryPolicy,
  LibrarySummary,
  MemberForm,
  Platform,
  PriceIntent,
  RecommendForm,
  Region,
  ReportField,
  SetupKind,
  Tag,
} from "./api";

export type Mode = "single" | "group";

/** Steam tag id of 恐怖 (Horror); used by the "不要恐怖" quick switch. */
export const HORROR_TAG = 1667;
export const MAX_MEMBERS = 8;
export const MAX_SEEDS = 3;

export interface GameRef {
  appid: number;
  name: string;
  year: number | null;
}

export interface Prefs {
  seeds: GameRef[];
  feelWant: Tag[];
  feelAvoid: Tag[];
  avoidTags: Tag[];
  noHorror: boolean;
  avoidContent: AvoidContent[];
  chinese: boolean;
  /** Missing in drafts saved before the field existed. */
  singlePlayer?: boolean;
  platform: Platform | null;
  budget: string;
  priceIntent: PriceIntent;
  libraryPolicy: LibraryPolicy;
}

export interface PartyMember {
  key: string;
  name: string;
  region: Region;
  seeds: GameRef[];
  avoidTags: Tag[];
  noHorror: boolean;
  avoidContent: AvoidContent[];
  platform: Platform | null;
  ownedExtra: GameRef[];
  /** Machine / screen number, only used when place === "hybrid". */
  site: number;
  /** "想玩什么" free text; missing in drafts saved before the field existed. */
  preferenceText?: string;
}

export const MAX_PREFERENCE_TEXT = 200;

/** "auto" lets the backend pick the best setup. */
export type Place = "auto" | SetupKind;

export interface Party {
  members: PartyMember[];
  place: Place;
  interaction: Interaction;
  budget: string;
  budgetScope: BudgetScope;
  priceIntent: PriceIntent;
  seeds: GameRef[];
  feelWant: Tag[];
  feelAvoid: Tag[];
  chinese: boolean;
  libraryPolicy: LibraryPolicy;
}

/** A connected Steam library. summary is null right after Steam login (the backend has it, we do not yet). */
export interface LibState {
  summary: LibrarySummary | null;
}

export type Libs = Record<number, LibState>;

/** The answer to the last 喜欢 / 不喜欢 click, shown on that card (or above the cards if it dropped out). */
export interface CardNote {
  appid: number;
  name: string;
  action: FeedbackKind;
  member: number;
  saved: boolean;
  text: string;
}

export function emptyPrefs(): Prefs {
  return {
    seeds: [],
    feelWant: [],
    feelAvoid: [],
    avoidTags: [],
    noHorror: false,
    avoidContent: [],
    chinese: false,
    platform: null,
    budget: "",
    priceIntent: "none",
    libraryPolicy: "none",
  };
}

let keySeq = 0;
export function newMember(name: string, region: Region, site = 1): PartyMember {
  keySeq += 1;
  return {
    key: `m${Date.now().toString(36)}${keySeq}`,
    name,
    region,
    seeds: [],
    avoidTags: [],
    noHorror: false,
    avoidContent: [],
    platform: null,
    ownedExtra: [],
    site,
    preferenceText: "",
  };
}

export function defaultParty(region: Region): Party {
  return {
    members: [newMember("我", region, 1), newMember("朋友 2", region, 2)],
    place: "auto",
    interaction: "coop",
    budget: "",
    budgetScope: "per_person",
    priceIntent: "none",
    seeds: [],
    feelWant: [],
    feelAvoid: [],
    chinese: false,
    libraryPolicy: "none",
  };
}

const uniq = (xs: number[]) => Array.from(new Set(xs));

export function parseBudget(s: string): number | null {
  const v = Number(s.trim());
  return s.trim() !== "" && Number.isFinite(v) && v >= 0 ? v : null;
}

function avoidIds(tags: Tag[], noHorror: boolean): number[] {
  return uniq([...tags.map((t) => t.tagid), ...(noHorror ? [HORROR_TAG] : [])]);
}

export function singleForm(region: Region, p: Prefs): RecommendForm {
  const me: MemberForm = {
    name: "我",
    region,
    seeds: [],
    feel_want: [],
    feel_avoid: [],
    avoid_tags: avoidIds(p.avoidTags, p.noHorror),
    avoid_content: p.avoidContent,
    language: p.chinese ? "schinese" : null,
    platform: p.platform,
    owned_extra: [],
    site: null,
  };
  return {
    members: [me],
    seeds: p.seeds.map((g) => g.appid),
    feel_want: p.feelWant.map((t) => t.tagid),
    feel_avoid: p.feelAvoid.map((t) => t.tagid),
    budget: parseBudget(p.budget),
    budget_scope: "per_person",
    price_intent: p.priceIntent,
    interaction: "any",
    setup: null,
    library_policy: p.libraryPolicy,
    single_player: !!p.singlePlayer,
  };
}

export function groupForm(party: Party): RecommendForm {
  const members: MemberForm[] = party.members.map((m, i) => {
    const pref = (m.preferenceText ?? "").trim().slice(0, MAX_PREFERENCE_TEXT);
    return {
      name: m.name.trim() || (i === 0 ? "我" : `朋友 ${i + 1}`),
      region: m.region,
      seeds: m.seeds.map((g) => g.appid),
      feel_want: [],
      feel_avoid: [],
      avoid_tags: avoidIds(m.avoidTags, m.noHorror),
      avoid_content: m.avoidContent,
      language: party.chinese ? "schinese" : null,
      platform: m.platform,
      owned_extra: m.ownedExtra.map((g) => g.appid),
      site: party.place === "local" ? 1 : party.place === "hybrid" ? m.site : null,
      ...(pref ? { preference_text: pref } : {}),
    };
  });
  return {
    members,
    seeds: party.seeds.map((g) => g.appid),
    feel_want: party.feelWant.map((t) => t.tagid),
    feel_avoid: party.feelAvoid.map((t) => t.tagid),
    budget: parseBudget(party.budget),
    budget_scope: party.budgetScope,
    price_intent: party.priceIntent,
    interaction: party.interaction,
    setup: party.place === "auto" ? null : party.place,
    library_policy: party.libraryPolicy,
  };
}

export function hasSingleInput(p: Prefs): boolean {
  return p.seeds.length > 0 || p.feelWant.length > 0;
}

export const CURRENCY: Record<Region, string> = { CN: "¥", US: "$" };

export const SETUP_ZH: Record<SetupKind, string> = {
  online: "在线组队",
  local: "本地同屏",
  remote: "远程同乐",
  hybrid: "混合开局",
};

export const PLATFORM_ZH: Record<Platform, string> = {
  windows: "Windows",
  mac: "macOS",
  linux: "Linux",
  deck: "Steam Deck",
};

export const PRICE_INTENT_ZH: Record<PriceIntent, string> = {
  none: "价格不限偏好",
  cheap: "越便宜越好",
  near_record_low: "最好在打折（接近史低）",
};

export const LIBRARY_POLICY_ZH: Record<LibraryPolicy, string> = {
  none: "库里有没有都行",
  prefer_owned: "优先库里已有的",
  exclude_owned: "排除库里已有的",
};

export const INTERACTION_ZH: Record<Interaction, string> = {
  coop: "一起合作",
  versus: "互相对战",
  any: "合作对战都行",
};

export const REPORT_FIELD_ZH: Record<ReportField, string> = {
  players: "人数上限",
  modes: "联机模式",
  price: "价格",
  tags: "标签与玩法",
  other: "其他",
};

export function money(v: number, region: Region): string {
  const n = Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  return `${CURRENCY[region]}${n}`;
}
