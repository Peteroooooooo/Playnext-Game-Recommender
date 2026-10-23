# Playnext-Game-Recommender

Context-aware Steam game recommender (NUS-ISS group project "Backlog Breaker").
Try it: **https://playnext.peteroooooooo.com**
Design document: [docs/Core_Technical_Skeleton.md](docs/Core_Technical_Skeleton.md).

## Setup

- Install [uv](https://docs.astral.sh/uv/), then run `uv sync` in the repo root. It creates `.venv` with
  Python 3.12 and the exact versions in `uv.lock`. By default this includes the `models` group (CUDA torch on
  Windows / Linux, about 3 GB), which only the offline embedding build and some evaluations need; the web service
  runs without it, so a server only needs `uv sync --no-group models`.
  Run everything through `uv run`, e.g. `uv run python scripts/check_keys.py`.
- Create `.env` in the repo root (never committed):

  ```
  STEAM_API_KEY=...
  TWITCH_CLIENT_ID=...
  TWITCH_CLIENT_SECRET=...
  ITAD_API_KEY=...
  LLM_BASE_URL=...   # OpenAI-compatible endpoint, ending in /v1
  LLM_API_KEY=...
  LLM_MODEL=gemini-3.8-flash-anti
  PGHOST=127.0.0.1
  PGPORT=5432
  PGDATABASE=playnext
  PGUSER=playnext
  PGPASSWORD=...     # any local password
  ```

  The Twitch access token for IGDB is fetched automatically and cached in `.cache/`.
- `uv run python scripts/check_keys.py` checks the Steam, IGDB and ITAD keys.
- `docker compose up -d` starts the local PostgreSQL 16 (bound to 127.0.0.1, data in the `playnext-pgdata` volume).

## Data pipeline

Run from the repo root with `uv run python scripts/<script>`, in order. Every step caches its raw pulls under `data/raw/`,
so re-running skips what is already there. `data/` and `.cache/` are git-ignored.

| Step | Script | Output |
|---|---|---|
| 1 | `fetch_core_list.py` | `data/core_candidates.json` — games with >= 1,000 Steam reviews (SteamSpy, 1 page / min) |
| 2 | `fetch_steam_items.py` | `data/raw/steam_items/` — tags, categories, reviews, CN/US prices, descriptions (EN/ZH), ratings; US-store data for games the CN store does not sell |
| 3 | `fetch_igdb.py` | `data/raw/igdb/` — player counts, series, companies, similar games, time to beat |
| 4 | `fetch_itad.py` | `data/raw/itad/` — Steam-store historical lows for CN and US |
| 5 | `build_processed.py` | `data/processed/*.parquet` — normalised tables for the 7,304 core games; removed entries (software, redirects, demos, servers, prologues) in `excluded_apps.parquet` |
| 5a | `build_desc_embeddings.py` (about 20 min on a 16 GB GPU, cached per game) | `data/derived/desc_emb_qwen3_4b.npz` — EN and ZH description vectors (Qwen3-Embedding-4B in `.cache/models/`); offline evaluations only, the service does not use them |
| 5b | `build_aliases.py`, then `build_aliases.py test` | `data/processed/aliases.parquet` — store names plus common Chinese names from the LLM (replies cached in `.cache/alias_llm/`) |
| 5c | `build_tag_categories.py` | `data/processed/tag_categories.parquet` — the 446 tags as gameplay / theme / mood / other (LLM once, manual overrides in the script) |
| 5d | `build_app_index.py` | `data/processed/app_index.parquet` — AppID and name of every game on the Steam store (IStoreService/GetAppList) |
| daily | `refresh_prices.py [--dry-run]` (the API also runs it in the background when the snapshot is a day old) | `data/processed/prices.parquet` — CN / US prices and record lows, dated in the file's metadata; the old file is backed up; `build_processed.py` keeps a refreshed snapshot unless given `--rebuild-prices` |
| 6 | download Kaggle "steam-reviews-100m" (sergiodelcarpio, MIT) with `uvx --from kaggle==2.2.4 kaggle datasets download -d sergiodelcarpio/steam-reviews-100m` (11.9 GB zip; token in `~/.kaggle/access_token`) and extract it to `data/raw/kaggle_reviews100m/extracted/` | — |
| 7 | `fetch_reviews_increment.py plan`, `run 160`, then always `repair` | `data/raw/steam_reviews_increment/reviews/` — reviews after the Kaggle scrape and games Kaggle lacks; needs a local rotating SOCKS5 proxy (`PLAYNEXT_PROXY`, default `socks5h://127.0.0.1:17892`) |
| 8 | `fill_kaggle_gaps.py measure`, `nonsteam`, `steam` | `data/raw/steam_reviews_increment/kaggle_gaps/` — non-Steam-purchase reviews and the games Kaggle cut short |
| 9 | `build_reviews_merged.py` (about 18 min) | `data/derived/reviews_merged/` — 161M reviews deduplicated by review id |
| 10 | `build_review_tables.py` (about 2 min) | `data/derived/ease_reviews100m.npz`, `colike_reviews100m.parquet`, `playtime_reference_100m.parquet`, `eval_reviews100m_test.parquet` |
| 11 | `build_neighbors.py` (after 10) | `data/derived/neighbors_k200.npz` — each game's top 200 co-like neighbours (4.5 MB). The web service reads this instead of the dense EASE matrix and needs no description vectors, so a server needs only `data/processed/` (without price backups), this file, `colike_reviews100m.parquet` and `playtime_reference_100m.parquet` (about 44 MB) |

Reviewer Steam IDs are keyed-hashed in memory as soon as they are read and never written. The full review pipeline is
recorded in [docs/Review_Data_Pipeline.md](docs/Review_Data_Pipeline.md).

## The recommender (`src/playnext/`)

| Module | Design step |
|---|---|
| `understand.py`, `llm.py`, `aliases.py` | Step 1: request → SessionSpec (LLM + Pydantic), alias table; Step 6 follow-up patches |
| `spec.py` | SessionSpec, members, sites (who sits at which machine) |
| `library.py` | Paths A / B: Steam OpenID login or profile link → GetOwnedGames (SteamID never stored) |
| `rules.py` | Step 2: three-valued rules, multiplayer modes and player limits, who-buys plans, budget, region |
| `scoring.py` | Step 3: co-like (EASE), tag and feel channels; group aggregation |
| `ranking.py`, `pricing.py` | Step 4: series folding, live price re-check, rating floor, relevance window, MMR |
| `cards.py` | Step 5: evidence cards, setup cards, LLM reasons with fact check and template fallback |
| `rerank.py`, `local_rerank.py` | semantic rerank: one batched LLM call per request, a column per target (player, member, shared request); Qwen3-Reranker for comparison |
| `relax.py` | conflict analyser (subset-sum over failed relaxable rules) |
| `kb.py` | the knowledge base in memory: processed tables, co-like neighbours and description texts aligned with the core games |
| `outside.py` | games outside the core library: looked up in the light index, fetched once and used as tag-only taste anchors (no co-like); never recommended |
| `pipeline.py`, `api.py` | the trunk (including the "没通过的" list of near misses); FastAPI backend (also serves the built web app) |
| `db.py` | PostgreSQL knowledge base; recursive-CTE lineage paths, queried for the cards at request time |
| `profiles.py` | slow loop: card feedback per bound account (keyed hash only) and fact-error reports, in PostgreSQL |
| `refresh.py`, `appindex.py` | daily price snapshot refresh; light index of all Steam games |
| `config.py` | every weight and threshold |

Run it:

```
docker compose up -d                                   # optional: PostgreSQL, then scripts/load_postgres.py
npm --prefix web install && npm --prefix web run build # web app (see web/README.md)
uv run uvicorn --app-dir src playnext.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. On Windows, `pwsh -File scripts/serve.ps1` (or double-click `start.bat`) starts Docker and
the database, then the app on 127.0.0.1:8000.

The public site runs on a Linux server (aarch64 or x86-64, about 0.5 GB of memory). `pwsh -File scripts/deploy.ps1
[-Server <ssh host>] [-CopyEnv] [-SkipData] [-SkipWeb]` (or double-click `deploy.bat`) builds the web app, uploads the code and the tables from step 11 to `/opt/playnext`,
and runs `scripts/deploy/server.sh` there: `uv sync --no-default-groups`, a PostgreSQL 16 container bound to
127.0.0.1 (loaded on first run), and the systemd unit `scripts/deploy/playnext.service`, which listens on the
server's EasyTier address with `--proxy-headers` for the reverse proxy on a separate server that adds HTTPS and a
rate limit. `-CopyEnv` uploads `.env` (first deploy only); the server's `prices.parquet` is kept because the service
refreshes it daily. Logs: `journalctl -u playnext`. The app has no authentication of its own; expose it only through
such a proxy.
Card feedback of bound accounts is kept in PostgreSQL under a keyed hash; the key is generated once in
`.cache/profile_secret` (git-ignored; deleting it unlinks all saved feedback). Set `PLAYNEXT_NO_REFRESH=1` to skip the background price refresh. Command-line checks:
`scripts/try_request.py "<request>" ["<follow-up>"]` (full path with LLM and live prices), `scripts/smoke_pipeline.py`
(no LLM). Tests: `uv run pytest` (the PostgreSQL tests skip when the database is not loaded).

Offline evaluation: `eval_fusion.py` (channel weights), `eval_ranking_groups.py` (ranking rules, library bonus,
synthetic groups), `eval_extra.py` (mechanics combinations, price preference, rating smoothing, scoring latency),
`eval_request_set.py run|local|llm_named|sweep|judge|report` (32 real forum requests vs asking the LLM directly,
checked against hand-written conditions in `eval/request_set_gold.json`; reranker and w_r comparison on a dev / test
split; results in `eval/`), `eval_content_weight.py` (content share and tag gate on the held-out reviewers),
`eval_seed_rerank.py gen|sweep|report` ("games like X": with and without the seed rerank, and the stage-1 tag share
under the rerank; blind judge input in `eval/`), `eval_rerank_weight.py gen|regen|report` (rerank weight w_r on seed,
free-text and free-text + library requests). `simulate_inputs.py` runs the four input paths through the current
system; `explain_library_example.py` and `explain_request_example.py` record the examples of
`docs/pipeline_architecture.html`.
Earlier evaluation: `eval_ease.py [N] [M]`, `playtime_signal.py`, `demo_walkthrough.py`.
Diagnostics: `igdb_mp_coverage.py`, `rate_limit_probe.py`, `diagnose_short_games.py`, `diagnose_paging.py`,
`diagnose_empty_pages.py`, `probe_owned_games.py` (one Steam profile, counts only), `probe_owned_sample.py`
(GetOwnedGames privacy states on sampled reviewers, counts only).

Data sources: Steam store and review endpoints, Steam Web API, IGDB (non-commercial use),
IsThereAnyDeal, Kaggle "steam-reviews-100m" by sergiodelcarpio (MIT; co-like, playtime reference and evaluation).
Price data courtesy of IsThereAnyDeal.
