# Playnext-Game-Recommender

Context-aware Steam game recommender (NUS-ISS group project "Backlog Breaker").
Design document: [docs/Core_Technical_Skeleton.md](docs/Core_Technical_Skeleton.md).

## Setup

- Python 3.12 with pandas, pyarrow, numpy, scipy.
- Create `.env` in the repo root (never committed):

  ```
  STEAM_API_KEY=...
  TWITCH_CLIENT_ID=...
  TWITCH_CLIENT_SECRET=...
  ITAD_API_KEY=...
  ```

  The Twitch access token for IGDB is fetched automatically and cached in `.cache/`.
- `python scripts/check_keys.py` checks all three keys.

## Data pipeline

Run from the repo root, in order. Every step caches its raw pulls under `data/raw/`,
so re-running skips what is already there. `data/` and `.cache/` are git-ignored.

| Step | Script | Output |
|---|---|---|
| 1 | `fetch_core_list.py` | `data/core_candidates.json` — games with >= 1,000 Steam reviews (SteamSpy, 1 page / min) |
| 2 | `fetch_steam_items.py` | `data/raw/steam_items/` — tags, categories, reviews, CN/US prices, descriptions (EN/ZH), ratings |
| 3 | `fetch_igdb.py` | `data/raw/igdb/` — player counts, series, companies, similar games, time to beat |
| 4 | `fetch_itad.py` | `data/raw/itad/` — Steam-store historical lows for CN and US |
| 5 | download Kaggle "Game Recommendations on Steam" to `data/raw/kaggle_recs/archive.zip` | — |
| 6 | `build_colike_kaggle.py` | `data/derived/colike_kaggle.parquet`, `eval_kaggle_test.parquet` |
| 7 | `fetch_appreviews.py trial` (optional, not used) | `data/raw/appreviews/` — recent positive reviews, reviewer IDs salted-hashed. Trial showed the co-like signal is too sparse; new games use IGDB similar games instead. Single connection only (parallel requests get HTTP 429). |
| 8 | `build_processed.py` | `data/processed/*.parquet` — normalised tables |

Diagnostics: `kaggle_stats.py`, `kaggle_coverage.py`, `igdb_mp_coverage.py`, `desc_player_count.py`.

Data sources: Steam store and review endpoints, Steam Web API, IGDB (non-commercial use),
IsThereAnyDeal, Kaggle dataset by Anton Kozyriev (CC0). Price data courtesy of IsThereAnyDeal.
