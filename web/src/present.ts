// How result data is turned into the short text the page shows. Pure functions, covered by present.test.ts.
import type { Card, NearMiss, PriceFacts, StepEvent, StepId, Understood } from "./api";
import type { Dict } from "./i18n";
import { money } from "./types";

/** Steam CDN art: library_600x900.jpg = poster, library_hero.jpg = banner / backdrop, header.jpg = fallback. */
export const art = (appid: number, file: string) => `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/${file}`;

/** Fisher–Yates shuffle into a new array; `rand` is injectable for tests. */
export function shuffled<T>(xs: readonly T[], rand: () => number = Math.random): T[] {
  const out = xs.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** A new random round of the home backdrops that does not start with the one just shown. */
export function nextRound(list: readonly number[], last: number | null, rand: () => number = Math.random): number[] {
  const r = shuffled(list, rand);
  if (r.length > 1 && r[0] === last) [r[0], r[r.length - 1]] = [r[r.length - 1], r[0]];
  return r;
}

/** Chinese display names come as "中文名 / English name"; the page shows the first part. */
export const shortName = (name: string) => name.split(" / ")[0];

export function englishName(c: Pick<Card, "name" | "name_en">): string | null {
  return c.name_en && c.name_en !== shortName(c.name) ? c.name_en : null;
}

export function priceLabel(p: PriceFacts, t: Dict): string | null {
  if (p.free) return t.free;
  return p.final != null ? money(p.final, p.region) : null;
}

/** "通关约 12 小时（IGDB）" or "About 12 hours to beat (IGDB)" → "12 小时" / "12 h". */
export function shortTime(s: string, t: Dict): string {
  const n = /\d+(?:\.\d+)?/.exec(s)?.[0];
  return n ? t.hours(n) : s;
}

/** "我理解成" chips: what the backend took from the sentence, in the user's words where possible. */
export function understoodChips(u: Understood, t: Dict): string[] {
  const region = u.members[0]?.region ?? "CN";
  const group = u.party_size > 1;
  const out = [group ? t.nP(u.party_size) : t.oneP];
  if (group) {
    u.setups.forEach((k) => out.push(t.setupShort[k]));
    if (u.interaction === "coop") out.push(t.coop);
    if (u.interaction === "versus") out.push(t.versus);
  }
  if (u.budget && u.budget.amount != null) {
    const scope = group ? (u.budget.scope === "team_total" ? "team" : "per") : "";
    out.push(t.budgetChip(scope, money(u.budget.amount, region)));
  }
  if (u.price_intent === "cheap") out.push(t.cheap);
  if (u.price_intent === "near_record_low" || u.only_discounted) out.push(t.onSale);
  if (u.library_policy === "exclude_owned") out.push(t.excludeOwned);
  if (u.library_policy === "prefer_owned") out.push(t.preferOwned);
  if (u.seeds.length) out.push(t.like_(u.seeds));
  u.feel_want.forEach((x) => out.push(x));
  u.mechanics.forEach((x) => out.push(x));
  if (u.feel_avoid.length) out.push(t.avoid(u.feel_avoid));
  return Array.from(new Set(out));
}

/** One line per thing the user should know about how the sentence was read. */
export function understoodNotes(u: Understood, t: Dict): string[] {
  const out: string[] = [];
  if (u.unresolved.length) out.push(t.notFound(u.unresolved));
  Object.entries(u.ambiguous)
    .filter(([, v]) => v.length > 1)
    .forEach(([name, cands]) => out.push(t.readAs(name, cands[0])));
  return out;
}

export type Badge = { text: string; tone: "good" | "warn" };

export function cardBadges(c: Card, t: Dict): Badge[] {
  const out: Badge[] = [];
  if (c.price.discount_pct) out.push({ text: `-${c.price.discount_pct}%`, tone: "good" });
  else if (c.price.near_low) out.push({ text: t.nearLow, tone: "good" });
  if (c.unknown?.length) out.push({ text: t.pending, tone: "warn" });
  else if (c.rating.below_floor) out.push({ text: t.mixed, tone: "warn" });
  return out;
}

/** The orange badge on a near miss: what keeps it out of the picks. */
export function missLabel(m: NearMiss["miss"], t: Dict): string {
  switch (m.cause) {
    case "players":
      return t.miss.players(typeof m.value === "number" ? m.value : null);
    case "mode": {
      const k = (typeof m.value === "string" && m.value in t.miss.mode ? m.value : "any") as keyof Dict["miss"]["mode"];
      return t.miss.mode[k];
    }
    case "budget":
    case "region":
    case "discount":
    case "mechanics":
    case "solo":
    case "players_unknown":
    case "unknown":
      return t.miss[m.cause];
    default:
      return t.miss.other;
  }
}

/** Price line under a poster; in a group the price is what each person pays. */
export function metaText(c: Card, group: boolean, t: Dict): string {
  const price = priceLabel(c.price, t);
  if (group && c.setup) {
    const bits = [price && (c.price.free ? price : t.perPerson(price)), t.setupMax(c.setup.kind_zh, c.setup.max_players ?? "?")];
    return bits.filter(Boolean).join(" · ");
  }
  return price ?? "";
}

/** Characters of a reason shown `ms` after it arrived, revealed at `cps` characters per second. */
export function revealed(text: string, ms: number, cps: number): number {
  return Math.max(0, Math.min(text.length, Math.floor((ms / 1000) * cps)));
}

/** Reveal speed: Chinese characters per second, about the same reading pace in English letters. */
export const revealCps = (text: string) => (/[一-鿿]/.test(text) ? 45 : 140);

/** One line of the task list shown while a request runs; the backend streams each step as it reaches it. */
export interface Task {
  id: StepId;
  state: "pending" | "active" | "done";
}

export const STEP_LABEL: Record<StepId, keyof Pick<Dict, "stepUnderstand" | "stepPick" | "stepRerank" | "stepPrices">> = {
  understand: "stepUnderstand",
  pick: "stepPick",
  rerank: "stepRerank",
  prices: "stepPrices",
};

/** The task list after one stream event: the plan lists every step, a skipped step leaves the list. */
export function applyStep(tasks: Task[], ev: StepEvent): Task[] {
  if (ev.type === "plan") return ev.steps.map((id) => ({ id, state: "pending" }));
  if (ev.state === "skip") return tasks.filter((k) => k.id !== ev.step);
  const state = ev.state === "start" ? "active" : "done";
  return tasks.map((k) => (k.id === ev.step ? { ...k, state } : k));
}
