import type { BudgetScope, Interaction, LibrarySummary, Region, TagsResponse } from "../api";
import {
  HORROR_TAG,
  MAX_MEMBERS,
  MAX_PREFERENCE_TEXT,
  MAX_SEEDS,
  type Libs,
  type Party,
  type PartyMember,
  type Place,
} from "../types";
import { AvoidSwitches, BudgetInput, LibraryPolicyRadios, PlatformSelect, PriceIntentSelect } from "./FormBits";
import { GameSearch } from "./GameSearch";
import { Avatar, XIcon } from "./Icons";
import { LibraryConnect } from "./LibraryConnect";
import { TagPicker } from "./TagPicker";

const PLACES: { key: Place; label: string; help: string }[] = [
  { key: "auto", label: "不限", help: "让系统按人数和每款游戏的支持情况，挑最合适的开局方式。" },
  { key: "online", label: "各自在家", help: "每人一台电脑在线联机。每人需要一份游戏，已经有的人不用买。" },
  { key: "local", label: "同一块屏幕", help: "大家在同一台电脑前同屏玩，一台电脑一份游戏就够，通常每人一个手柄。" },
  { key: "remote", label: "远程同乐", help: "Steam 远程同乐：只有主机需要拥有游戏，其余人通过串流加入，网络延迟以实际为准。" },
  { key: "hybrid", label: "混合", help: "有人在一起、有人在家：给每个人选在哪台电脑前，同一台电脑的人同屏，不同电脑之间在线联机。" },
];

const INTERACTIONS: { key: Interaction; label: string }[] = [
  { key: "coop", label: "一起合作" },
  { key: "versus", label: "互相对战" },
  { key: "any", label: "都行" },
];

const CONTENT_TAGS = [HORROR_TAG, 4345, 12095];

interface Props {
  party: Party;
  onChange: (p: Party) => void;
  tags: TagsResponse | null;
  libs: Libs;
  sessionId: string | null;
  defaultRegion: Region;
  onConnected: (sessionId: string, member: number, summary: LibrarySummary) => void;
  onLogin: (member: number) => void;
  onAddMember: () => void;
  onRemoveMember: (index: number) => void;
  onSubmit: () => void;
  busy: boolean;
  textInUse: boolean;
}

