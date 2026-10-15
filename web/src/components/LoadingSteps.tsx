import { useEffect, useState } from "react";
import { CheckIcon } from "./Icons";

const STEPS = ["理解需求", "筛选", "打分", "生成卡片"];

/**
 * Progress shown while a request runs. The backend does not stream progress, so steps advance on a timer:
 * slowly for the LLM path (understanding takes most of the 15–30 s), quickly for the form path.
 */
export function LoadingSteps({ slow, title = "正在挑选" }: { slow: boolean; title?: string }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = window.setInterval(() => setElapsed((Date.now() - t0) / 1000), 250);
    return () => window.clearInterval(id);
  }, []);
  const marks = slow ? [0, 12, 17, 21] : [0, 0.3, 0.7, 1.1];
  let step = 0;
  marks.forEach((m, i) => {
    if (elapsed >= m) step = i;
  });

  return (
    <div className="panel" role="status" aria-live="polite">
      <h3>{title}</h3>
      <div className="steps">
        {STEPS.map((s, i) => (
          <div key={s} className={`step${i < step ? " done" : i === step ? " now" : ""}`}>
            <span className="dot">{i < step ? <CheckIcon /> : null}</span>
            {s}…
          </div>
        ))}
      </div>
      <p className="hint">
        已用 <span className="mono">{Math.floor(elapsed)}</span> 秒
        {slow ? "，理解自然语言通常需要 15–30 秒" : ""}
      </p>
    </div>
  );
}
