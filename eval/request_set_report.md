# 请求集评估结果（2026-10-16，生成式模型 gemini-3.8-flash-anti）

32 条论坛真实求推荐帖（Reddit 16、PTT 15、知乎 1；两个场景各 16 条）。每条帖子交给两方：本系统，和“直接问同一个 LLM 推荐 5 款”。
硬条件按 `eval/request_set_gold.json` 检查：逐帖阅读写下的条件（人数、开局方式、单人、预算、说过玩过或排除的游戏、明确拒绝的内容），**不用系统自己的理解**，所以系统读漏的条件也算系统违规。雷区只认核心标签（票数占比 ≥ 0.5）；欧元预算没有汇率数据，按美区美元价超过上限 1.25 倍才算违规。

## 总表（全部 32 条）

“系统”一列是现行设置（llmn_w0.9：LLM 精排 w_r = 0.9，附游戏英文名），它是在开发集上选出来的，所以开发集一半的数字偏乐观，看下面测试集一列更公平。

| 指标 | 系统（现行设置） | 不精排 | 直接问 LLM |
|---|---|---|---|
| 推荐的游戏数 | 160 | 160 | 160 |
| 违反帖子里写明的硬条件（款） | 2 | 2 | 4 |
| 缺事实、无法判断（款） | 0 | 5 | 3 |
| 不在核心库 / 认不出（款） | 0 | 0 | 2 |
| 命中原帖主说喜欢 / 想试的（款） | 4 | 3 | 4 |
| 有正面反馈的请求里命中至少一款 | 2/13 | 3/13 | 3/13 |
| 推荐了原帖主后来说拒绝或已玩过的（款） | 3 | 0 | 4 |
| 命中帖子里网友推荐最多的（款） | 25 | 16 | 39 |
| LLM 盲评平均（0~2） | 1.71 | 0.91 | 1.9 |
| LLM 盲评 2 分占比 | 0.76 | 0.3 | 0.91 |
| 第二评委盲评平均（0~2，另一模型家族） | 1.81 | 1.24 | 1.91 |

### 场景一：找下一款

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 80 | 80 |
| 违反帖子里写明的硬条件（款） | 0 | 1 |
| 缺事实、无法判断（款） | 0 | 0 |
| 不在核心库 / 认不出（款） | 0 | 0 |
| 命中原帖主说喜欢 / 想试的（款） | 4 | 4 |
| 有正面反馈的请求里命中至少一款 | 2/7 | 3/7 |
| 推荐了原帖主后来说拒绝或已玩过的（款） | 2 | 1 |
| 命中帖子里网友推荐最多的（款） | 10 | 15 |
| LLM 盲评平均（0~2） | 1.79 | 1.88 |
| LLM 盲评 2 分占比 | 0.8 | 0.88 |
| 第二评委盲评平均（0~2，另一模型家族） | 1.82 | 1.89 |

### 场景二：一起玩

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 80 | 80 |
| 违反帖子里写明的硬条件（款） | 2 | 3 |
| 缺事实、无法判断（款） | 0 | 3 |
| 不在核心库 / 认不出（款） | 0 | 2 |
| 命中原帖主说喜欢 / 想试的（款） | 0 | 0 |
| 有正面反馈的请求里命中至少一款 | 0/6 | 0/6 |
| 推荐了原帖主后来说拒绝或已玩过的（款） | 1 | 3 |
| 命中帖子里网友推荐最多的（款） | 15 | 24 |
| LLM 盲评平均（0~2） | 1.63 | 1.93 |
| LLM 盲评 2 分占比 | 0.72 | 0.95 |
| 第二评委盲评平均（0~2，另一模型家族） | 1.8 | 1.92 |

## 违规明细（按帖子写明的条件）

**系统**（2 款）：r15《HELLDIVERS™ 绝地潜兵2》超预算：$39.99，远高于 €20；r15《Valheim: 英灵神殿》超预算：$29.99，远高于 €20

