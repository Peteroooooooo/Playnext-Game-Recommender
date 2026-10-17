# 评测数据流水线：完整记录

本文记录 Playnext 同好通道用的评测数据从下载、抓取、核对、补缺、合并到建表、离线评估的全过程，包括每一步的做法、数字、遇到的问题、改过什么、还缺什么。截至 2026-10-13；覆盖数字于 2026-10-16 按现在的核心库（7,304 款）重新核对。数据源的概要见 [Data_Sources.md](Data_Sources.md) ⑤⑥，算法见 [Core_Technical_Skeleton.md](Core_Technical_Skeleton.md) 5.5。

## 1. 目标和范围

- **用途**：同好通道（EASE 权重表 + 卡片统计）、库画像的时长参照、离线评估的测试玩家。
- **范围**：核心库 7,413 款游戏（取数时的名单；2026-10-14 剔除 109 个非游戏后核心库为 7,304 款，评测表没有重建，剔除条目的评测留在表里，不会被推荐出来）的全部评测：从第一条（2010-10）到 2026-10-13，全部语言，全部购买方式（Steam 购买和非 Steam 购买一视同仁），不设条数上限，不抽样。抽样会让不同游戏抽到的不是同一批人，同好重合就没了，早期试过，走不通。
- **不要的**：评测正文（同好只看“谁推荐了什么”）；是否 Steam 购买（2026-10-13 定：算法不区分）；约 2,400 条 Steam 计数里有、但怎么切时间段都取不到的评测（应是被隐藏或删除的，不追）。

## 2. 数据从哪来

### 2.1 Kaggle “steam-reviews-100m”（一次性下载）

- 作者 sergiodelcarpio，MIT 许可，2025-08-12 至 08-26 从 Steam 评测接口抓取。用 `uvx --from kaggle kaggle`（2.2.4，`~/.kaggle/access_token`）下载，压缩包 11.9 GB，解压成 553 个评测 parquet + 游戏信息 parquet，放在 `data/raw/kaggle_reviews100m/extracted/`（约 12 GB，压缩包已按用户要求删除）。
- 评测者 ID（author_id）是完整的 64 位整数：只有 6.2% 是 16 的倍数，和真实 ID 的理论值一致。旧 Kaggle 2024 数据被取整成 16 的倍数，这是换数据的原因（见第 7 节）。
- 核心库里 6,675 款游戏有评测，共 8,459.4 万条，没有重复的评测编号。
- **它缺的**（第 5 节第 4 步逐款核对得出）：
  1. **只有 Steam 商店购买的评测**：每一行 steam_purchase 都是 true（接口默认 purchase_type=steam）。激活码、捆绑包、实体版、免费游戏玩家的评测一条没有，Kaggle 时段里 Steam 上有 4,151 万条，约占三成；免费游戏的评测九成属于这一类。
  2. **179 款抓得不全**：130 款只有最近一段（CS2 只从 2024-06-24 开始，456 万条 Steam 购买评测里只有 54 万条），符合“翻页中途断掉”（第 4 节）；49 款只在它的游戏清单里、评测文件里几乎没有（Subnautica 0 条，Fall Guys 233 条）。
  3. 抓取日之后的评测，以及核心库里它没收的游戏。
  4. 约一半行的 num_games_owned 为空，少量行 playtime 为空（合并时记为 0，0 可能表示未知）。
- 它已有的部分是可信的：和我们自己抓的 51 万条重叠评测逐条比对，评测者、游戏、时间 100% 一致（第 5 节第 7 步）。

### 2.2 Steam 评测接口（我们自己抓）

