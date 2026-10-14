import { useRef } from "react";
import type { Mode } from "../types";
import { ArrowIcon } from "./Icons";

const EXAMPLES: Record<Mode, string[]> = {
  single: [
    "刚通关《哈迪斯》，还想要类似的，别太难，100 块以内",
    "想要轻松治愈的，最好有简体中文",
    "像《杀戮尖塔》那样的卡牌肉鸽，最好在打折",
  ],
  group: [
    "我们 4 个人各自在家，每人 60 块以内，想一起合作",
    "4 个人在客厅同屏，轻松点的",
    "两个人想对战，别要恐怖的",
  ],
};

interface Props {
  mode: Mode;
  onMode: (m: Mode) => void;
  text: string;
  onText: (t: string) => void;
  onSubmit: () => void;
  llm: boolean | null;
  busy: boolean;
}

export function AskBox({ mode, onMode, text, onText, onSubmit, llm, busy }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const group = mode === "group";
  const textOff = llm === false;

  return (
    <section className="ask" aria-labelledby="ask-title">
      <h1 id="ask-title">{group ? "今晚一起玩什么？" : "下一款玩什么？"}</h1>
      <p className="lede">
        {group
          ? "说说有几个人、在哪玩、预算多少。只推荐大家都能开局的游戏，还会写清楚谁要买、怎么开局。"
          : "说说你想要的感觉，或者刚玩完哪一款。推荐会讲清楚像在哪、差在哪，价格只摆事实。"}
      </p>
      <div className="seg" role="group" aria-label="推荐模式">
        <button type="button" aria-pressed={!group} onClick={() => onMode("single")}>
          找下一款
        </button>
        <button type="button" aria-pressed={group} onClick={() => onMode("group")}>
          一起玩
        </button>
      </div>

      {textOff ? (
        <div className="notice warn" role="status">
          自然语言输入暂不可用，请用问卷{group ? "（下方的成员和条件）" : ""}。
        </div>
      ) : (
        <>
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit();
            }}
          >
            <label htmlFor="ask-text" className="sr-only">
              {group ? "大家想玩什么" : "说说你想玩什么"}
            </label>
            <textarea
              id="ask-text"
              ref={ref}
              rows={2}
              value={text}
              maxLength={500}
              placeholder={group ? "说说大家想玩什么…（也可以只填下面的成员和条件）" : "说说你想玩什么…"}
              onChange={(e) => onText(e.target.value)}
              onKeyDown={(e) => {
                // Enter sends, Shift+Enter breaks the line; never while an IME is composing Chinese.
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (!busy) onSubmit();
                }
              }}
            />
            <button className="send" type="submit" disabled={busy} aria-label="推荐">
              <span className="lbl">{busy ? "推荐中" : "推荐"}</span>
              <ArrowIcon />
            </button>
          </form>
          <div className="examples">
            <span id="ex-label">试试：</span>
            {EXAMPLES[mode].map((x) => (
              <button
                type="button"
                className="ex"
                key={x}
                aria-describedby="ex-label"
                onClick={() => {
                  onText(x);
                  ref.current?.focus();
                }}
              >
                {x}
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