**直接问 LLM**（4 款）：r02《TUNIC》雷区：soulslike（核心标签 Souls-like）；r12《Lovers in a Dangerous Spacetime》人数 / 模式：没有在线合作模式（Steam 分类）；r12《Boomerang Fu》人数 / 模式：没有在线合作模式（Steam 分类）；r14《Stardew Valley》人数 / 模式：在线最多 4 人，差 1 个位

## 精排器与 w_r（开发集选、测试集报告）

开发 / 测试按场景内 id 交替拆分（各 16 条）。只在开发集上比较；“不精排”与各精排设置用同一份候选与打分。

按第二评委（另一模型家族）在开发集上选。

| 设置 | 开发集盲评（同一 LLM） | 开发集第二评委 | 开发集网友共识 | 测试集盲评（同一 LLM） | 测试集第二评委 | 测试集网友共识 | 测试集违规 |
|---|---|---|---|---|---|---|---|
| no_rerank | 0.94 | 1.21 | 9 | 0.88 | 1.27 | 7 | 0 |
| llm_w0.3 | 1.25 | 1.49 | 12 | 1.4 | 1.61 | 8 | 0 |
| llm_w0.45 | 1.38 | 1.61 | 12 | 1.53 | 1.71 | 10 | 0 |
| llm_w0.6 ← | 1.56 | 1.73 | 11 | 1.61 | 1.75 | 11 | 0 |
| llm_w0.75 | 1.57 | 1.73 | 11 | 1.69 | 1.82 | 12 | 0 |
| llm_w0.9 | 1.57 | 1.71 | 11 | 1.8 | 1.84 | 13 | 0 |
| llmn_w0.3 | 1.21 | 1.43 | 11 | 1.32 | 1.55 | 7 | 0 |
| llmn_w0.45 | 1.36 | 1.55 | 11 | 1.52 | 1.7 | 9 | 0 |
| llmn_w0.6 | 1.55 | 1.7 | 12 | 1.65 | 1.79 | 11 | 0 |
| llmn_w0.75 | 1.59 | 1.74 | 12 | 1.75 | 1.84 | 13 | 0 |
| llmn_w0.9 ← | 1.65 | 1.79 | 12 | 1.77 | 1.84 | 13 | 0 |
| local_w0.3 | 0.97 | 1.27 | 13 | 1.08 | 1.45 | 8 | 1 |
| local_w0.45 | 1.04 | 1.31 | 11 | 1.15 | 1.52 | 6 | 1 |
| local_w0.6 | 1.06 | 1.34 | 10 | 1.11 | 1.54 | 6 | 0 |
| local_w0.75 ← | 1.1 | 1.35 | 10 | 1.12 | 1.57 | 5 | 0 |
| local_w0.9 | 1.06 | 1.34 | 10 | 1.07 | 1.55 | 4 | 0 |
| localn_w0.3 | 0.97 | 1.29 | 11 | 1.07 | 1.41 | 7 | 2 |
| localn_w0.45 | 1.02 | 1.32 | 9 | 1.13 | 1.48 | 8 | 1 |
| localn_w0.6 | 1.15 | 1.39 | 9 | 1.16 | 1.52 | 5 | 0 |
| localn_w0.75 ← | 1.1 | 1.39 | 11 | 1.12 | 1.51 | 5 | 0 |
| localn_w0.9 | 1.06 | 1.38 | 9 | 1.12 | 1.51 | 5 | 0 |

开发集上各精排器最好的设置：LLM 精排 llm_w0.6；LLM 精排 + 游戏英文名 llmn_w0.9；Qwen3-Reranker-4B local_w0.75；Qwen3-Reranker-4B + 游戏英文名 localn_w0.75。综合最好：llmn_w0.9。耗时中位：LLM 精排 27.9 秒；Qwen3-Reranker-4B 1.1 秒（本机 GPU，模型已载入）。名字后缀 = 把帖子里提到的游戏的英文官方名附在请求后面（`rerank.with_game_names`）。

## 需求理解准确率（系统理解 vs 逐帖写下的条件）