- 接口 `https://store.steampowered.com/appreviews/<appid>`，免 key。参数：`json=1, filter=recent, language=all, review_type=all, purchase_type=all（补缺时改成 steam 或 non_steam_purchase）, num_per_page=100, cursor=..., start_date / end_date / date_range_type=include`。
- 返回：每页最多 100 条，加一个“书签”（cursor），下一页要用上一页的书签，所以同一个时间段只能顺序翻；`num_per_page=0` 时只返回汇总 query_summary（总条数、好评数、差评数、评级），用来核对“应该有多少条”。
- 每条评测带的字段：recommendationid、voted_up、review（正文）、language、timestamp_created / updated、votes_up / votes_funny、weighted_vote_score、comment_count、steam_purchase、received_for_free、written_during_early_access、primarily_steam_deck；作者 steamid、num_games_owned、num_reviews、playtime_forever、playtime_at_review、playtime_last_two_weeks、last_played。
- **我们存的 11 列**：rec_id、user_hash、appid、voted_up、timestamp_created、timestamp_updated、playtime_forever、playtime_at_review、num_games_owned、num_reviews、language。
- 限速：按出口 IP，约每 5 分钟 200 次（实测连续 150 次后 HTTP 429，封约 4 分钟）。

## 3. 隐私处理

- 盐：`.cache/review_salt`（16 字节随机数，git 已忽略，不外传）。
- 哈希：`blake2b(steamid 的 8 字节小端, key=盐, digest_size=8)`，转成有符号 int64 = user_hash。Kaggle 的 author_id 和接口返回的 steamid 用同一个函数（`fetch_reviews_increment.uhash`），所以同一个人在两边是同一个编号（重叠评测 100% 一致，已验证）。
- 原始 Steam ID 只在内存里出现，不写进任何文件、日志、输出。评测者 ID 必须保持 int64，不能变成浮点数。
- 测试玩家：user_hash % 10 == 0 的 10%，固定不变，不参与任何建表。

## 4. 抓取架构

- **代理**：用户本机的 mihomo 代理池（在仓库外，含控制密钥，不复制、不打印），对外一个 SOCKS5 入口 `socks5h://127.0.0.1:17892`，每个新连接轮换到下一个节点；约 2,792 条经 Steam 实测可用的免费节点配置。入口可用环境变量 `PLAYNEXT_PROXY` 改。之前的 v2rayN + 公开节点、每节点一个 Xray 进程的方案已不用，脚本已删。
- **请求**：`requests[socks]`（2.34.2，pysocks 1.7.1，写死版本），每次请求新建连接，相邻请求从不同节点出去。超时（连接 10 秒、读取 25 秒）、HTTP 429 / 403、非 JSON、success≠1 都直接重试，最多 12 次，重试会换到别的节点。抓到空页先换节点再问 3 次，避免坏节点的空页被当成“抓完了”。每个请求另有 45 秒硬上限（在后台线程里发，超时就放弃）：requests 的读取超时每收到一个字节就重新计时，个别节点一点点吐数据能把请求卡住不放，2026-10-13 第 6 步第二轮就因此整体停住约 20 分钟。
- **并发**：96 个时每秒约 70 页、没有 429；256 个时约 165 页、约 4% 被拒；全量用 160 个，约 115 页 / 秒。
- **为什么几千个节点还是每秒约 100 页**：3,000 个请求只看到 720 个不同出口 IP（估计共约 1,000 个），而且分布不均，最忙的一个 IP 分到 2.3% 的请求，远超 Steam 每 IP 约 0.67 次 / 秒的限额，长期被 429。每个请求往返 1.2 到 1.4 秒，速度约等于并发数 ÷ 1.4 秒。
- **两个 Steam 的坑**（2026-10-13 查明）：
  1. **翻页中途断掉**：在很长的时间段里翻页，Steam 有时先回一页十几条，再回空页，表示“没有了”，其实还有很多。例：《Max Payne 2》两年的时间段，Steam 报 4,177 条，翻到第 1,116 条就断了；6 个不同节点在同一位置都返回空页，是 Steam 的行为。切成一周一段，几乎全部拿回。脚本 `scripts/diagnose_paging.py`、`scripts/diagnose_empty_pages.py`、`scripts/diagnose_short_games.py`。
  2. **约 1/40 的节点报错误的条数**：例如《流放之路 2》报 377 条，实际 59,269 条；带 `cc=US` / `cc=CN` 参数后没有再出现。核对条数一律问到有两次一致为止（`steam_count`，最多问 5 次）。
