"""Regenerate the two generated sections of docs/data_overview.html from the current results:
  simulation  - from .cache/simulate_inputs.json (scripts/simulate_inputs.py, the real system on four inputs)
  request-set - from eval/request_set_results.json (scripts/eval_request_set.py report)
Each section sits between <!-- LEAD: name --> and <!-- /LEAD --> markers; everything between them is replaced.
Usage: uv run python scripts/overview_sections.py [simulation] [request-set]
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "data_overview.html"
e = html.escape


def replace(page, name, body):
    pat = re.compile(rf"(<!-- LEAD: {re.escape(name)} -->)(.*?)(<!-- /LEAD -->)", re.S)
    if not pat.search(page):
        raise SystemExit(f"marker {name} not found")
    return pat.sub(lambda m: m.group(1) + "\n" + body + "\n" + m.group(3), page, count=1)


def pick_li(k, c):
    like = c.get("like") or {}
    ev = []
    if like.get("shared_core_tags"):
        ev.append(f'<span class="s1">{e(" · ".join(like["shared_core_tags"][:3]))}</span>')
    if like.get("feel_hits"):
        ev.append(f'<span class="s1">感觉：{e("、".join(like["feel_hits"]))}</span>')
    if c.get("colike"):
        co = c["colike"]
        ev.append(f'<span class="s4">和《{e(co["anchor"])}》同好 {co["co_count"]:,} 人，排第 {co["rank"]}</span>')
    if c.get("lineage_path"):
        ev.append(f'<span class="s2">{e(c["lineage_path"]["text"])}</span>')
    elif c.get("lineage"):
        ev.append(f'<span class="s2">{e(c["lineage"][0])}</span>')
    if c.get("same_series_folded"):
        ev.append(f'<span class="s2">同系列另有 {len(c["same_series_folded"])} 款</span>')
    anchor = f' · 像《{e(like["anchor"])}》' if like.get("anchor") else ""
    rating = c.get("rating") or {}
    price = (c.get("price") or {}).get("text", "")
    reason = c.get("reason") or ""
    return (f'<li class="pick"><span class="rk">{k}</span><div><div class="nm">{e(c["name"])}</div>'
            f'<div class="meta">{e(c.get("name_en") or "")}{anchor}</div><div class="ev">{"".join(ev)}</div>'
            + (f'<p class="small">理由（{"LLM，已过事实校验" if c.get("reason_source") == "llm" else "模板"}）：{e(reason)}</p>' if reason else "")
            + f'</div><div class="side"><span class="fit">{c["relevance"]:.2f}</span>'
            f'<span>{rating.get("pct_positive", "?")}% 好评</span><span class="muted">{e(price)}</span></div></li>')


def run_block(letter, rid, title, input_text, step1, r):
    rules = "".join(f'<li>{e(x["rule"])}：通过 {x["pass"]:,}，不通过 {x["fail"]:,}，待确认 {x["unknown"]:,}</li>'
                    for x in r.get("rules", []))
    t = r.get("timings", {})
    tparts = [f"规则 {t.get('hard_filter', 0):.2f} 秒", f"打分 {t.get('scoring', 0):.2f} 秒"]
    if "rerank" in t:
        tparts.append(f"LLM 精排 {t['rerank']:.1f} 秒")
    notes = "".join(f"<li>{e(n)}</li>" for n in r.get("notes", []))
    picks = "".join(pick_li(k + 1, c) for k, c in enumerate(r.get("picks", [])))
    failed = "、".join(f"《{e(f['name'])}》（{e('；'.join(f['why'])[:40])}）" for f in r.get("failed", [])[:3])
    unknown = "、".join(f"《{e(u['name'])}》" for u in r.get("unknown", []))
    backups = "、".join(f"《{e(b['name'])}》" for b in r.get("backups", [])[:5])
    return f'''
    <article class="run" aria-labelledby="{rid}">
      <div class="run-head"><span class="letter">{letter}</span><h3 id="{rid}">{e(title)}</h3></div>
      <div class="input"><span class="lbl">模拟输入</span><span>{input_text}</span></div>
      <div class="pstep"><div class="k">1 听懂</div><div class="v">{step1}</div></div>
      <div class="pstep"><div class="k">2 排除<small>三值规则</small></div><div class="v"><ul class="small">{rules}</ul></div></div>
      <div class="pstep"><div class="k">3~5 结果<small>{e("；".join(tparts))}</small></div><div class="v">
        <ol class="picks">{picks}</ol>
        {f'<ul class="small">{notes}</ul>' if notes else ''}
        <p class="small">{f'<b><a class="term" href="#t-unknown">待确认</a>：</b>{unknown}。' if unknown else ''}{f'<b><a class="term" href="#t-short">备选</a>（前 5 款）：</b>{backups}。' if backups else ''}{f'<b>没通过的（举例）：</b>{failed}。' if failed else ''}</p>
      </div></div>
    </article>'''


def simulation():
    d = json.loads((ROOT / ".cache" / "simulate_inputs.json").read_text(encoding="utf-8"))
    w = d["weights"]
    head = (f'<p class="status-note"><b>{e(d["made"][:10])} 用正式系统重跑：</b>下面四个例子走的是 <code>src/playnext/</code> 的完整流程'
            f'（当前权重：同好 {w["colike"]}、标签 {w["tag"]}'
            f'{"、介绍 " + str(w["desc"]) if "desc" in w else ""}、血统 {w["lineage"]}；有偏好原话或感觉时 LLM 精排，w_r = {d["rerank_w"]}；'
            f'口碑先验 α = {d["alpha_beta"][0]}、β = {d["alpha_beta"][1]}），名单、证据、价格和理由都是系统原样输出，脚本 <code>scripts/simulate_inputs.py</code>，'
            '结果存在 <code>.cache/simulate_inputs.json</code>。只有 Steam 游戏库是编的（不查真实账号），价格用当天的每日快照而不是实时价。'
            '契合度是本次候选里的相对分，1.00 表示这次最高。</p>')
    q = d["questionnaire"]
    blocks = [run_block("C", "run-c", "种子问卷", "喜欢的游戏：《Hades》《Hollow Knight》 · 必须支持简体中文 · 雷区：恐怖",
                        "<p>不调 LLM：表单直接变成条件表，两款游戏当种子，各 1.0 分。</p>", q)]
    for key, letter, rid, title in (("sentence", "D", "run-d", "直接说（LLM 理解）"), ("combo", "A+D", "run-ad", "有库，再说清楚这次要什么")):
        if key not in d:
            continue
        r = d[key]
        u = r["understood"]
        b = u.get("budget")
        parts = [f"种子：{'、'.join(u['seeds']) or '无'}"]
        if u.get("feel_want"):
            parts.append(f"想要的感觉：{'、'.join(u['feel_want'])}")
        if u.get("feel_avoid"):
            parts.append(f"不想要：{'、'.join(u['feel_avoid'])}")
        if b:
            parts.append(f"预算：{b['amount']:g} {b.get('currency') or ''}")
        if u.get("price_intent") != "none":
            parts.append(f"价格偏好：{u['price_intent']}")
        step1 = (f"<p>LLM {r.get('understand_seconds', 0):.1f} 秒，程序校验格式和标签名后得到：{e('；'.join(parts))}。"
                 + ("另外接上了下面同一份 Steam 库：有显式种子时，库只在前 50 款里加分。" if key == "combo" else "") + "</p>")
        blocks.append(run_block(letter, rid, title, f"「{e(r['input']['text'])}」", step1, r))
    lib = d["library"]
    owned = "、".join(f"{e(n)} {h:g} 小时" for n, h in lib["input"]["owned"].items())
    anchors = "、".join(f"{e(n)} {w_:.2f}" for n, w_ in lib["anchors_library"].items())
    blocks.insert(1, run_block("A/B", "run-a", "Steam 游戏库", f"模拟的库：{owned}",
                               f"<p>没有种子时，Steam 上玩过的游戏就是口味锚点，权重 = 比这款游戏的其他玩家玩得多的程度：{anchors}。"
                               "时长为 0 的游戏不当锚点；不在核心库的那款只计入“已拥有”。</p>", lib))
    priv = d["private"]
    tail = (f'<p class="small"><b>库读不到时：</b>游戏详情不公开的库不报错，结果页提示“{e(priv["notes"][-1])}”，'
            f'并先按口碑排一版（{e("、".join(priv["picks"][:3]))}……）。</p>')
    return head, "\n".join(blocks) + "\n" + tail


def request_set():
    d = json.loads((ROOT / "eval" / "request_set_results.json").read_text(encoding="utf-8"))
    S = d["stats"]
    sys.path.insert(0, str(ROOT / "src"))
    from playnext import config as C
    main = f"{'llmn' if C.RERANK_GAME_NAMES else 'llm'}_w{C.RERANK_W}"
    main = main if main in S else "system"
    sysv, base, nor = S[main]["all"], S["baseline"]["all"], S["no_rerank"]["all"]
    test_s, test_b = S[main]["test"], S["baseline"]["test"]
    jc = sysv.get("judge_claude") is not None
    rows = [("违反帖子里写明的条件（款，共 160 款）", "fail"), ("推荐了不在库里 / 认不出的游戏", "not_core"),
            ("命中帖子里网友推荐最多的游戏", "community"), ("命中原帖主后来说想试 / 喜欢的", "pos"),
            ("AI 盲评（同一个 LLM 打分，0~2）", "judge")]
    if jc:
        rows.append(("AI 盲评（另一家族的模型打分，0~2）", "judge_claude"))
    trs = "".join(f"<tr><th>{l}</th><td>{sysv[k]}</td><td>{nor[k]}</td><td>{base[k]}</td></tr>" for l, k in rows)
    ia = d["intent"]
    pct = lambda x: f"{x[0]}/{x[1]}"
    best = d["best_dev"]
    return f'''
  <section aria-labelledby="rs-title">
    <div class="sec-head">
      <h2 id="rs-title">32 条真实请求的对比</h2>
      <p>从 Reddit、PTT 和知乎找了 32 条真人发的求推荐帖（两个场景各 16 条）。每条帖子原文交给两方各推荐 5 款：本系统，和“直接把帖子交给同一个 LLM，让它推荐 5 款”。
      违规按<b>逐帖人工写下的条件</b>检查（<code>eval/request_set_gold.json</code>：人数、在哪玩、预算、说过玩过或排除的游戏、明确拒绝的内容），不用系统自己的理解，所以系统读漏的条件也算系统的错。完整报告在 <code>eval/request_set_report.md</code>（{e(d["date"])}）。</p>
    </div>
    <div class="cmp"><table>
      <thead><tr><th></th><th>本系统</th><th>本系统，不开精排</th><th>直接问 LLM</th></tr></thead>
      <tbody>{trs}</tbody>
    </table></div>
    <p class="small"><b>怎么读：</b>守条件这一项系统更少出错，但差距不大，两边都只有几款；系统那 {sysv["fail"]} 款都出在一条写了欧元预算的帖子上，系统没有欧元价格，所以没按预算筛，结果页写明了这一点。口味这一项直接问 LLM 仍然更强，它更会挑大家公认好玩的游戏。
    精排（让 LLM 给前 80 款按帖子原话打分）是差距缩小的主要原因：另一家族模型的打分从不精排的 {nor.get("judge_claude")} 提到 {sysv.get("judge_claude")}，直接问 LLM 是 {base.get("judge_claude")}。只看没参与调参的 16 条测试集：系统 {test_s.get("judge_claude")}，直接问 LLM {test_b.get("judge_claude")}。
    “同一个 LLM 打分”的评委和对照组、精排是同一个模型，可能偏向自己的答案，所以调参用的是另一家族模型的打分。原帖主的反馈太少（13 条帖子），那一行差异不显著。</p>
    <p class="small"><b>需求理解：</b>人数读对 {pct(ia["party_size"])}，开局方式 {pct(ia["setup"])}，预算（金额和币种）{pct(ia["budget"])}，说过玩过 / 排除的游戏找全了 {pct(ia["played_excluded_recall"])}，能对上标签的雷区 {pct(ia["avoid_recall"])}。</p>
    <p class="small"><b>精排器对比</b>（16 条开发集上选、16 条测试集上看）：LLM 精排明显好于专用重排模型 Qwen3-Reranker-4B（后者快得多，约 1 秒，但盲评只比不精排略高）。开发集上各自最好的设置：{e("；".join(f"{k} {v}" for k, v in best.items()))}。</p>
  </section>'''


if __name__ == "__main__":
    which = sys.argv[1:] or ["simulation", "request-set"]
    page = PAGE.read_text(encoding="utf-8")
    if "simulation" in which:
        head, body = simulation()
        page = replace(page, "simulation", head)
        page = replace(page, "simulation-body", body)
    if "request-set" in which:
        page = replace(page, "request-set", request_set())
        page = page.replace('<!-- LEAD: request-set toc (uncomment when the section exists): <li><a href="#rs-title">32 条真实请求的对比</a></li> -->',
                            '<li><a href="#rs-title">32 条真实请求的对比</a></li>')
    PAGE.write_text(page, encoding="utf-8")
    print("updated", which)
