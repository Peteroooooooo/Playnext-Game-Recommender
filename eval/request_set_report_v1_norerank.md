# 请求集评估结果（2026-10-14，模型 gemini-3.8-flash-anti）

## 全部 32 条

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 155 | 160 |
| 命中原帖主说喜欢 / 想试的游戏（款） | 3 | 4 |
| 有正面反馈的请求里命中至少一款 | 3/13 | 3/13 |
| 推荐了原帖主拒绝或已玩过的（款） | 2 | 4 |
| 命中社区最多人推荐的游戏（款） | 13（31 条请求） | 38（31 条请求） |
| 违反硬条件（按知识库判 FAIL） | 0 | 21 |
| 无法判断（UNKNOWN） | 0 | 3 |
| 不在核心库 / 认不出的名字 | 0 | 3 |
| 盲评平均分（0~2，补充参考） | 0.85 | 1.85 |
| 盲评 2 分占比 | 0.26 | 0.85 |

## 场景一：找下一款

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 80 | 80 |
| 命中原帖主说喜欢 / 想试的游戏（款） | 2 | 4 |
| 有正面反馈的请求里命中至少一款 | 2/7 | 3/7 |
| 推荐了原帖主拒绝或已玩过的（款） | 0 | 1 |
| 命中社区最多人推荐的游戏（款） | 6（15 条请求） | 16（15 条请求） |
| 违反硬条件（按知识库判 FAIL） | 0 | 10 |
| 无法判断（UNKNOWN） | 0 | 0 |
| 不在核心库 / 认不出的名字 | 0 | 0 |
| 盲评平均分（0~2，补充参考） | 0.91 | 1.86 |
| 盲评 2 分占比 | 0.3 | 0.86 |

## 场景二：一起玩

| 指标 | 系统 | 直接问 LLM |
|---|---|---|
| 推荐的游戏数 | 75 | 80 |
| 命中原帖主说喜欢 / 想试的游戏（款） | 1 | 0 |
| 有正面反馈的请求里命中至少一款 | 1/6 | 0/6 |
| 推荐了原帖主拒绝或已玩过的（款） | 2 | 3 |
| 命中社区最多人推荐的游戏（款） | 7（16 条请求） | 22（16 条请求） |
| 违反硬条件（按知识库判 FAIL） | 0 | 11 |
| 无法判断（UNKNOWN） | 0 | 3 |
| 不在核心库 / 认不出的名字 | 0 | 3 |
| 盲评平均分（0~2，补充参考） | 0.79 | 1.83 |
| 盲评 2 分占比 | 0.21 | 0.83 |

## 耗时与解释一致性

- 需求理解（LLM）中位 12.3 秒；规则 + 打分 + 排序 + 卡片中位 0.53 秒；推荐理由（LLM，结果出来后再补）中位 16.9 秒；直接问 LLM 中位 18.1 秒。
- LLM 理由通过事实校验的比例：155/155（不通过的改用模板理由）。
- 需求理解失败（LLM 两次都没给出有效 JSON）：0 条；系统没给出推荐的：1 条。

## 逐条