- 人数：28/30（93%）；开局方式：9/9（100%）；预算（金额 + 币种，含“没说预算”）：32/32（100%）
- 说过玩过 / 排除的游戏：召回 121/138（88%），精确 121/148（82%）（系统一侧含种子游戏，种子本来也不会被推荐）
- 能对上 Steam 标签的雷区：召回 15/17（88%）

<details><summary>逐条漏读</summary>

- r01 漏掉玩过 / 排除：Grand Theft Auto V 传承版
- r01 漏掉玩过 / 排除：巫师3：狂猎 — 重制版
- r01 漏掉玩过 / 排除：Fallout 4
- r01 漏掉玩过 / 排除：The Elder Scrolls V: Skyrim Special Edition
- r01 漏掉玩过 / 排除：Red Dead Redemption 2
- r02 漏掉玩过 / 排除：Grand Theft Auto V 传承版
- r02 漏掉雷区：soulslike
- r02 漏掉雷区：inventory management
- r05 漏掉玩过 / 排除：The Elder Scrolls V: Skyrim Special Edition
- r07 漏掉玩过 / 排除：Schedule I
- r10 人数：系统 3，帖子 4
- r15 漏掉玩过 / 排除：The Binding of Isaac: Rebirth
- r19 漏掉玩过 / 排除：全面战争：战锤3
- r19 漏掉玩过 / 排除：光与影：33号远征队
- r20 漏掉玩过 / 排除：Age of Empires II: Definitive Edition
- r26 漏掉玩过 / 排除：Age of Empires II: Definitive Edition
- r26 漏掉玩过 / 排除：《命令与征服™：重制版》
- r28 漏掉玩过 / 排除：The Sims™ 4
- r29 人数：系统 2，帖子 3
- r31 漏掉玩过 / 排除：Overcooked! 2
- r31 漏掉玩过 / 排除：Age of Empires II: Definitive Edition

</details>

## 耗时与解释一致性

- 需求理解（LLM）中位 11.9 秒；规则 + 打分 + 精排 + 排序 + 卡片中位 28.1 秒；推荐理由（结果出来后再补）中位 14.2 秒；直接问 LLM 中位 16.0 秒。
- LLM 理由通过事实校验：160/160（不通过的用模板理由）。
- 需求理解失败：0 条；系统没给出推荐：0 条。

## 逐条

