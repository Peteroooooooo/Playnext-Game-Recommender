// UI-side state and how it maps to the API form.
import type { AvoidContent, LibraryPolicy, LibrarySummary, MemberForm, Platform, PriceIntent, RecommendForm, Region, Tag } from "./api";

/** Steam tag id of 恐怖 (Horror); used by the "不要恐怖" quick switch. */
export const HORROR_TAG = 1667;

export interface GameRef {
  appid: number;
  name: string;
  year: number | null;
}

/** What the form path sends. The page itself only fills `seeds` (game search when free text is unavailable). */
export interface Prefs {
  seeds: GameRef[];
  feelWant: Tag[];
  feelAvoid: Tag[];
  avoidTags: Tag[];
  noHorror: boolean;
  avoidContent: AvoidContent[];
  chinese: boolean;
  singlePlayer?: boolean;
  platform: Platform | null;
  budget: string;
  priceIntent: PriceIntent;
  libraryPolicy: LibraryPolicy;
}

/** A connected Steam library. summary is null right after Steam login (the backend has it, we do not yet). */
export interface LibState {
  summary: LibrarySummary | null;
}

export type Libs = Record<number, LibState>;

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

const uniq = (xs: number[]) => Array.from(new Set(xs));

export function parseBudget(s: string): number | null {
  const v = Number(s.trim());
  return s.trim() !== "" && Number.isFinite(v) && v >= 0 ? v : null;
}

/**
 * With free text the backend takes the request from the text and uses this form only for the store region and
 * the libraries (api.merge_form); without text it is the whole request.
 */
export function singleForm(region: Region, p: Prefs): RecommendForm {
  const me: MemberForm = {
    name: "我",
    region,
    seeds: [],
    feel_want: [],
    feel_avoid: [],
    avoid_tags: uniq([...p.avoidTags.map((t) => t.tagid), ...(p.noHorror ? [HORROR_TAG] : [])]),
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

export const CURRENCY: Record<Region, string> = { CN: "¥", US: "$" };

/** ¥66 / ¥17.5 / $9.99 / $2.50: dollar amounts with cents keep two decimals. */
export function money(v: number, region: Region): string {
  const n = Number.isInteger(v) ? String(v) : region === "US" ? v.toFixed(2) : String(Math.round(v * 100) / 100);
  return `${CURRENCY[region]}${n}`;
}
