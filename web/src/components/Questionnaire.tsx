import type { Region, TagsResponse } from "../api";
import { emptyPrefs, HORROR_TAG, MAX_SEEDS, type Prefs } from "../types";
import { AvoidSwitches, BudgetInput, LibraryPolicyRadios, PlatformSelect, PriceIntentSelect } from "./FormBits";
import { GameSearch } from "./GameSearch";
import { TagPicker } from "./TagPicker";

interface Props {
  prefs: Prefs;
  onChange: (p: Prefs) => void;
  tags: TagsResponse | null;
  region: Region;
  open: boolean;
  onToggle: () => void;
  onSubmit: () => void;
  busy: boolean;
  textInUse: boolean;
  libConnected: boolean;
}

/** Content tags handled by the AvoidSwitches; kept out of the feel pickers' "avoid" lists to avoid duplicates. */
const CONTENT_TAGS = [HORROR_TAG, 4345, 12095];

export function Questionnaire({ prefs, onChange, tags, region, open, onToggle, onSubmit, busy, textInUse, libConnected }: Props) {
  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) => onChange({ ...prefs, [k]: v });
  const filled =
    prefs.seeds.length + prefs.feelWant.length + prefs.feelAvoid.length + prefs.avoidTags.length + prefs.avoidContent.length +
    (prefs.noHorror ? 1 : 0) + (prefs.chinese ? 1 : 0) + (prefs.platform ? 1 : 0) + (prefs.budget.trim() ? 1 : 0) +
    (prefs.priceIntent !== "none" ? 1 : 0) + (prefs.libraryPolicy !== "none" ? 1 : 0);

  return (
    <section className="quiz" aria-labelledby="quiz-toggle">
      <button
        type="button"
        id="quiz-toggle"
        className="quiz-toggle"
        aria-expanded={open}
        aria-controls="quiz-body"
        onClick={onToggle}
      >
        <span>
          <b>问卷</b>
          <span className="hint">
            {" "}
            点选喜欢的游戏、想要的感觉、雷区和预算{filled ? ` · 已填 ${filled} 项` : ""}
          </span>
        </span>
        <span className="caret" aria-hidden="true">
          {open ? "收起" : "展开"}
        </span>
      </button>
      {open && (
        <form
          id="quiz-body"
          className="quiz-body"
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit();
          }}
        >
          {textInUse && (
            <p className="notice info">
              上面写了文字时以文字为准；问卷里的喜欢的游戏、雷区、语言和平台会合并进去。想完全按问卷来，先清空上面的文字。
            </p>
          )}
          <GameSearch
            label="喜欢的游戏"
            hint="1–3 款，用来找相似的"
            selected={prefs.seeds}
            max={MAX_SEEDS}
            onChange={(v) => set("seeds", v)}
          />
          {tags ? (
            <>
              <TagPicker
                label="想要的感觉"
                common={tags.common}
                all={tags.all}
                selected={prefs.feelWant}
                onChange={(v) => set("feelWant", v)}
              />
              <TagPicker
                label="不想要的感觉"
                hint="尽量避开，不是硬性排除"
                tone="avoid"
                common={tags.common}
                all={tags.all}
                hide={CONTENT_TAGS}
                selected={prefs.feelAvoid}
                onChange={(v) => set("feelAvoid", v)}
              />
            </>
          ) : (
            <p className="hint">标签加载中…</p>
          )}
          <AvoidSwitches
            noHorror={prefs.noHorror}
            avoidContent={prefs.avoidContent}
            onHorror={(v) => set("noHorror", v)}
            onContent={(v) => set("avoidContent", v)}
          />
          {tags && (
            <details className="more-fields">
              <summary>更多雷区标签{prefs.avoidTags.length ? `（已选 ${prefs.avoidTags.length}）` : ""}</summary>
              <TagPicker
                label="雷区"
                hint="带这些标签的游戏直接排除"
                tone="avoid"
                common={tags.common}
                all={tags.all}
                hide={CONTENT_TAGS}
                selected={prefs.avoidTags}
                onChange={(v) => set("avoidTags", v)}
              />
            </details>
          )}
          <div className="grid-2">
            <fieldset className="field plain">
              <legend className="field-label">其他要求</legend>
              <label className="check">
                <input type="checkbox" checked={prefs.chinese} onChange={(e) => set("chinese", e.target.checked)} />
                必须支持简体中文
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!prefs.singlePlayer}
                  onChange={(e) => set("singlePlayer", e.target.checked)}
                />
                一个人玩（要有单人模式）
              </label>
            </fieldset>
            <PlatformSelect value={prefs.platform} onChange={(v) => set("platform", v)} />
            <BudgetInput region={region} value={prefs.budget} onChange={(v) => set("budget", v)} />
            <PriceIntentSelect value={prefs.priceIntent} onChange={(v) => set("priceIntent", v)} />
          </div>
          <LibraryPolicyRadios
            value={prefs.libraryPolicy}
            onChange={(v) => set("libraryPolicy", v)}
            hint={libConnected ? undefined : "连接 Steam 后才生效"}
          />
          <div className="quiz-foot">
            <button type="submit" className="send" disabled={busy}>
              {busy ? "推荐中…" : "按这些条件推荐"}
            </button>
            <button type="button" className="link" onClick={() => onChange(emptyPrefs())}>
              清空问卷
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