- **大时间段要提前切细**：同一时间段的页只能顺序翻。CS2 一个月三五万条，就是三五百页、约 10 分钟；《赛博朋克 2077》首发那一周上千页，要半小时以上。最后只剩几个这样的任务时，其他线程全闲着。现在 `refine` 会把每个缺数据的时间段按 Steam 报的条数切成约 20 页一段再并行抓（`slices(..., slice_pages=20)`）。

## 5. 流水线：每一步做了什么

全部命令在 `scripts/` 下用 `uv run python <脚本>` 运行。

### 第 1 步：抓取计划（`fetch_reviews_increment.py plan`，2026-10-12 17:34）

- 每款游戏问一次 Steam 总条数，切成约 100 页一段的任务，写进 `data/raw/steam_reviews_increment/plan.json`。
- 判断“Kaggle 有没有这款”：读 Kaggle 全部 parquet 里的 scrape_date。**这里有个失误**：游戏信息文件里也有 scrape_date，所以 7,007 款被当成“Kaggle 已有”（其中 332 款 Kaggle 评测文件里其实没有或几乎没有），只抓抓取日前一天以后的部分；只有 403 款被当成“Kaggle 没有”，抓全部历史；3 款 Steam 报 0 条。这 332 款抓取日以前的部分后来由第 5、6 步补上。
- 计划：8,525 个任务、7,410 款、约 2,274 万条、约 23.2 万页（窗口任务 8,122 个 / 1,852 万条；全历史 403 款 / 422 万条）。

### 第 2 步：首轮抓取（`run 160`，约 35 分钟）

- 7,410 款全部抓完，2,274 万条，1,351 万名评测者，好评 84.7%。约 21.4 万次成功请求，重试约 4%。
- 中途修的问题：某个时间段没有评测时写出没有列名的空文件（改成显式列名）；全历史任务的切片用运行时的当前时间，名字每次都变（改成用 plan 的生成时间）；坏节点回“成功但空”被当成抓完（改成空页再换节点问 3 次）。
- 早期还有 121 个旧格式空文件（没有列），读取时跳过。

### 第 3 步：核对和修复（`repair`，约 1.5 小时）

- 起因：check 发现 9 款明显偏少（《军团要塞2》94%、《Max Payne 2》67%），查明是第 4 节的两个坑。
- 做法：
  1. 每款按多数投票重新问总条数，写 `verified_counts.json`。核对后 Steam 应有 2,279.9 万条，手上 2,274.0 万条，1,130 款偏少，共缺 59,407 条（《流放之路 2》因为计划时拿到错误的 377 条，只抓了 18,680 条，实际有 59,269 条）。
  2. 偏少的游戏按 年（只计数）→ 月 → 周 → 天 → 小时逐级切小：每级先问 Steam 每段应有多少，只重抓不够的段，还不够的再往下切（`refine`）。重抓的文件名带 `_r`。
- 结果：月级重抓 2,389 段后还缺 30,753；周级后 7,431；天级后 3,120；小时级后 3,123（不再下降）。最终 2,279.6 万条，是 Steam 所报的 99.99%，缺的约 2,400 条分散在约 1,000 款里（最多的是 CS2 253 条），不追。
- 共约 44 万次请求，大部分是核对用的计数请求。

### 第 4 步：Kaggle 完整度核对（`fill_kaggle_gaps.py measure`）

- 每款的“Kaggle 时段”= 从 2010-09 到抓取窗口开始前一秒。对 7,007 款分别问 Steam 购买和非 Steam 购买的条数（多数投票），和手上的比。
- 结果：Steam 购买 Steam 报 9,545 万条，手上 8,424 万条（88.3%），差 50 条以上的 179 款，共缺 1,233 万条；6,828 款吻合（中位 101%，多出的是后来被删的评测）。非 Steam 购买 Steam 报 4,151 万条，手上 0 条。
- 抽样比较两类评测（Kaggle 10% 文件 对 补抓的非 Steam 购买）：好评率 83.4% 对 84.2%，时长中位数都是 54.6 小时，写评测时不到 1 小时 4.2% 对 7.7%；逐款（600 款，各 ≥ 200 条）好评率差中位数 −0.8 个百分点，只有 2.7% 的游戏非 Steam 购买的好评率高出 10 个百分点以上。看不出刷评，保留。

