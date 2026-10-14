import type { Understood } from "../api";
import { INTERACTION_ZH, LIBRARY_POLICY_ZH, money, PLATFORM_ZH, PRICE_INTENT_ZH, SETUP_ZH } from "../types";
import { Avatar } from "./Icons";

/** "我理解的条件": what the backend understood, as read-only chips. */
export function UnderstoodChips({ u }: { u: Understood }) {
  const region = u.members[0]?.region ?? "CN";
  const group = u.party_size > 1;
  const chips: { text: string; kind?: "fixed" | "avoid" | "warn" }[] = [];

  u.seeds.forEach((s) => chips.push({ text: `参考：${s}`, kind: "fixed" }));
  if (u.preference_text) chips.push({ text: `想要：${u.preference_text}`, kind: "fixed" });
  u.mechanics.forEach((s) => chips.push({ text: `核心玩法：${s}`, kind: "fixed" }));
  u.feel_want.forEach((s) => chips.push({ text: `感觉：${s}` }));
  u.feel_avoid.forEach((s) => chips.push({ text: `尽量不要：${s}`, kind: "avoid" }));
  if (u.budget && u.budget.amount != null) {
    const scope = group ? (u.budget.scope === "team_total" ? "全队合计 " : "每人 ") : "";
    chips.push({ text: `${scope}${money(u.budget.amount, region)} 以内` });
  }
  if (u.price_intent !== "none") chips.push({ text: PRICE_INTENT_ZH[u.price_intent] });
  if (u.only_discounted) chips.push({ text: "只看正在打折的" });
  if (u.library_policy !== "none") chips.push({ text: LIBRARY_POLICY_ZH[u.library_policy] });
  if (group) {
    chips.push({ text: `${u.party_size} 人`, kind: "fixed" });
    if (u.interaction !== "any") chips.push({ text: INTERACTION_ZH[u.interaction], kind: "fixed" });
    u.setups.forEach((s) => chips.push({ text: SETUP_ZH[s], kind: "fixed" }));
  }

  const ambiguous = Object.entries(u.ambiguous).filter(([, v]) => v.length > 1);

  return (
    <div className="conds">
      <div className="label-row">
        <span className="eyebrow">我理解的条件</span>
        <span className="hint">不对的话，在下面“继续改条件”里说一声</span>
      </div>
      <ul className="chips" aria-label="已理解的条件">
        {chips.map((c, i) => (
          <li key={i} className={`chip static${c.kind === "fixed" ? " fixed" : c.kind === "avoid" ? " chip-avoid" : ""}`}>
            {c.text}
          </li>
        ))}
        {chips.length === 0 && <li className="hint">没有识别出具体条件</li>}
      </ul>
      {u.members.length > 0 && (group || u.members.some((m) => m.avoid.length || m.language || m.platform || m.library)) && (
        <ul className="member-chips" aria-label="成员">
          {u.members.map((m, i) => {
            const bits = [
              m.region,
              m.library ? (m.library.public ? `Steam 库 ${m.library.owned} 款` : "Steam 库不公开") : null,
              m.seeds.length ? `喜欢 ${m.seeds.join("、")}` : null,
              m.avoid.length ? `不要 ${m.avoid.map(avoidZh).join("、")}` : null,
              m.language === "schinese" ? "需简体中文" : m.language,
              m.platform ? PLATFORM_ZH[m.platform] : null,
              m.played_elsewhere.length ? `别处玩过 ${m.played_elsewhere.join("、")}` : null,
            ].filter(Boolean);
            return (
              <li className="member" key={i}>
                <Avatar name={m.name} index={i} small />
                <span className="who">
                  {m.name}
                  <small>{bits.join(" · ")}</small>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {u.unresolved.length > 0 && (
        <p className="notice warn" role="status">
          没找到：{u.unresolved.join("、")}。这些名字不在推荐库里，没有参与推荐；可以换个叫法，或在问卷里搜索后点选。
        </p>
      )}
      {ambiguous.map(([name, cands]) => (
        <p className="notice info" key={name}>
          “{name}”可能指：{cands.join(" / ")}。按第一个理解，不对的话在“继续改条件”里说明。
        </p>
      ))}
    </div>
  );
}

function avoidZh(s: string): string {
  return s === "gore" ? "血腥" : s === "sexual" ? "色情内容" : s;
}