| id | 场景 | 系统推荐 | 直接问 LLM | 正面反馈 | 系统违规 | LLM 违规 |
|---|---|---|---|---|---|---|
| r01 | 1 | Don't Starve Together、Baldur's Gate 3、DAVE THE DIVER、The Sims™ 4、Among Us | Medieval Dynasty、Necesse、Core Keeper、No Place Like Home、Slime Rancher | 3 | — | — |
| r02 | 1 | Celeste、Outer Wilds、TUNIC、Dead Cells、Ori and the Will of the Wisps | Ori and the Will of the Wisps、Hyper Light Drifter、Environmental Station Alpha、Prince of Persia The Lost Crown、Celeste | 0 | — | — |
| r03 | 1 | Factorio、The Planet Crafter、Dyson Sphere Program、SteamWorld Build、Oxygen Not Included | Dyson Sphere Program、The Planet Crafter、shapez 2、Techtonica、ASTRONEER | 0 | — | shapez 2 - Factory（机制组合：基地建设 + 资源管理 都是核心标签）；ASTRONEER（机制组合：基地建设 + 资源管理 都是核心标签） |
| r04 | 1 | Arco、Hero of the Kingdom、Oxenfree、Haven、The Witcher: Enhanced Edition Director's Cut | Portal 2、Undertale、Fallout: New Vegas、STAR WARS™ - Knights of the Old Republic™、OneShot | 1 | — | — |
| r05 | 1 | Cyberpunk 2077、Terraria、Vampire Survivors、Black Myth: Wukong、Stardew Valley | Factorio、Risk of Rain 2、Dead Cells、Monster Hunter: World、Vampire Survivors | 1 | — | Factorio（种子或已玩过） |
| r06 | 1 | INSIDE、Life is Strange - Episode 1、GRIS、To the Moon、Outer Wilds | Gone Home、Before Your Eyes、Oxenfree、The Vanishing of Ethan Carter、Outer Wilds | 4 | — | — |
| r07 | 1 | Counter-Strike 2、Terraria、Garry's Mod、Unturned、Satisfactory | RimWorld、Valheim、Factorio、Medieval Dynasty、Subnautica | 1 | — | — |
| r08 | 1 | Terraria、Virtual Cottage、Outpath、Wylde Flowers、Minami Lane | Graveyard Keeper、My Time at Sandrock、Medieval Dynasty、Core Keeper、Rune Factory 4 Special | 0 | — | — |
| r09 | 2 | Split Fiction、Human Fall Flat、Sid Meier’s Civilization® VI、Overcooked、Axis & Allies 1942 Online | Unravel Two、Haven、Spiritfarer: Farewell Edition、Brothers: A Tale of Two Sons Remake、Baldur's Gate 3 | 4 | — | — |
| r10 | 2 | Don't Starve Together、Tom Clancy's Rainbow Six Siege、Stardew Valley、Unturned、Dead by Daylight | PlateUp!、Lovers in a Dangerous Spacetime、Deep Rock Galactic、HELLDIVERS™ Dive Harder Edition、Unrailed! | 1 | — | — |
| r11 | 2 | United heist、Rail Route、Portal 2、TerraScape、Escape Academy | It Takes Two、Roots of Pacha、Raft、ASTRONEER、Portal 2 | 0 | — | — |
| r12 | 2 | Bang-On Balls: Chronicles、House Flipper 2、KarmaZoo、Luma Island、Party Animals | PICO PARK、Wobbly Life、Bloons TD 6、Human Fall Flat、Golf With Your Friends | 0 | — | Golf With Your Friends（在线组队：没有在线合作模式（Steam 分类）） |
| r13 | 2 | — | Stick Fight: The Game、Terraria、Castle Crashers、Broforce、Golf With Your Friends | 0 | — | — |
| r14 | 2 | Stardew Valley、Among Us、Raft、Pummel Party、Escape Simulator | Terraria、Core Keeper、Stardew Valley、Necesse、Factorio | 0 | — | — |
| r15 | 2 | Terraria、Risk of Rain 2、HELLDIVERS™ 2、Left 4 Dead 2、Castle Crashers® | Left 4 Dead 2、Risk of Rain Returns、Heroes of Hammerwatch、Castle Crashers、Streets of Rogue | 2 | — | — |
| r16 | 2 | Terraria、Raft、Among Us、Teardown、KILL IT WITH FIRE! 2 | Raft、Core Keeper、Enshrouded、Terraria、Sun Haven | 3 | — | — |
| r17 | 1 | The Chrono Jotter、Class of '09、Hakuoki: Kyoto Winds、Tomorrow's Love Puzzle、When The Past Was Around | VA-11 Hall-A: Cyberpunk Bartender Action、OPUS: Echo of Starsong - Full Bloom Edition、Oxenfree、Slay the Princess、I Was a Teenage Exocolonist | 0 | — | — |
| r18 | 1 | Valheim、Medieval Dynasty、I Am Future: Cozy Apocalypse Survival、V Rising、Above Snakes | Conan Exiles、Medieval Dynasty、Soulmask、Bellwright、ASKA | 2 | — | Conan Exiles Enhanced（机制组合：生存 + 基地建设 都是核心标签）；Bellwright（机制组合：生存 + 基地建设 都是核心标签） |
| r19 | 1 | Total War: WARHAMMER II、Kind Words (lo fi chill beats to write to)、RimWorld、klocki、House Flipper 2 | Romancing SaGa 2: Revenge of the Seven、Diplomacy is Not an Option、FINAL FANTASY XII THE ZODIAC AGE、Age of Wonders 4、Earth Defense Force 5 | 0 | — | — |
| r20 | 1 | Our Adventurer Guild、Slipways、Hexarchy、Shadow Empire、Terraformers | The Battle of Polytopia、Terraformers、Slipways、Ozymandias: Bronze Age Empire Sim、Terra Nil | 0 | — | The Battle of Polytopia（机制组合：回合战略 + 管理 都是核心标签）；Terra Nil（机制组合：回合战略 + 管理 都是核心标签） |
| r21 | 1 | Dungeon Munchies、Immortal Life、Kitaria Fables、Papa's Pizzeria Deluxe、Saleblazers | Cuisineer、Battle Chef Brigade Deluxe、Rune Factory 4 Special、Moonlighter、Kitaria Fables | 0 | — | Cuisineer（机制组合：动作 + 烹饪 都是核心标签）；Rune Factory 4 Special（机制组合：动作 + 烹饪 都是核心标签）；Moonlighter（机制组合：动作 + 烹饪 都是核心标签） |
| r22 | 1 | Slay the Spire、Baldur's Gate 3、Vampire Survivors、Stardew Valley、The Binding of Isaac: Rebirth | Luck be a Landlord、Slice & Dice、Peglin、Monster Train、Dicey Dungeons | 0 | — | — |
| r23 | 1 | Cities: Skylines、Manor Lords、Valheim、Stardew Valley、Mount & Blade II: Bannerlord | Manor Lords、Foundation、Banished、Ostriv、Dawn of Man | 1 | — | — |
| r24 | 1 | Minds Beneath Us、沉睡的法则 Things as They Are、MiSide、Spiritfarer®: Farewell Edition、Knell of St. Godhrkar | DAVE THE DIVER、DREDGE、Stray、Subnautica、Persona 5 Royal | 0 | — | — |
| r25 | 2 | Stardew Valley、Terraria、Deep Rock Galactic、Vampire Survivors、It Takes Two | Raft、Nobody Saves the World、Dinkum、Ship of Fools、Grounded | 1 | — | — |
| r26 | 2 | Alien Swarm: Reactive Drop、KILL IT WITH FIRE! 2、Minion Masters、Teenage Mutant Ninja Turtles: Splintered Fate、PULSAR: Lost Colony | Left 4 Dead 2、Legion TD 2 - Multiplayer Tower Defense、Deep Rock Galactic、Age of Empires II: Definitive Edition、HELLDIVERS™ 2 | 1 | — | — |
| r27 | 2 | Fall Guys、Gang Beasts、Hello Kitty Island Adventure、Golf With Your Friends、My Friend Peppa Pig | Party Animals、Cake Bash、Boomerang Fu、Moving Out 2、Sackboy: A Big Adventure | 0 | — | Party Animals（种子或已玩过） |
| r28 | 2 | Travellers Rest、Old Market Simulator、ContractVille、Farm Together 2、Go-Go Town! | Roots of Pacha、Fae Farm、Sun Haven、Spiritfarer: Farewell Edition、Dinkum | 0 | — | Roots of Pacha（机制组合：生活模拟 + 管理 都是核心标签）；Fae Farm（机制组合：生活模拟 + 管理 都是核心标签）；Sun Haven（机制组合：生活模拟 + 管理 都是核心标签）；Spiritfarer®: Farewell Edition（机制组合：生活模拟 + 管理 都是核心标签、在线组队：没有在线合作模式（Stea）；Dinkum（机制组合：生活模拟 + 管理 都是核心标签） |
| r29 | 2 | Subnautica、Valheim、ASTRONEER、V Rising、Enshrouded | ASTRONEER、Satisfactory、Raft、Grounded、No Man's Sky | 0 | — | Satisfactory（机制组合：探索 + 基地建设 都是核心标签）；Raft（机制组合：探索 + 基地建设 都是核心标签）；Grounded（机制组合：探索 + 基地建设 都是核心标签）；No Man's Sky（机制组合：探索 + 基地建设 都是核心标签） |
| r30 | 2 | Factorio、Deep Rock Galactic、HELLDIVERS™ 2、No Man's Sky、Valheim | Factorio、Baldur's Gate 3、Stardew Valley、ASTRONEER、For The King | 0 | — | — |
| r31 | 2 | Altitude、DG2: Defense Grid 2、Faeria、Songs of Silence、ShellShock Live | Deep Rock Galactic、Mechabellum、Risk of Rain 2、Northgard、Warhammer: Vermintide 2 | 0 | — | — |
| r32 | 2 | Wobbly Life、Overcooked! 2、Ultimate Chicken Horse、Pummel Party、Stardew Valley | Boomerang Fu、Overcooked! 2、Gang Beasts、Ultimate Chicken Horse、Teenage Mutant Ninja Turtles: Shredder's Revenge | 0 | — | — |