### 第 5 步：补非 Steam 购买的评测（`fill_kaggle_gaps.py nonsteam`，约 1.5 小时）

- 每款按条数切成约 20 页一段（25,359 段），purchase_type=non_steam_purchase，文件名带 `_n`，存 `data/raw/steam_reviews_increment/kaggle_gaps/`。
- 抓到 4,149.7 万条，是 Steam 所报 4,151.4 万条的 99.96%。剩下的 0.04% 没有逐级追（为节省时间停掉）。
- 约 52 万次成功请求，429 约 6%（和第 3 步同时在跑，总并发 256）。

### 第 6 步：补 Kaggle 抓漏的 179 款（`fill_kaggle_gaps.py steam`）

- 第一轮：按年计数找出 990 个缺的年份（缺 1,244 万条），缺的月份整月重抓。抓到约 1,238 万行，但尾部只剩几个大游戏的大月份在顺序翻，停掉。注意这 1,238 万行里有一部分是 Kaggle 已有的（边界月份整月重抓），所以真正还缺的比“1,244 万 − 1,238 万”多：第二轮按年核对时还剩 160 个年份、约 25.6 万条。
- 第二轮（2026-10-13 晚）：年、月只计数，从周开始抓，文件名带 `_s`。月级核对后还缺 428 个月份、约 25.6 万条。抓周时进程停住约 20 分钟，停掉后加了 45 秒硬上限。
- 第三轮：还缺约 14.6 万条，又卡在《赛博朋克 2077》首发那几周（一周上千页、只能顺序翻），停掉。
- 第四轮：缺数据的时间段先按条数切成约 20 页一段再并行抓。周级一轮就从 14.6 万条降到 747 条（约 5.2 万次请求）。结果见第 6 节。

### 第 7 步：合并去重（`build_reviews_merged.py`，约 18 分钟）

- 两遍流式处理，避免整表进内存：第一遍只读评测编号，算出每个文件里哪些行保留；第二遍逐文件读、过滤、写出约 500 万行一个的 parquet。
- 去重规则：Kaggle 内部按评测编号去重；我们抓的内部按评测编号去重（多次重抓的同一条只留一份）；两边都有时保留我们抓的（更新，时长是最新的）。只保留核心库游戏。
- 交叉核对两边都有的 514,810 条：user_hash、appid、timestamp_created 100% 一致；voted_up 99.13% 一致（其余是玩家后来改了评价）；我们抓的时长 ≥ Kaggle 的 99.99%。
- 输出 `data/derived/reviews_merged/`（约 4 GB）：kaggle_NNN.parquet + crawl_NNN.parquet，列 rec_id、user_hash、appid、voted_up、timestamp_created、playtime_forever、playtime_at_review（分钟）、num_games_owned、num_reviews、language、source（0 = Kaggle，1 = 我们抓的）。
- 第一次合并（第 6 步第一轮之后）：1.6076 亿条。最终合并（第四轮之后，2026-10-13 晚）：**1.6101 亿条**（Kaggle 独有 8,408 万 + 我们抓的 7,693 万），**5,232 万名评测者**，7,412 款，2010-10-15 至 2026-10-13，好评 86.4%。我们抓的文件共 59,358 个、9,418 万行，去重后 7,693 万条。
- 第一次运行因为 Kaggle 有空值（playtime、num_games_owned）转整数失败，改成空值记 0 后重跑。

### 第 8 步：建派生表（`build_review_tables.py`，约 2 分钟）

