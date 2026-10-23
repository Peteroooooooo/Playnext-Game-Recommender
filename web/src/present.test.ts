import { describe, expect, it } from "vitest";
import type { Card, Understood } from "./api";
import { DICTS } from "./i18n";
import {
  cardBadges,
  englishName,
  metaText,
  missLabel,
  nextRound,
  shuffled,
  progressAt,
  revealCps,
  revealed,
  shortName,
  shortTime,
  TEXT_STEPS,
  understoodChips,
  understoodNotes,
} from "./present";

const zh = DICTS.zh;
const en = DICTS.en;

const understood = (o: Partial<Understood> = {}): Understood => ({
  seeds: [],
  preference_text: null,
  feel_want: [],
  feel_avoid: [],
  mechanics: [],
  budget: null,
  price_intent: "none",
  only_discounted: false,
  library_policy: "none",
  party_size: 1,
  interaction: "any",
  setups: [],
  unresolved: [],
  ambiguous: {},
  members: [{ name: "我", region: "CN", seeds: [], played_elsewhere: [], avoid: [], language: null, platform: null, library: null }],
  ...o,
});

const card = (o: Partial<Card> = {}): Card => ({
  appid: 1,
  name: "晃晃人生 / Wobbly Life",
  name_en: "Wobbly Life",
  year: 2021,
  developer: "RubberBandGames",
  store_url: "",
  header: "",
  relevance: 1,
  like: {},
  rating: { pct_positive: 92, reviews: 30000, smoothed: 0.9, text: "", below_floor: false },
  price: { region: "CN", text: "", final: 66, low: 31, discount_pct: 0 },
  ...o,
});

describe("names", () => {
  it("shows the Chinese part and keeps a distinct English name", () => {
    expect(shortName("晃晃人生 / Wobbly Life")).toBe("晃晃人生");
    expect(englishName(card())).toBe("Wobbly Life");
    expect(englishName(card({ name: "Overcooked! 2", name_en: "Overcooked! 2" }))).toBeNull();
  });
});

describe("understood chips", () => {
  const group = understood({
    party_size: 4,
    setups: ["online"],
    interaction: "coop",
    budget: { amount: 100, scope: "per_person" },
    feel_want: ["搞笑", "合作"],
  });

  it("reads a group request in the user's words", () => {
    expect(understoodChips(group, zh)).toEqual(["4 个人", "各自在家", "合作", "每人 ¥100 以内", "搞笑"]);
    expect(understoodChips({ ...group, feel_want: ["Funny"] }, en)).toEqual(["4 players", "each at home", "co-op", "under ¥100 each", "Funny"]);
  });

  it("does not show group-only chips for one player", () => {
    const u = understood({ interaction: "coop", budget: { amount: 20, scope: "per_person" }, seeds: ["Hades", "Celeste"] });
    expect(understoodChips(u, zh)).toEqual(["一个人", "¥20 以内", "像《Hades》《Celeste》"]);
    expect(understoodChips(u, en)).toEqual(["1 player", "under ¥20", "like Hades, Celeste"]);
  });

  it("names unresolved and ambiguous games", () => {
    const u = understood({ unresolved: ["某游戏"], ambiguous: { 文明: ["Civilization VI", "Civilization V"], x: ["only"] } });
    expect(understoodNotes(u, zh)).toEqual(["没找到：某游戏。换个叫法试试。", "“文明”按《Civilization VI》理解。"]);
  });
});

describe("card text", () => {
  it("prices per person in a group", () => {
    const setup = { kind: "online", kind_zh: "在线组队", players: 4, max_players: 4 } as Card["setup"];
    expect(metaText(card({ setup }), true, zh)).toBe("每人 ¥66 · 在线组队 4 人");
    expect(metaText(card({ setup: { ...setup!, kind_zh: "Online" } }), true, en)).toBe("¥66 each · Online 4 players");
    expect(metaText(card(), false, zh)).toBe("¥66");
    expect(metaText(card({ price: { region: "US", text: "", free: true } }), false, en)).toBe("Free");
    expect(metaText(card({ price: { region: "US", text: "", final: 2.5 } }), false, en)).toBe("$2.50");
    expect(metaText(card({ price: { region: "CN", text: "", final: 17.5 } }), false, zh)).toBe("¥17.5");
  });

  it("puts a discount before near-low and a missing fact before low ratings", () => {
    expect(cardBadges(card({ price: { region: "CN", text: "", discount_pct: 40, near_low: true } }), zh)).toEqual([
      { text: "-40%", tone: "good" },
    ]);
    const c = card({ unknown: ["人数"], rating: { ...card().rating, below_floor: true } });
    expect(cardBadges(c, zh)).toEqual([{ text: "待确认", tone: "warn" }]);
  });

  it("formats discount and play time in both languages", () => {
    expect(zh.discount(30)).toBe("7 折");
    expect(zh.discount(75)).toBe("2.5 折");
    expect(en.discount(30)).toBe("30% off");
    expect(shortTime("通关约 12 小时（IGDB）", zh)).toBe("12 小时");
    expect(shortTime("About 12 hours to beat (IGDB)", en)).toBe("12 h");
  });
});

describe("near misses", () => {
  it("names what keeps a game out", () => {
    expect(missLabel({ cause: "players", value: 3 }, zh)).toBe("最多 3 人");
    expect(missLabel({ cause: "mode", value: "local" }, en)).toBe("No local mode");
    expect(missLabel({ cause: "mode", value: null }, zh)).toBe("没有这种玩法");
    expect(missLabel({ cause: "budget", value: 98 }, zh)).toBe("超预算");
    expect(missLabel({ cause: "players_unknown", value: null }, en)).toBe("Player count unconfirmed");
  });
});

describe("home backdrop", () => {
  it("plays every game once per round in a new order, never the same one twice in a row", () => {
    const list = [1, 2, 3, 4, 5];
    let seed = 7;
    const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    let last: number | null = null;
    for (let k = 0; k < 50; k++) {
      const r = nextRound(list, last, rand);
      expect([...r].sort()).toEqual(list);
      expect(r[0]).not.toBe(last);
      last = r[r.length - 1];
    }
    expect(shuffled(list, rand)).not.toBe(list);
  });
});

describe("timing", () => {
  it("reveals at a steady speed and stops at the end", () => {
    expect(revealed("一二三四五", 0, 45)).toBe(0);
    expect(revealed("一二三四五", 50, 45)).toBe(2);
    expect(revealed("一二三四五", 10_000, 45)).toBe(5);
    expect(revealCps("中文理由")).toBeLessThan(revealCps("An English reason"));
  });

  it("walks through the steps and never fills the bar on its own", () => {
    expect(progressAt(TEXT_STEPS, 0).label).toBe("stepUnderstand");
    expect(progressAt(TEXT_STEPS, 5).label).toBe("stepPick");
    expect(progressAt(TEXT_STEPS, 8).label).toBe("stepRerank");
    const late = progressAt(TEXT_STEPS, 120);
    expect(late.label).toBe("stepPrices");
    expect(late.frac).toBeLessThan(1);
    expect(progressAt(TEXT_STEPS, 14).frac).toBeGreaterThan(progressAt(TEXT_STEPS, 7).frac);
  });

  it("has every UI text in both languages", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(zh).sort());
  });
});
