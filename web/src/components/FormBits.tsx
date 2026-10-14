import { useId } from "react";
import type { AvoidContent, LibraryPolicy, Platform, PriceIntent, Region } from "../api";
import { CURRENCY, LIBRARY_POLICY_ZH, PLATFORM_ZH, PRICE_INTENT_ZH } from "../types";

/** 恐怖 / 血腥 / 色情 hard filters. */
export function AvoidSwitches({
  noHorror,
  avoidContent,
  onHorror,
  onContent,
  legend = "内容雷区（绝对不要）",
}: {
  noHorror: boolean;
  avoidContent: AvoidContent[];
  onHorror: (v: boolean) => void;
  onContent: (v: AvoidContent[]) => void;
  legend?: string;
}) {
  const toggle = (c: AvoidContent, on: boolean) =>
    onContent(on ? Array.from(new Set([...avoidContent, c])) : avoidContent.filter((x) => x !== c));
  return (
    <fieldset className="field plain">
      <legend className="field-label">{legend}</legend>
      <div className="checks">
        <label className="check">
          <input type="checkbox" checked={noHorror} onChange={(e) => onHorror(e.target.checked)} />
          不要恐怖
        </label>
        <label className="check">
          <input type="checkbox" checked={avoidContent.includes("gore")} onChange={(e) => toggle("gore", e.target.checked)} />
          不要血腥
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={avoidContent.includes("sexual")}
            onChange={(e) => toggle("sexual", e.target.checked)}
          />
          不要色情内容
        </label>
      </div>
    </fieldset>
  );
}

export function BudgetInput({
  region,
  value,
  onChange,
  label = "预算",
}: {
  region: Region;
  value: string;
  onChange: (v: string) => void;
  label?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
        <span className="hint"> 按商店区 {region} 的币种，留空表示不限</span>
      </label>
      <div className="money-input">
        <span aria-hidden="true">{CURRENCY[region]}</span>
        <input
          id={id}
          className="input"
          type="number"
          inputMode="decimal"
          min={0}
          step="any"
          placeholder="不限"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}

export function PriceIntentSelect({ value, onChange }: { value: PriceIntent; onChange: (v: PriceIntent) => void }) {
  const id = useId();
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        价格偏好
      </label>
      <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value as PriceIntent)}>
        {(Object.keys(PRICE_INTENT_ZH) as PriceIntent[]).map((k) => (
          <option key={k} value={k}>
            {PRICE_INTENT_ZH[k]}
          </option>
        ))}
      </select>
    </div>
  );
}

export function PlatformSelect({
  value,
  onChange,
  label = "平台",
}: {
  value: Platform | null;
  onChange: (v: Platform | null) => void;
  label?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="input"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? (e.target.value as Platform) : null)}
      >
        <option value="">不限</option>
        {(Object.keys(PLATFORM_ZH) as Platform[]).map((k) => (
          <option key={k} value={k}>
            {PLATFORM_ZH[k]}
          </option>
        ))}
      </select>
    </div>
  );
}

export function LibraryPolicyRadios({
  value,
  onChange,
  hint,
}: {
  value: LibraryPolicy;
  onChange: (v: LibraryPolicy) => void;
  hint?: string;
}) {
  const name = useId();
  return (
    <fieldset className="field plain">
      <legend className="field-label">
        Steam 库里已有的游戏{hint && <span className="hint"> {hint}</span>}
      </legend>
      <div className="checks">
        {(Object.keys(LIBRARY_POLICY_ZH) as LibraryPolicy[]).map((k) => (
          <label className="check" key={k}>
            <input type="radio" name={name} value={k} checked={value === k} onChange={() => onChange(k)} />
            {LIBRARY_POLICY_ZH[k]}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
