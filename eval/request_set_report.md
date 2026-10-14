# 请求集评估结果（2026-10-14，模型 gemini-3.8-flash-anti）

## 全部 32 条

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 155 | 160 |
| 命中原帖主说喜欢 / 想试的游戏（款） | 2 | 4 |
| 有正面反馈的请求里命中至少一款 | 2/13 | 3/13 |
| 推荐了原帖主拒绝或已玩过的（款） | 5 | 3 |
| 命中社区最多人推荐的游戏（款） | 18（31 条请求） | 37（31 条请求） |
| 违反硬条件（按知识库判 FAIL） | 0 | 19 |
| 无法判断（UNKNOWN） | 0 | 2 |
| 不在核心库 / 认不出的名字 | 0 | 2 |
| 盲评平均分（0~2，补充参考） | 1.58 | 1.74 |
| 盲评 2 分占比 | 0.64 | 0.77 |

## 场景一：找下一款

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 80 | 80 |
| 命中原帖主说喜欢 / 想试的游戏（款） | 2 | 4 |
| 有正面反馈的请求里命中至少一款 | 2/7 | 3/7 |
| 推荐了原帖主拒绝或已玩过的（款） | 3 | 1 |
| 命中社区最多人推荐的游戏（款） | 7（15 条请求） | 14（15 条请求） |
| 违反硬条件（按知识库判 FAIL） | 0 | 11 |
| 无法判断（UNKNOWN） | 0 | 0 |
| 不在核心库 / 认不出的名字 | 0 | 0 |
| 盲评平均分（0~2，补充参考） | 1.56 | 1.62 |
| 盲评 2 分占比 | 0.59 | 0.69 |

## 场景二：一起玩

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 75 | 80 |
| 命中原帖主说喜欢 / 想试的游戏（款） | 0 | 0 |
| 有正面反馈的请求里命中至少一款 | 0/6 | 0/6 |
| 推荐了原帖主拒绝或已玩过的（款） | 2 | 2 |
| 命中社区最多人推荐的游戏（款） | 11（16 条请求） | 23（16 条请求） |
| 违反硬条件（按知识库判 FAIL） | 0 | 8 |
| 无法判断（UNKNOWN） | 0 | 2 |
| 不在核心库 / 认不出的名字 | 0 | 2 |
| 盲评平均分（0~2，补充参考） | 1.6 | 1.86 |
| 盲评 2 分占比 | 0.69 | 0.86 |

## 违规按类型（一款游戏可能同时违反几条）

| 类型 | 系统 | 直接问 LLM |
|---|---|---|
| 已玩过 / 种子本身 | 0 | 1 |
| 多人模式或人数 | 0 | 3 |
| 预算 | 0 | 0 |
| 区域不卖 | 0 | 0 |
| 雷区内容 | 0 | 2 |
| 语言 / 平台 | 0 | 0 |
| 机制组合（本系统自己的严格规则） | 0 | 14 |

只算用户自己说出的条件（去掉“机制组合”这条本系统自己的严格口径）：系统 0 款，直接问 LLM 6 款（共 160 款）。

## 耗时与解释一致性

- 需求理解（LLM）中位 12.4 秒；规则 + 打分 + 排序 + 卡片中位 29.13 秒；推荐理由（LLM，结果出来后再补）中位 16.1 秒；直接问 LLM 中位 18.0 秒。
- LLM 理由通过事实校验的比例：155/155（不通过的改用模板理由）。
- 需求理解失败（LLM 两次都没给出有效 JSON）：0 条；系统没给出推荐的：1 条。

## 逐条