| 文件 | 内容 | 参数 / 结果 |
|---|---|---|
| `eval_reviews100m_test.parquet` | 测试玩家的全部评测：user_hash、app_id、date、voted_up、hours（写评测时）、hours_total | 523 万人、1,613 万条；好评 ≥ 5 条的 67.6 万人 |
| `playtime_reference_100m.parquet` | 每款游戏非测试评测者（正负都算、时长 > 0）的时长分布：n、median_hours、101 个分位点 | 每款至少 50 人；文件里 7,406 款（含 2026-10-14 剔除的条目），在现在核心库里的 7,301 款。《双人成行》19.4 小时、《文明6》157、《Hades》54、《星露谷》130 |
| `ease_reviews100m.npz` | EASE 权重：items（appid）、B（float32，行 = 锚点，列 = 候选）、n（每款好评数） | 训练好评 1.2515 亿条、7,412 款（在现在核心库里的 7,303 款）；λ = 10,000 |
| `colike_reviews100m.parquet` | 卡片统计：app_id、neighbor、sim、co_count | sim = 共同推荐 ÷ √(两款推荐数之积)；共同推荐 ≥ 5；每款 Top-200。文件里 7,410 款有邻居，7,407 款 ≥ 20 个；按现在的核心库算，7,304 款里 7,303 款有邻居且都 ≥ 20 个（2023 到 2026 年发售的全部达到） |

### 第 9 步：离线评估（`eval_ease.py`、`eval_ease.py 100`，各约 3 分钟）

- 做法：测试玩家里好评 ≥ 5 条的 67 万人中随机抽 5 万人；每人好评按时间排序，前一半当口味，后一半当答案；推荐 20 款（排除前一半），看猜中答案的比例（Recall@20），并给 95% 置信区间。训练矩阵只用非测试评测者。`100` 版本把最热门的 100 款从候选和答案里都去掉。

| 方法 | 普通版 | 去掉最热门 100 款 | 旧 Kaggle 2024 数据（普通 / 去热门） |
|---|---|---|---|
| 只推热门 | 0.149 | 0.057 | 0.166 / 0.060 |
| 余弦取最大（原设计） | 0.168 | 0.130 | 0.170 / 0.108 |
| 余弦相加 | 0.198 | 0.151 | 0.193 / 0.125 |
| EASE λ=10,000 | **0.222** | **0.172** | 0.208 / 0.143 |

- EASE 比余弦取最大高 0.054（95% CI [0.052, 0.055]），去热门后高 0.042（[0.040, 0.044]）。λ 在 1,000 到 50,000 之间几乎不变。结论和旧数据一样，采用 EASE。“只推热门”变低，是因为数据更全以后热门游戏不再被过度放大。

## 6. 第二轮补缺后的最终数字

第 6 步第四轮之后重新跑了第 4 步核对（`kaggle_measure2.log`）：

| 部分 | Steam 报的条数 | 手上的条数 | 说明 |
|---|---|---|---|
| Kaggle 时段的 Steam 购买评测（7,007 款） | 9,545 万 | 9,670 万（101.3%） | 多出的是 Kaggle 抓取后被删的评测；只有 46 款各差几条，合计 148 条，没有一款差 50 条以上 |
| Kaggle 时段的非 Steam 购买评测 | 4,151 万 | 4,150 万（99.96%） | 差约 1.7 万条，不追 |
| 抓取窗口内（2025-08 以后 + 全历史游戏） | 2,280 万 | 2,280 万（99.99%） | 差约 2,400 条，Steam 计数里有、取不到，不追 |

第 6 步四轮下来，179 款的 Steam 购买评测从缺约 1,244 万条补到不缺；最后切到一小时一段仍取不到的约 750 条，同样不追。

最终合并、建表和评估的数字已写进第 5 节第 7、8、9 步：评测总表 1.6101 亿条、5,232 万名评测者；测试玩家 523 万人；现在核心库 7,304 款里 7,303 款有 ≥ 20 个同好邻居（取数时的 7,413 款里是 7,407 款）；EASE Recall@20 0.222（去热门 0.172）。

