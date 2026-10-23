// Fixed data behind the "?" guide and the home screen. Text lives in i18n.ts (examples, exGroups), aligned by index.

/** Group index (i18n exGroups) and the game each example sentence finds; the home screen cycles through them. */
export const EXAMPLES: { group: number; appid: number }[] = [
  // each game was among the 5 picks when the Chinese sentence ran through the recommender (CN store, 2026-10-23)
  { group: 0, appid: 1139980 },
  { group: 0, appid: 367580 },
  { group: 0, appid: 1082430 },
  { group: 0, appid: 504230 },
  { group: 1, appid: 1211020 },
  { group: 1, appid: 1426210 },
  { group: 1, appid: 552500 },
  { group: 1, appid: 892970 },
  { group: 2, appid: 1296830 },
  { group: 2, appid: 292030 },
  { group: 2, appid: 211820 },
  { group: 2, appid: 1942280 },
  { group: 3, appid: 548430 },
  { group: 3, appid: 322330 },
  { group: 3, appid: 1135690 },
  { group: 3, appid: 1243830 },
];

/** Steam popover: a played game, a much-played one, and what that leads to. */
export const STEAM_DEMO = { played: 413150, hours: 367520, rec: 504230 };

/** Guide, Steam card: the same shelf without and with a library; `after` replaces the poster when imported. */
export const BOOST_DEMO: { appid: number; after?: number; before?: "played"; label?: "like" | "taste" }[] = [
  { appid: 413150, before: "played", after: 433340, label: "like" },
  { appid: 1055540 },
  { appid: 972660, after: 1145360, label: "taste" },
  { appid: 1135690 },
];

/** Guide, store card: CN / US prices from data/processed/prices.parquet (2026-10 snapshot); null = not sold in CN. */
export const STORE_DEMO: { appid: number; cn: string | null; us: string }[] = [
  { appid: 367520, cn: "¥58", us: "$14.99" },
  { appid: 387290, cn: null, us: "$19.99" },
  { appid: 504230, cn: "¥17", us: "$4.99" },
  { appid: 1145360, cn: "¥92", us: "$24.99" },
];

/** "a, b" + "c" → "a, b, c"; empty parts dropped. Used by the "+" chips in the guide. */
export function addPart(text: string, part: string, sep: string): string {
  const cur = text.trim();
  const next = part.trim();
  if (!next || splitParts(cur, sep).includes(next)) return cur;
  return cur ? `${cur}${sep}${next}` : next;
}

export function removePart(text: string, part: string, sep: string): string {
  return splitParts(text, sep)
    .filter((x) => x !== part)
    .join(sep);
}

export function splitParts(text: string, sep: string): string[] {
  return text
    .split(sep.trim() || sep)
    .map((x) => x.trim())
    .filter(Boolean);
}