| id | 场景 | 拆分 | 系统推荐 | 直接问 LLM | 系统违规 | LLM 违规 |
|---|---|---|---|---|---|---|
| r01 | 1 | dev | 房产达人、Littlewood、Lightyear Frontier、Farm Together、Sun Haven | Forager、No Place Like Home、Core Keeper、Garden Paws、Slime Rancher | — | — |
| r02 | 1 | test | Outer Wilds、Celeste、Ori and the Will of the Wisps、小飞船大冒险 Minishoot' Adventures、FEZ | Ori and the Will of the Wisps、TUNIC、Hyper Light Drifter、Environmental Station Alpha、Outer Wilds | — | TUNIC（雷区：soulslike（核心标签 Souls-like）） |
| r03 | 1 | dev | 戴森球计划、星球工匠、FOUNDRY、Factory Town、异形工厂（Shapez） | Dyson Sphere Program、The Planet Crafter、shapez 2、FOUNDRY、ASTRONEER | — | — |
| r04 | 1 | test | Undertale、Portal 2、影子诡局：被诅咒的海盗 Shadow Gambit: The Cursed Crew、遗忘之城、Haven | Undertale、Psychonauts、A Short Hike、OneShot、West of Loathing | — | — |
| r05 | 1 | dev | 幸福工厂、Vampire Survivors - 吸血鬼幸存者、Terraria、戴森球计划、Stardew Valley | Factorio、Risk of Rain 2、Dead Cells、Monster Hunter: World、Vampire Survivors | — | — |
| r06 | 1 | test | 历历在目、Outer Wilds、The Vanishing of Ethan Carter、The Beginner's Guide、Gone Home | Before Your Eyes、The Vanishing of Ethan Carter、Gone Home、Everybody's Gone to the Rapture、Outer Wilds | — | — |
| r07 | 1 | dev | Terraria、边缘世界 RimWorld、Factorio、Project Zomboid、Valheim: 英灵神殿 | RimWorld、Subnautica、ZERO Sievert、Medieval Dynasty、Factorio | — | — |
| r08 | 1 | test | Fields of Mistria、潜水员戴夫 DAVE THE DIVER、Echoes of the Plum Grove、Dinkum(金垦小镇)、Roots of Pacha | My Time at Sandrock、Graveyard Keeper、Medieval Dynasty、Rune Factory 4 Special、Core Keeper | — | — |
| r09 | 2 | dev | 真‧三國無雙６ with 猛將傳 DX、旧世界 Old World、波兰球：编年史、As Dusk Falls、旅者之憩 Travellers Rest | Unravel Two、Haven、Brothers: A Tale of Two Sons Remake、Baldur's Gate 3、Spiritfarer: Farewell Edition | — | — |
| r10 | 2 | test | 速速上菜！、World War Z、深岩银河、Unrailed!、Monaco: What's Yours Is Mine | PlateUp!、Lovers in a Dangerous Spacetime、Warhammer: Vermintide 2、Deep Rock Galactic、Unrailed! | — | — |
| r11 | 2 | dev | Escape Academy、Portal 2、Roots of Pacha、双人成行、Operation: Tango - Friend Pass | Roots of Pacha、It Takes Two、ASTRONEER、Raft、Portal 2 | — | — |
| r12 | 2 | test | 晃晃人生 / Wobbly Life、Minecraft Dungeons、胡闹厨房 全都好吃、麻布仔大冒险、因果动物园 | PICO PARK、Lovers in a Dangerous Spacetime、Unrailed!、Ultimate Chicken Horse、Boomerang Fu | — | Lovers in a Dangerous Spacetime（人数 / 模式：没有在线合作模式（Steam 分类））；Boomerang Fu（人数 / 模式：没有在线合作模式（Steam 分类）） |
| r13 | 2 | dev | Terraria、Vampire Survivors - 吸血鬼幸存者、Among Us、Red Dead Redemption 2、Bloons TD 6 | Stick Fight: The Game、Terraria、Castle Crashers、Broforce、Golf With Your Friends | — | — |
| r14 | 2 | test | Among Us、Raft、Tabletop Simulator、密室逃脱模拟器、猛兽派对 | Terraria、Core Keeper、Necesse、Stardew Valley、Teenage Mutant Ninja Turtles: Shredder's Revenge | — | Stardew Valley（人数 / 模式：在线最多 4 人，差 1 个位） |
| r15 | 2 | dev | HELLDIVERS™ 绝地潜兵2、雨中冒险 2、Valheim: 英灵神殿、Left 4 Dead 2、Castle Crashers® | Left 4 Dead 2、Risk of Rain Returns、Heroes of Hammerwatch、Streets of Rogue、Broforce | HELLDIVERS™ 绝地潜兵2（超预算：$39.99，远高于 €20）；Valheim: 英灵神殿（超预算：$29.99，远高于 €20） | — |
| r16 | 2 | test | Stardew Valley、星球工匠、Terraria、Palworld / 幻兽帕鲁、Farm Together 2 | Stardew Valley、Raft、Core Keeper、Enshrouded、Palworld | — | — |
| r17 | 1 | dev | VA-11 Hall-A: Cyberpunk Bartender Action、海沙风云 Far Away、Hakuoki: Kyoto Winds、Jenny LeClue - Detectivu、宇宙之轮姐妹会 | VA-11 Hall-A: Cyberpunk Bartender Action、OPUS: Echo of Starsong - Full Bloom Edition、Oxenfree、I Was a Teenage Exocolonist、Slay the Princess | — | — |
| r18 | 1 | test | 中世纪王朝、灵魂面甲(Soulmask)、ASKA、雾锁王国 (Enshrouded)、Valheim: 英灵神殿 | Soulmask、Bellwright、Conan Exiles、Medieval Dynasty、ASKA | — | — |
| r19 | 1 | dev | 潜水员戴夫 DAVE THE DIVER、全面战争：战锤2、Crusader Kings III、Sid Meier’s Civilization® VI、冲就完事模拟器 | Diplomacy is Not an Option、Romancing SaGa 2: Revenge of the Seven、FINAL FANTASY XII THE ZODIAC AGE、Age of Wonders 4、Vampire Survivors | — | — |
| r20 | 1 | test | 法老王：青铜帝国 Ozymandias、Terraforming Mars、Slipways、Rebuild 3: Gangs of Deadsville、Predynastic Egypt | The Battle of Polytopia、Ozymandias: Bronze Age Empire Sim、Slipways、Terraforming Mars、Terra Nil | — | — |
| r21 | 1 | dev | Cuisineer 猫娘小厨、波西亚时光、咩咩启示录、幻想生活ｉ 转圈圈的龙和偷取时间的少女、东方夜雀食堂 - Touhou Mystia's Izakaya | Cuisineer、Dungeon Munchies、Battle Chef Brigade Deluxe、Moonlighter、Rune Factory 4 Special | — | — |
| r22 | 1 | test | Slay the Spire、Nubby's Number Factory、哥布林弹球 Peglin、骰子闯魔城、弹球亿万富翁 | Luck be a Landlord、Slice & Dice、Peglin、Monster Train、Backpack Hero | — | — |
| r23 | 1 | dev | 庄园领主 Manor Lords、族人 Clanfolk、海狸浮生记 Timberborn、纪元1800、Infection Free Zone (无感染区) | Manor Lords、Banished、Foundation、Endzone - A World Apart、Dawn of Man | — | — |
| r24 | 1 | test | INSIDE、What Remains of Edith Finch、宅男的人间冒险、生化奇兵：无限 完全版、米塔 MiSide | Dave the Diver、Dredge、Inscryption、Subnautica、Ghost Trick: Phantom Detective | — | — |
| r25 | 2 | dev | Raft、露玛岛、Dinkum(金垦小镇)、Grounded、幻想生活ｉ 转圈圈的龙和偷取时间的少女 | Core Keeper、Raft、Grounded、Nobody Saves the World、My Time at Sandrock | — | — |
| r26 | 2 | test | Left 4 Dead 2、Age of Mythology: Retold、元素塔防2、HELLDIVERS™ 绝地潜兵2、异形丛生：虫启天降 (Alien Swarm: Reactive Drop) | Left 4 Dead 2、Legion TD 2 - Multiplayer Tower Defense、Sanctum 2、Deep Rock Galactic、HELLDIVERS™ 2 | — | — |
| r27 | 2 | dev | Boomerang Fu、猛兽派对、Untitled Goose Game、LEGO® The Incredibles、麻布仔大冒险 | Party Animals、Cake Bash、Boomerang Fu、Heave Ho、Moving Out | — | — |
| r28 | 2 | test | Stardew Valley、《Spiritfarer®》Farewell版、Roots of Pacha、旅者之憩 Travellers Rest、露玛岛 | Roots of Pacha、Fae Farm、Spiritfarer: Farewell Edition、Parkitect、Sun Haven | — | — |
| r29 | 2 | dev | 雾锁王国 (Enshrouded)、荒原疗者 (Wildmender)、ASTRONEER、无径之林、Aloft | Astroneer、No Man's Sky、Grounded、Raft、Satisfactory | — | — |
| r30 | 2 | test | Factorio、博德之门3、纪元1800、ASTRONEER、FOUNDRY | Factorio、Baldur's Gate 3、Astroneer、Sid Meier’s Civilization VI、Stardew Valley | — | — |
| r31 | 2 | dev | 深岩银河、钢铁指挥官、雨中冒险 2、Age of Empires IV: Anniversary Edition、Warhammer 40,000: 星际战士2 | Deep Rock Galactic、Legion TD 2 - Multiplayer Tower Defense、Northgard、Risk of Rain 2、Warhammer: Vermintide 2 | — | — |
| r32 | 2 | test | 超级鸡马、Overcooked! 2、Stick Fight: The Game、Castle Crashers®、Boomerang Fu | Boomerang Fu、Overcooked! 2、Ultimate Chicken Horse、Rubber Bandits、Pummel Party | — | — |
