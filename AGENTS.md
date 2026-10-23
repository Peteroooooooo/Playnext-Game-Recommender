# Playnext 项目规则（给 Codex / Claude Code）

## 先读这些

- `docs/Core_Technical_Skeleton.md` 是唯一的设计依据。文档没写到的事，先问，不要自己拍板。
- `docs/Data_Sources.md` 说明每个数据源拉到了什么、怎么用、覆盖率多少。
- `design/prototype.html` 是界面原型，只作视觉和交互参考，里面的推荐结果是示例。

## 环境

- Python 3.12，用 uv 管理，虚拟环境在仓库根目录的 `.venv`。第一次用先跑 `uv sync`。
- 运行任何 Python 都用 `uv run python ...`、`uv run pytest`。不要直接敲 `python`：这台机器 PATH 上的 `python` 是 Windows 应用商店的占位程序，不会有任何输出。shell 里激活的 conda 环境（dailystudy）也不要用，uv 会自动忽略它。
- 加依赖用 `uv add --bounds exact <包名>`，版本写死；测试和开发工具加 `--dev`。改完一起提交 `pyproject.toml` 和 `uv.lock`。
- torch 与 sentence-transformers 在 `models` 依赖组，只给离线脚本和评测用（默认会装）；在线服务不跑本地模型，服务器上用 `uv sync --no-group models`。torch 在 Windows / Linux 上走 PyTorch 的 cu128 源（本机 RTX 4070 Ti SUPER 16 GB），macOS 走 PyPI。
- 数据库：`docker compose up -d` 启动本地 PostgreSQL 16，只监听 127.0.0.1。连接参数在 `.env` 的 `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD`。
- 生成式 LLM：OpenAI 兼容接口，参数在 `.env` 的 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。它返回的 JSON 可能包在 ```json 代码块里，解析前先去掉，再用 Pydantic 校验。一次小请求约 10 秒，别放在需要即时响应的循环里。
- `.env` 用 `scripts/check_keys.py` 里的 `load_env()` 读取，不另加依赖。

## 数据规则

- `data/` 和 `.cache/` 不进 git。`data/raw/` 是各接口的原始返回，只读，不改不删。
- `data/processed/` 由 `scripts/build_processed.py` 从 raw 重建（约 10 秒）。评测总表 `data/derived/reviews_merged/` 由 `scripts/build_reviews_merged.py` 生成（约 18 分钟），同好权重、卡片统计、时长参照和测试玩家（`ease_reviews100m.npz`、`colike_reviews100m.parquet`、`playtime_reference_100m.parquet`、`eval_reviews100m_test.parquet`）由 `scripts/build_review_tables.py` 从总表生成（约 2 分钟）。
- 除非任务明确要求，不要重新跑 `fetch_*.py` 抓数据：各接口有限速，全量要几个小时，而且会覆盖已有快照。
- 评测数据 = `data/raw/kaggle_reviews100m/`（Kaggle steam-reviews-100m，ID 完整，只有 Steam 购买的评测）+ `data/raw/steam_reviews_increment/`（评测接口补抓，已哈希），见 `docs/Data_Sources.md` ⑤⑥。用 `*100m*` 派生文件。旧的 Kaggle 2024 / “Game Recommendations on Steam” 数据和它们的派生文件已于 2026-10-13 删除，不要再下载回来混用（同一批真实玩家，混用会让测试用户泄漏进同好矩阵）。测试用户只用于离线评估，不能用来算同好矩阵或调参之外的任何训练。
- 评测接口抓完后要跑 `scripts/fetch_reviews_increment.py repair`：Steam 翻页在长时间段里会中途断掉，少数节点也会报错误的条数，必须按多数投票核对后切小时间段重抓。
- 读评测 parquet 时，评测者 ID 必须保持 int64 或字符串，不能让它变成浮点数：浮点数会把 17 位 ID 取整成 16 的倍数，旧 Kaggle 2024 数据就是这样坏掉的。
- `data/raw/kaggle_reviews100m/` 和评测接口返回的数据里都有评测者的真实 Steam ID：只在内存里读取并立即加盐哈希，不要把原始 ID 写进任何派生文件、日志或输出。
- 字段缺失记 UNKNOWN，不要用别的来源或推断补上，除非设计文档写明了补充规则。

## 密钥与隐私

- `.env` 永远不提交。不要把里面的值打印到终端、日志、测试快照或代码里。
- `.cache/proxies/` 里是代理节点的地址、密码和代理池的控制密钥，同样永远不提交、不打印、不复制到仓库其他位置；代码里也不写本机代理软件的路径。抓评测只通过 `PLAYNEXT_PROXY` 指向的本地 SOCKS5 入口。
- 发给外部 LLM 的只能是偏好句段和游戏介绍，不发 SteamID 和用户的游戏库数据。

## 写代码的约定

- 新代码放在 `src/playnext/`（第一次需要时创建），测试放在 `tests/`。`scripts/` 只放数据管线和诊断脚本。
- 每个任务一个分支，不直接提交到 `main`。没被要求就不要 commit。
- 先给实现计划，确认后再写代码。
- 新功能和修 bug 都要带测试，交付前 `uv run pytest` 必须全部通过。
- 规则判断一律三值：PASS / FAIL / UNKNOWN，UNKNOWN 不能当作 PASS。
- 权重、阈值等超参数集中放在配置里，不散落在代码中（见设计文档 10.4）。
- 实现中做出的决定（阈值、模型版本、口径）写回设计文档第 10 节。