核心库里唯一没有评测的是 900883（《上古卷轴 4》年度版 2009 豪华版，旧版跳转页）。同好邻居不足 20 个的 6 款：它、Batman: Arkham Asylum（35010）、Night Dive advertising app（336390，不是游戏）、Rising Storm 2: Vietnam（418500）、Sid Meier's Civilization IV 及其资料片（34440、34460）。2026-10-14 剔除非游戏条目后，6 款里只有 900883 还在核心库，另外 5 款已被剔除。原计划由 IGDB 相似游戏补同好分，后来放弃了（IGDB 相似只当卡片证据，见设计文档 5.5），所以 900883 的同好一路为 0，只靠标签和介绍两路。

## 7. 被取代和试过不用的

这些做法用到的原始数据、派生文件和脚本已于 2026-10-13 删除（约 5 GB），这里只留结论。

- **Kaggle “Steam Games Reviews 2024”**（截至 2024-06-09）：评测者 ID 被导出方按浮点数取整，全是 16 的倍数，相邻 16 个账号共用一个 ID。用评测编号回 Steam 精确重查证实了这一点。用指纹（游戏数 + 评测数）区分账号也不可靠。不要再下载回来和新数据混用。
- **Kaggle “Game Recommendations on Steam”**（截至 2022-12）：更早的数据。同样不要混用（同一批真实玩家，混用会让测试玩家漏进同好矩阵）。
- **Steam 商店“更多类似内容”页面**：离线 Recall@20 0.118，比只推热门（0.197）还低，不用。
- **每款只抽几百到一千条**：评测者重合太少，不用。
- **按时长给好评加权**：EASE 0.2083 / 0.2071 / 0.2098，几乎不变，不用。
- **v2rayN 节点 + 公开节点、每节点一个 Xray 进程**：127 个出口 IP、每秒约 60 页，被 mihomo 轮换池取代。

## 8. 文件清单

| 路径 | 内容 | 大小 |
|---|---|---|
| `data/raw/kaggle_reviews100m/extracted/` | Kaggle 原始 parquet（含真实 ID，只读） | 约 12 GB |
| `data/raw/steam_reviews_increment/plan.json` | 抓取计划 | — |
| `data/raw/steam_reviews_increment/reviews/` | 增量 + 全历史 + 修复（`_r`），已哈希 | 约 1 GB |
| `data/raw/steam_reviews_increment/kaggle_gaps/` | 非 Steam 购买（`_n`）+ 抓漏补缺（`_s`），已哈希 | 约 2.5 GB |
| `data/raw/steam_reviews_increment/verified_counts.json` | 每款多数投票核对的条数 | — |
| `data/raw/steam_reviews_increment/kaggle_gaps.json` | Kaggle 时段每款两类评测的应有 / 已有条数 | — |
| `data/raw/steam_reviews_increment/*.log` | 各步运行日志（只有计数） | — |
| `data/derived/reviews_merged/` | 评测总表 | 约 4 GB |
| `data/derived/*100m*` | 第 5 节第 8 步的四张表 | 约 530 MB |
| `data/derived/{merge,tables,eval,eval_longtail}.log` | 合并、建表、评估日志 | — |
| `.cache/review_salt` | 哈希用的盐 | — |

`data/` 和 `.cache/` 都不进 git。

## 9. 脚本清单

| 脚本 | 作用 | 命令 |
|---|---|---|
| `fetch_reviews_increment.py` | 计划、抓取、核对、修复 | `plan` / `test [秒] [并发]` / `run [并发]` / `check` / `repair` |
| `fill_kaggle_gaps.py` | 核对 Kaggle 完整度，补非 Steam 购买和抓漏的部分 | `measure` / `nonsteam` / `steam [最小缺口]` |
| `build_reviews_merged.py` | 合并去重成评测总表 | 无参数 |
| `build_review_tables.py` | 建测试玩家、时长参照、EASE、卡片统计 | 无参数 |
| `eval_ease.py` | 离线评估（同好通道各方法的 Recall@20） | `[去掉前 N 热门] [锚点数]` |
| `playtime_signal.py` | 时长排位检验（分位 vs 小时数） | 无参数 |
| `simulate_inputs.py` / `demo_walkthrough.py` | 四种输入的模拟 / 单个用户的逐步演示 | `[--no-llm]` / `[感觉权重]` |
| `diagnose_short_games.py` / `diagnose_paging.py` / `diagnose_empty_pages.py` | 查明翻页中途断掉的诊断脚本 | 见脚本说明 |
| `rate_limit_probe.py` | 测 Steam 每个 IP 的限速 | 无参数 |