| id | 场景 | 系统推荐 | 直接问 LLM | 正面反馈 | 系统违规 | LLM 违规 |
|---|---|---|---|---|---|---|
| r01 | 1 | Littlewood、House Flipper、Lightyear Frontier、Forager、Garden Life: A Cozy Simulator | Core Keeper、Necesse、Medieval Dynasty、Len's Island、Garden Paws | 3 | — | — |
| r02 | 1 | Outer Wilds、Celeste、Isles of Sea and Sky、Ori and the Will of the Wisps、Minishoot' Adventures | Ori and the Will of the Wisps、Prince of Persia The Lost Crown、TUNIC、Axiom Verge、Celeste | 0 | — | — |
| r03 | 1 | Dyson Sphere Program、The Planet Crafter、FOUNDRY、shapez、SteamWorld Build | Dyson Sphere Program、The Planet Crafter、Shapez 2、Astroneer、Techtonica | 0 | — | shapez 2 - Factory（机制组合：基地建设 + 资源管理 都是核心标签）；ASTRONEER（机制组合：基地建设 + 资源管理 都是核心标签） |
| r04 | 1 | Undertale、Portal 2、CONTROL Ultimate Edition、Katana ZERO、Arco | Portal 2、Undertale、Fallout: New Vegas、Psychonauts、STAR WARS™ - Knights of the Old Republic™ | 2 | — | — |
| r05 | 1 | Terraria、Slay the Spire、Vampire Survivors、Stardew Valley、Satisfactory | Factorio、Risk of Rain 2、Monster Hunter: World、Brotato、Dead Cells | 1 | — | Factorio（种子或已玩过） |
| r06 | 1 | Life is Strange - Episode 1、Before Your Eyes、Outer Wilds、The Beginner's Guide、Oxenfree | Outer Wilds、Before Your Eyes、The Vanishing of Ethan Carter、Oxenfree、SOMA | 4 | — | — |
| r07 | 1 | Terraria、RimWorld、My Time at Sandrock、Factorio、Medieval Dynasty | Valheim、RimWorld、Subnautica、Factorio、Medieval Dynasty | 1 | — | — |
| r08 | 1 | Terraria、Fields of Mistria、Outpath、Garden Paws、Dinkum | Graveyard Keeper、My Time at Sandrock、Rune Factory 4 Special、Medieval Dynasty、Travellers Rest | 0 | — | — |
| r09 | 2 | Human Fall Flat、Haven、Escape Academy、Degrees of Separation、Portal 2 | Haven、Unravel Two、Spiritfarer: Farewell Edition、Divinity: Original Sin 2 - Definitive Edition、Trine 4: The Nightmare Prince | 4 | — | — |
| r10 | 2 | PlateUp!、HELLDIVERS™ 2、Deep Rock Galactic、Lovers in a Dangerous Spacetime、Risk of Rain 2 | Lovers in a Dangerous Spacetime、PlateUp!、Deep Rock Galactic、Warhammer: Vermintide 2、Unrailed! | 1 | — | — |
| r11 | 2 | Luma Island、It Takes Two、Wildmender、Hello Kitty Island Adventure、Roots of Pacha | It Takes Two、Roots of Pacha、Astroneer、Raft、Portal 2 | 0 | — | — |
| r12 | 2 | Wobbly Life、Minecraft Dungeons、KarmaZoo、House Flipper 2、Mining Mechs | PICO PARK、Overcooked! 2、Lovers in a Dangerous Spacetime、Heave Ho、Stardew Valley | 0 | — | Lovers in a Dangerous Spacetime（在线组队：没有在线合作模式（Steam 分类））；Heave Ho（在线组队：没有在线合作模式（Steam 分类）） |
| r13 | 2 | — | Stick Fight: The Game、Terraria、Castle Crashers、Ultimate Chicken Horse、Broforce | 0 | — | — |
| r14 | 2 | DDNet、Core Keeper、Escape Simulator、Last Train Outta' Wormtown、Tower Unite | Terraria、Starbound、Core Keeper、Golf With Your Friends、Necesse | 0 | — | — |
| r15 | 2 | Terraria、HELLDIVERS™ 2、Risk of Rain 2、Valheim、Left 4 Dead 2 | Left 4 Dead 2、Risk of Rain Returns、Heroes of Hammerwatch、Castle Crashers、Streets of Rogue | 2 | — | — |
| r16 | 2 | Terraria、Raft、Parkitect、Swords 'n Magic and Stuff、Garden Paws | Core Keeper、Stardew Valley、Enshrouded、Raft、Terraria | 3 | — | Stardew Valley（在线组队：在线最多 4 人，差 4 个位） |
| r17 | 1 | The Chrono Jotter、Class of '09、Ken ga Kimi、Song of Farca、Marco & The Galaxy Dragon | VA-11 Hall-A: Cyberpunk Bartender Action、Oxenfree、Slay the Princess、A Space for the Unbound、Coffee Talk | 0 | — | — |
| r18 | 1 | Valheim、Medieval Dynasty、ASKA、Soulmask、Sengoku Dynasty | Conan Exiles、Medieval Dynasty、Bellwright、Soulmask、ASKA | 2 | — | Conan Exiles Enhanced（机制组合：生存 + 基地建设 都是核心标签）；Bellwright（机制组合：生存 + 基地建设 都是核心标签） |
| r19 | 1 | Total War: WARHAMMER II、PowerWash Simulator、RimWorld、Dorfromantik、Mount & Blade II: Bannerlord | Diplomacy is Not an Option、Romancing SaGa 2: Revenge of the Seven、Age of Wonders 4、FINAL FANTASY XII THE ZODIAC AGE、Warhammer 40,000: Space Marine 2 | 0 | — | — |
| r20 | 1 | Slipways、Ozymandias: Bronze Age Empire Sim、Rebuild 3: Gangs of Deadsville、Predynastic Egypt、Terraforming Mars | The Battle of Polytopia、Terraformers、Ozymandias: Bronze Age Empire Sim、Slipways、dotAGE | 0 | — | The Battle of Polytopia（机制组合：回合战略 + 管理 都是核心标签）；Terraformers（雷区：类 Rogue）；dotAGE（雷区：类 Rogue、轻度 Rogue、机制组合：回合战略 + 管理 都是核心标） |
| r21 | 1 | Dungeon Munchies、Kitaria Fables、Battle Chef Brigade Deluxe、Immortal Life、Saleblazers | Cuisineer、Battle Chef Brigade Deluxe、Kitaria Fables、Rune Factory 4 Special、Moonlighter | 0 | — | Cuisineer（机制组合：动作 + 烹饪 都是核心标签）；Rune Factory 4 Special（机制组合：动作 + 烹饪 都是核心标签）；Moonlighter（机制组合：动作 + 烹饪 都是核心标签） |
| r22 | 1 | Slay the Spire、Nubby's Number Factory、Peglin、Shogun Showdown、Inscryption | Luck be a Landlord、Slice & Dice、Peglin、Monster Train、Slay the Spire | 0 | — | — |
| r23 | 1 | Manor Lords、Cities: Skylines、Banished、They Are Billions、Frostpunk 2 | Manor Lords、Foundation、Ostriv、Dawn of Man、Becastled | 1 | — | — |
| r24 | 1 | What Remains of Edith Finch、Dungeon Munchies、Minds Beneath Us、MiSide、Chicory: A Colorful Tale | DAVE THE DIVER、DREDGE、Inscryption、Stray、What Remains of Edith Finch | 0 | — | — |
| r25 | 2 | Don't Starve Together、Enshrouded、Core Keeper、Minecraft Dungeons、Coral Island | Raft、Grounded、Nobody Saves the World、Ship of Fools、Portal Knights | 1 | — | — |
| r26 | 2 | Element TD 2 - Tower Defense、Alien Swarm: Reactive Drop、Warhammer: Vermintide 2、Age of Mythology: Retold、HYPERCHARGE: Unboxed | Left 4 Dead 2、Legion TD 2 - Multiplayer Tower Defense、Age of Empires II: Definitive Edition、Deep Rock Galactic、HELLDIVERS™ 2 | 1 | — | — |
| r27 | 2 | Party Animals、Boomerang Fu、Golf With Your Friends、Pikuniku、Untitled Goose Game | Party Animals、Cake Bash、Boomerang Fu、Moving Out、Sackboy: A Big Adventure | 0 | — | — |
| r28 | 2 | Luma Island、Anno 1800、Parkitect、Stardew Valley、Roots of Pacha | Fae Farm、Roots of Pacha、Sun Haven、Parkitect、My Time at Sandrock | 0 | — | — |
| r29 | 2 | Luma Island、Rising World、Mining Mechs、My Little Universe、EVE Online | ASTRONEER、Satisfactory、No Man's Sky、Raft、Grounded | 0 | — | ASTRONEER（机制组合：探索 + 采矿 都是核心标签）；Satisfactory（机制组合：探索 + 采矿 都是核心标签）；No Man's Sky（机制组合：探索 + 采矿 都是核心标签）；Raft（机制组合：探索 + 采矿 都是核心标签）；Grounded（机制组合：探索 + 采矿 都是核心标签） |
| r30 | 2 | Factorio、Baldur's Gate 3、Stardew Valley、No Man's Sky、The Planet Crafter | Factorio、Astroneer、Raft、Stardew Valley、Sid Meier's Civilization VI | 0 | — | — |
| r31 | 2 | Mechabellum、Forts、Alien Swarm: Reactive Drop、Gunfire Reborn、Legion TD 2 - Multiplayer Tower Defense | Deep Rock Galactic、Northgard、Risk of Rain 2、Gunfire Reborn、Warhammer: Vermintide 2 | 0 | — | — |
| r32 | 2 | Ultimate Chicken Horse、Overcooked! 2、Wobbly Life、PICO PARK、Boomerang Fu | Boomerang Fu、Overcooked! 2、Ultimate Chicken Horse、Rubber Bandits、Teenage Mutant Ninja Turtles: Shredder's Revenge | 0 | — | — |