export function PartyPanel(props: Props) {
  const { party, onChange, tags, libs, sessionId, onConnected, onLogin, onAddMember, onRemoveMember, onSubmit, busy, textInUse } =
    props;
  const set = <K extends keyof Party>(k: K, v: Party[K]) => onChange({ ...party, [k]: v });
  const setMember = (i: number, patch: Partial<PartyMember>) =>
    onChange({ ...party, members: party.members.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  const n = party.members.length;
  const place = PLACES.find((p) => p.key === party.place) ?? PLACES[0];
  const hybrid = party.place === "hybrid";

  return (
    <form
      className="party"
      aria-labelledby="party-title"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      {textInUse && (
        <p className="notice info">
          上面写了文字时，人数、开局方式、预算和合作 / 对战以文字为准；这里的名字、商店区、Steam 库、喜欢的游戏、“想玩什么”、雷区和“已拥有”会合并进去。
        </p>
      )}

      <div className="party-row">
        <header>
          <h2 id="party-title">一起玩的 {n} 个人</h2>
          <span className="hint">连上 Steam 的人自动算已有的游戏，其他人可以手动标“已拥有”</span>
        </header>
        <ol className="member-list">
          {party.members.map((m, i) => {
            const lib = libs[i];
            const status = lib ? (lib.summary && !lib.summary.public ? "Steam 库不公开" : "Steam 已连接") : "未连接 Steam";
            return (
              <li className="member-card" key={m.key}>
                <div className="member-head">
                  <Avatar name={m.name} index={i} />
                  <label className="sr-only" htmlFor={`${m.key}-name`}>
                    第 {i + 1} 位成员的名字
                  </label>
                  <input
                    id={`${m.key}-name`}
                    className="input name-input"
                    value={m.name}
                    maxLength={12}
                    placeholder={i === 0 ? "我" : `朋友 ${i + 1}`}
                    onChange={(e) => setMember(i, { name: e.target.value })}
                  />
                  <label className="sr-only" htmlFor={`${m.key}-region`}>
                    {m.name || `第 ${i + 1} 位成员`}的商店区
                  </label>
                  <select
                    id={`${m.key}-region`}
                    className="input sm-select"
                    value={m.region}
                    onChange={(e) => setMember(i, { region: e.target.value as Region })}
                  >
                    <option value="CN">CN · ¥</option>
                    <option value="US">US · $</option>
                  </select>
                  {hybrid && (
                    <>
                      <label className="sr-only" htmlFor={`${m.key}-site`}>
                        {m.name || `第 ${i + 1} 位成员`}在哪台电脑前
                      </label>
                      <select
                        id={`${m.key}-site`}
                        className="input sm-select"
                        value={m.site}
                        onChange={(e) => setMember(i, { site: Number(e.target.value) })}
                      >
                        {Array.from({ length: n }, (_, k) => (
                          <option key={k} value={k + 1}>
                            电脑 {k + 1}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                  <span className={`member-status${lib ? " on" : ""}`}>{status}</span>
                  {i > 0 && (
                    <button
                      type="button"
                      className="x"
                      aria-label={`移除 ${m.name || `第 ${i + 1} 位成员`}`}
                      onClick={() => onRemoveMember(i)}
                    >
                      <XIcon />
                    </button>
                  )}
                </div>
                <label className="sr-only" htmlFor={`${m.key}-pref`}>
                  {m.name || `第 ${i + 1} 位成员`}想玩什么（可不填）
                </label>
                <input
                  id={`${m.key}-pref`}
                  className="input member-pref"
                  value={m.preferenceText ?? ""}
                  maxLength={MAX_PREFERENCE_TEXT}
                  placeholder="想玩什么（可不填）"
                  onChange={(e) => setMember(i, { preferenceText: e.target.value })}
                />
                <details className="member-more">
                  <summary>
                    喜欢的游戏、雷区、已拥有、Steam 库
                    {m.seeds.length + m.ownedExtra.length + m.avoidTags.length + m.avoidContent.length + (m.noHorror ? 1 : 0) > 0 &&
                      " · 已填"}
                  </summary>
                  <div className="member-body">
                    <LibraryConnect
                      member={i}
                      who={i === 0 ? "你" : m.name || `第 ${i + 1} 位成员`}
                      sessionId={sessionId}
                      lib={lib}
                      onConnected={onConnected}
                      onLogin={onLogin}
                      compact
                    />
                    <GameSearch
                      label="喜欢的游戏"
                      hint="最多 3 款"
                      selected={m.seeds}
                      max={MAX_SEEDS}
                      onChange={(v) => setMember(i, { seeds: v })}
                    />
                    <AvoidSwitches
                      legend="雷区"
                      noHorror={m.noHorror}
                      avoidContent={m.avoidContent}
                      onHorror={(v) => setMember(i, { noHorror: v })}
                      onContent={(v) => setMember(i, { avoidContent: v })}
                    />
                    {tags && (
                      <details className="more-fields">
                        <summary>更多雷区标签{m.avoidTags.length ? `（已选 ${m.avoidTags.length}）` : ""}</summary>
                        <TagPicker
                          label="雷区标签"
                          tone="avoid"
                          common={tags.common}
                          all={tags.all}
                          hide={CONTENT_TAGS}
                          selected={m.avoidTags}
                          onChange={(v) => setMember(i, { avoidTags: v })}
                        />
                      </details>
                    )}
                    <GameSearch
                      label="已拥有的游戏"
                      hint="没连 Steam 时手动标，买的时候算 ¥0"
                      selected={m.ownedExtra}
                      max={20}
                      onChange={(v) => setMember(i, { ownedExtra: v })}
                    />
                    <PlatformSelect value={m.platform} onChange={(v) => setMember(i, { platform: v })} />
                  </div>
                </details>
              </li>
            );
          })}
        </ol>
        {n < MAX_MEMBERS ? (
          <button type="button" className="add" onClick={onAddMember}>
            + 加一个人
          </button>
        ) : (
          <span className="hint">最多 {MAX_MEMBERS} 人</span>
        )}
      </div>

      <div className="party-row">
        <header>
          <h2 id="place-title">谁和谁在同一台电脑前</h2>
        </header>
        <div className="seg" role="group" aria-labelledby="place-title">
          {PLACES.map((p) => (
            <button type="button" key={p.key} aria-pressed={party.place === p.key} onClick={() => set("place", p.key)}>
              {p.label}
            </button>
          ))}
        </div>
        <p className="place-help">{place.help}</p>
        {hybrid && <SiteSummary members={party.members} />}
      </div>

      <div className="party-row">
        <header>
          <h2 id="inter-title">怎么玩</h2>
        </header>
        <div className="seg" role="group" aria-labelledby="inter-title">
          {INTERACTIONS.map((p) => (
            <button
              type="button"
              key={p.key}
              aria-pressed={party.interaction === p.key}
              onClick={() => set("interaction", p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="party-row">
        <header>
          <h2>预算</h2>
        </header>
        <div className="grid-2">
          <BudgetInput
            region={party.members[0]?.region ?? props.defaultRegion}
            value={party.budget}
            onChange={(v) => set("budget", v)}
            label={party.budgetScope === "per_person" ? "每人预算" : "全队合计预算"}
          />
          <fieldset className="field plain">
            <legend className="field-label">预算怎么算</legend>
            <div className="seg" role="group" aria-label="预算怎么算">
              {(
                [
                  ["per_person", "每人"],
                  ["team_total", "全队合计"],
                ] as [BudgetScope, string][]
              ).map(([k, label]) => (
                <button type="button" key={k} aria-pressed={party.budgetScope === k} onClick={() => set("budgetScope", k)}>
                  {label}
                </button>
              ))}
            </div>
          </fieldset>
          <PriceIntentSelect value={party.priceIntent} onChange={(v) => set("priceIntent", v)} />
          <fieldset className="field plain">
            <legend className="field-label">语言</legend>
            <label className="check">
              <input type="checkbox" checked={party.chinese} onChange={(e) => set("chinese", e.target.checked)} />
              所有人都需要简体中文
            </label>
          </fieldset>
        </div>
      </div>

      <details className="more-fields party-more">
        <summary>大家共同的口味（可选）</summary>
        <div className="member-body">
          <GameSearch
            label="大家都喜欢的游戏"
            hint="最多 3 款"
            selected={party.seeds}
            max={MAX_SEEDS}
            onChange={(v) => set("seeds", v)}
          />
          {tags && (
            <>
              <TagPicker
                label="想要的感觉"
                common={tags.common}
                all={tags.all}
                selected={party.feelWant}
                onChange={(v) => set("feelWant", v)}
              />
              <TagPicker
                label="不想要的感觉"
                tone="avoid"
                common={tags.common}
                all={tags.all}
                hide={CONTENT_TAGS}
                selected={party.feelAvoid}
                onChange={(v) => set("feelAvoid", v)}
              />
            </>
          )}
          <LibraryPolicyRadios value={party.libraryPolicy} onChange={(v) => set("libraryPolicy", v)} />
        </div>
      </details>

      <div className="quiz-foot">
        <button type="submit" className="send" disabled={busy}>
          {busy ? "推荐中…" : "按这些条件推荐"}
        </button>
      </div>
    </form>
  );
}

function SiteSummary({ members }: { members: PartyMember[] }) {
  const groups = new Map<number, string[]>();
  members.forEach((m, i) => {
    const list = groups.get(m.site) ?? [];
    list.push(m.name || `成员 ${i + 1}`);
    groups.set(m.site, list);
  });
  const sorted = Array.from(groups.entries()).sort((a, b) => a[0] - b[0]);
  return (
    <p className="hint" aria-live="polite">
      {sorted.map(([site, names]) => `电脑 ${site}：${names.join("、")}`).join("　")}
    </p>
  );
}