## 10. 还没做 / 已知缺口

- **定期补新评测暂不考虑**（2026-10-13 定），数据停在 2026-10-13。以后要做时：现在的 `plan` 是按“Kaggle 抓取日到今天”生成窗口的，需要加一个“从上次抓到的时间到今天”的入口；流程是抓 → `repair` → 合并 → 建表。按过去 14 个月的量，每月约 130 万条、1.3 万页，几分钟。大游戏的时间段要提前切细（第 4 节）。
- **已换到新表（2026-10-13）**：`simulate_inputs.py`（同好改用 EASE 相加，时长查 `playtime_reference_100m`，data_overview.html 的“模拟测试”已按新结果重写）、`demo_walkthrough.py`、`playtime_signal.py`（时长排位检验：分位 0.638 对绝对时长 0.594，685 万名训练评测者，旧数据 0.624 对 0.584）。
- **已清理（2026-10-13）**：旧 Kaggle 2024 与“Game Recommendations on Steam”数据、它们的派生表、Steam“更多类似内容”页面、早期抽样抓的评测、v2rayN 节点文件，以及只服务于这些的 17 个脚本，全部删除；`eval_ease.py` 去掉了 `--old`。
- **少量不追的缺口**：约 2,400 + 750 条 Steam 计数里有、取不到的评测（应是被隐藏或删除的）；非 Steam 购买约 0.04%（约 1.7 万条）。
- **现在核心库 7,304 款里只有 1 款（900883）没有任何评测、同好邻居不足 20 个**，同好一路为 0，只靠标签和介绍两路（取数时的 7,413 款里是 6 款，另外 5 款已于 2026-10-14 剔除，名单见第 6 节）。
- **Kaggle 的 num_games_owned 约一半为空**，合并后为 0；目前算法不用这一列。

## 11. 本轮修改记录（2026-10-13）

- **代码**
  - `fetch_reviews_increment.py`：请求加 45 秒硬上限（`Transport._fetch`）；新增 `steam_count`（多数投票计数）、`refine`（年 / 月 / 周 / 天 / 小时逐级重抓，`fetch_from` 控制从哪一级开始抓）、`repair`、`windows`、`fetched`；任务支持 `tag`（文件名后缀）、`dir`（输出目录）、`purchase`（购买类型）；`base_params` 支持 purchase_type；新增 `EARLIEST`（2010-09-01）；去掉旧的 `recheck`。
  - 新增 `fill_kaggle_gaps.py`、`build_reviews_merged.py`、`build_review_tables.py`、三个诊断脚本。
  - `eval_ease.py`：改读评测总表（旧数据的 `--old` 选项随旧数据一起删掉）。
- **文档**：Data_Sources.md ⑤⑥ 重写（缺口、补抓、修复、合并、速度瓶颈）；Core_Technical_Skeleton.md 5.5 同好通道的数据、依据、覆盖、文件，6.3 来源表第 5、6 行，10.5 更新块；data_overview.html 评测卡片、检验步骤、术语“非 Steam 购买”、缺口、待办、文件表、推荐卡示例；AGENTS.md 数据规则（用 `*100m*` 文件、抓完必须 repair）；本文。
- **决定**：保留非 Steam 购买评测；不区分购买方式；约 2,400 + 750 条取不到的评测不追；定期补新评测暂不考虑。
- **之后**：`simulate_inputs.py`、`demo_walkthrough.py`、`playtime_signal.py` 改读新表并重跑（见第 10 节）；模拟里发现“有显式种子时库锚点减半”在同好相加后压不住（《文明5》进了“像《Hades》”的前 5），已改为“库只在种子池前 50 款内加分（≤ 0.2）”，并加了同系列折叠（Core_Technical_Skeleton.md 4.1、5.5）。按用户要求删除所有旧数据和旧脚本，不留备份（见第 10 节）。
