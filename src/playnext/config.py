"""All tunable parameters in one place (design 10.4). Values marked "tuned" come from scripts/eval_fusion.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
DER = ROOT / "data" / "derived"
CACHE = ROOT / ".cache"
DESC_EMB = DER / "desc_emb_qwen3_4b.npz"
EMB_MODEL = CACHE / "models" / "Qwen3-Embedding-4B"
QUERY_PROMPT = "Instruct: Given what a player says they want, retrieve games whose store description matches it\nQuery: "

# Step 3 fusion: convex weights of the min-max normalised anchor channels (design 5.5). Tuned 2026-10-14 by
# scripts/eval_fusion.py: co-like alone is best offline; 0.05 + 0.05 of tag / description costs <= 0.005 Recall@20
# and keeps a content signal for ties and for games without co-like data. Lineage as a score lowers recall at every
# weight tried, so it only feeds cards, unless the user asks for the same studio (SAME_STUDIO_W).
WEIGHTS = {"tag": 0.05, "desc": 0.05, "colike": 0.90, "lineage": 0.0}
SAME_STUDIO_W = 0.15
TAG_AGG = "sum"          # multi-anchor aggregation: "sum" beat "max" for both tag and description offline
DESC_AGG = "sum"
LINEAGE_PARTS = ("dev", "ser", "sim")   # same developer, same series, IGDB similar
MAX_LIBRARY_ANCHORS = 50  # strongest library anchors by playtime percentile
FEEL_W = 0.25            # feel channel share when feel_tags are given
PREF_W = 0.25            # preference sentence vs game descriptions: own share, like the feel channel
SEED_POOL, LIB_BONUS = 50, 0.2   # design 4.1: with explicit seeds the library re-ranks only the seed's top 50
RERANK = True            # LLM semantic rerank when the request has preference words (design 5.5)
RERANK_N, RERANK_EXTRA = 80, 10  # top-N by fused score + best N by the sentence / feel channels alone; 80 covers
                                  # 62 of the 153 community / poster-named games in the request set, 40 only 43
RERANK_W = 0.6           # w_r: share of the rerank score after fusion

# Step 4 ranking (design 5.5)
DELTA = 0.10
SHORTLIST = 20
PICK = 5
UNKNOWN_SHOW = 2
RATING_FLOOR = 70
ALPHA, BETA = 24.6, 5.4  # Beta prior of the smoothed rating; refit by fit_beta_prior()
BASE_W = {"relevance": 0.5, "quality": 0.3, "price": 0.2}
MMR_LAMBDA = 0.65
NEAR_LOW = 1.05          # current price <= record low x 1.05 counts as "at the record low"
PREFER_OWNED_W = 0.2     # window term for library_policy = prefer_owned
SHORT_W = 0.2            # window term for "short game" (IGDB time to beat)

# Scenario 2 group aggregation (design 5.5)
GROUP_MEAN_W, GROUP_MIN_W = 0.6, 0.4
NASH_EPS = 0.01
GROUP_METHOD = "mean_min"  # "mean_min" | "nash" | "lexmin"
SHARED_W = 0.5

# Library rule (design 4.1)
CORE_TAG_SHARE = 0.5
