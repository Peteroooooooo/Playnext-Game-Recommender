"""All tunable parameters in one place (design 10.4). Values marked "tuned" come from scripts/eval_fusion.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
DER = ROOT / "data" / "derived"
CACHE = ROOT / ".cache"
DESC_EMB = DER / "desc_emb_qwen3_4b.npz"   # scripts/build_desc_embeddings.py; offline evaluations only (kb.DenseKB)
# The service reads only each game's top-K co-like neighbours (scripts/build_neighbors.py), not the dense EASE matrix
# (design 10.16). K = 200: scripts/eval_slim.py, held-out Recall@20 within +-0.005 of the full tables for library /
# 1 seed / 2 seeds, also with the pool cut to online co-op games.
NEIGHBORS_K = 200
NEIGHBORS = DER / f"neighbors_k{NEIGHBORS_K}.npz"

# Step 3 fusion: convex weights of the min-max normalised anchor channels (design 5.5, 10.18). The held-out reviewer
# test (scripts/eval_fusion.py, 2026-10-14) favours co-like at any content share, but it asks "what else did X's fans
# like", the question co-like is built on, so it cannot judge "is it like X". 2026-10-23, 60 seeds with the seed
# rerank, blind judge of another family (0-2): tag 0.05 1.57, 0.20 1.63, 0.35 1.63, 0.50 1.64 (each vs 0.05 +0.05 to
# +0.07, CI above 0, tied with each other). Library only (no rerank; scripts/eval_library_tag.py, 31 made-up
# libraries, same judge): tag 0.20 1.00, 0.30 1.14, 0.40 1.28; second round (judge also penalising weak games) 0.40
# 1.20, 0.50 1.36, 0.60 1.46, 0.70 1.52, 0.80 1.51, and picks with no tag overlap with the library (CS2 for a sandbox
# library) 4 / 1 / 0 / 0 / 0 of 155. Seeds with rerank, same round: 0.40-0.70 all 1.48-1.49 (within +-0.04), 0.80 1.46.
# So 0.70: best for libraries, no cost for seeds. The description-similarity channel (share 0.05 1.62, 0 1.59, 0.20
# 1.58, not shown to help) was set to 0 and then removed (design 10.18). Lineage only feeds cards unless the user asks
# for the same studio (SAME_STUDIO_W).
WEIGHTS = {"tag": 0.70, "colike": 0.30, "lineage": 0.0}
# "geometric": tag^0.7 x co-like^0.3, so a game needs both (design 10.18). 2026-10-23, same blind judge, linear vs
# geometric: libraries lin 0.70 1.52 / geo 0.70 1.50 (tied), picks with no co-like support 9 vs 0 of 155; seeds
# (rerank) lin 0.70 1.43 / geo 0.70 1.46, no co-like support 76 vs 45 of 300. Tag exponent, one round each:
# libraries 0.40 1.29, 0.60 1.48, 0.70 1.56, 0.80 1.60 (tied); seeds (gemini-3.8-flash-high) 0.40 1.38, 0.50 1.41,
# 0.60 1.39, 0.70 1.42 (others -0.01 to -0.04, CI across 0). So 0.70. "linear": the weighted sum.
FUSION = "geometric"
FUSION_EPS = 0.01        # geometric only: floor added before the log, so a zero channel is low but not -inf
SAME_STUDIO_W = 0.15
TAG_AGG = "sum"          # multi-anchor aggregation: "sum" beat "max" offline
LINEAGE_PARTS = ("dev", "ser", "sim")   # same developer, same series, IGDB similar
MAX_LIBRARY_ANCHORS = 50  # strongest library anchors by playtime percentile
FEEL_W = 0.25            # feel channel share when feel_tags are given
# The "sentence vs game descriptions" channel (Qwen3-Embedding-4B query encoder, share 0.25) was removed on
# 2026-10-23 (design 10.15): paired request-set judge 1.650 with it, 1.647 without, so the service needs no GPU.
SEED_POOL, LIB_BONUS = 50, 0.2   # design 4.1: with explicit seeds the library re-ranks only the seed's top 50
RERANK = True            # LLM semantic rerank when the request has preference words (design 5.5)
RERANK_N, RERANK_EXTRA = 80, 10  # top-N by fused score + best N by the sentence / feel channels alone; 80 covers
                                  # 62 of the 153 community / poster-named games in the request set, 40 only 43
RERANK_W = 0.7           # w_r: share of the rerank score after fusion; the fused score also decides which 80 games
                         # get reranked. 2026-10-23 (scripts/eval_rerank_weight.py, one LLM rerank per request re-fused
                         # at each w_r, blind judge of another family, 0-2), 0.9 / 0.7 / 0.5 / 0.3 and 0.9 rerun:
                         # 60 seeds 1.60 / 1.59 / 1.52 / 1.40 / 1.60, no co-like support 44 / 27 / 20 / 12 / 41 of 300;
                         # 31 sentences 1.80 / 1.78 / 1.68 / 1.54 / 1.81; the same with a library 1.43 / 1.41 / 1.40 /
                         # 1.34 / 1.41. 0.7 is within the rerun noise everywhere and has fewer picks without co-like
                         # support; 0.5 is worse (CI below 0). Earlier 0.9 (2026-10-16, 16 request-set posts) was
                         # changed together with RERANK_GAME_NAMES, so it never isolated w_r.
RERANK_SEEDS = True      # "games like X" without words: rerank against X's store facts (design 10.18). 2026-10-23,
                         # 60 seeds, blind judge of another family (0-2): 0.61 -> 1.68, better on 60 / 60; ~6-10 s
RERANK_GAME_NAMES = True # append the mentioned games' English store names to the rerank query (rerank.with_game_names)
RERANK_BATCHES = 1       # > 1: candidates split into this many parallel calls, raw scores kept (per-batch min-max,
                         # z-score and anchor calibration all drifted more). 2026-10-22, 29 request-set posts, no
                         # thinking: 1 batch 7.2 s, top 5 vs the old full call 3.38 / 5; 8 batches 4.5 s, 3.10 / 5
                         # (the same full call run twice: 3.55 / 5). 1 kept: 3 s is not worth the extra drift.

# Generative LLM thinking per call purpose (llm.LLM.chat): a reasoning_effort value ("none" / "low" / ...) or None
# for the model's own default. 2026-10-22 (scripts/eval_thinking.py, eval_rerank_speed.py, request-set posts):
# without thinking the parse matches the per-post gold as well as before (people 28/30, budget 32/32, played /
# excluded 120 vs 121 of 138; the default run twice also differs by one) in 4.2 s instead of 11.9 s; rerank 7.2 s
# instead of 31 s with top 5 within the model's own run-to-run noise; reasons 160 / 160 pass the fact check in
# 5.7 s instead of 15.6 s. Purposes not listed use the default.
THINKING = {"understand": "none", "patch": "none", "rerank": "none", "reasons": "none"}

# Step 4 ranking (design 5.5)
DELTA = 0.10
SHORTLIST = 20
PICK = 5
UNKNOWN_SHOW = 6         # "待确认" games shown as posters in the near-miss row (was 2 as a text list, 2026-10-23)
RATING_FLOOR = 70
ALPHA, BETA = 6.69, 1.43  # smoothed-rating Beta prior: kb.fit_beta_prior() (moments) on 7,298 core games, 2026-10-16
BASE_W = {"relevance": 0.5, "quality": 0.3, "price": 0.2}
MMR_LAMBDA = 0.65
NEAR_LOW = 1.05          # current price <= record low x 1.05 counts as "at the record low"
PREFER_OWNED_W = 0.2     # window term for library_policy = prefer_owned
SHORT_W = 0.2            # window term for "short game" (IGDB time to beat)
CHEAP_ZERO = {"CN": 200, "US": 30}   # price_intent "cheap": price score falls linearly from free (1) to this (0)
FAILED_SHOW = 8          # "没通过的" list: best-liked games that broke a hard rule
# ... but only when they are a little off (pipeline._is_near; 2026-10-23, the user: a stated 同屏 request must not
# list online-only games as "差一点"). A stated setup / interaction the game lacks never counts.
NEAR_PLAYERS_SHORT = 2   # player limit at most this many seats short of the party
NEAR_BUDGET_X = 1.5      # price at most this multiple of the budget

# Slow loop (design 5.3 Step 6): card feedback saved per bound account, liked games decay as anchors
LIKED_HALF_LIFE_DAYS = 180

# Scenario 2 group aggregation (design 5.5)
GROUP_MEAN_W, GROUP_MIN_W = 0.6, 0.4
NASH_EPS = 0.01
GROUP_METHOD = "mean_min"  # "mean_min" | "nash" | "lexmin"
SHARED_W = 0.5

# Library rule (design 4.1)
CORE_TAG_SHARE = 0.5

HOME_ART_COUNT = 200      # home-screen backdrop: most-reviewed core games with hero art (scripts/build_home_art.py)
