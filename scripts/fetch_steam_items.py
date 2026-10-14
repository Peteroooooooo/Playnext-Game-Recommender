"""Fetch Steam store data for the core library via IStoreBrowseService/GetItems.

Three passes, cached per batch under data/raw/steam_items/:
  cn_en : CN prices + English text + tags, categories, reviews, platforms,
          release, ratings / content descriptors, languages, full description
  cn_zh : Simplified Chinese short + full description
  us    : US prices (comparison region)
  us_en / us_zh : the cn_en / cn_zh requests against the US store, only for games the CN store does not sell
Also saves the tag list in English and Simplified Chinese.
Usage: python scripts/fetch_steam_items.py
"""
import json
import time
import urllib.parse

from check_keys import ROOT, request

CORE = ROOT / "data" / "core_candidates.json"
RAW = ROOT / "data" / "raw" / "steam_items"
BATCH = 100

PASSES = {
    "cn_en": ({"language": "english", "country_code": "CN"},
              {"include_basic_info": True, "include_tag_count": 20, "include_reviews": True,
               "include_all_purchase_options": True, "include_platforms": True, "include_release": True,
               "include_ratings": True, "include_supported_languages": True, "include_full_description": True}),
    "cn_zh": ({"language": "schinese", "country_code": "CN"},
              {"include_basic_info": True, "include_full_description": True}),
    "us": ({"language": "english", "country_code": "US"},
           {"include_all_purchase_options": True}),
}
# Games the CN store does not sell (unvailable_for_country_restriction) only get basic fields in the CN passes;
# these two passes fetch the same data from the US store for just those games.
BACKFILL = {
    "us_en": ({"language": "english", "country_code": "US"}, PASSES["cn_en"][1]),
    "us_zh": ({"language": "schinese", "country_code": "US"}, PASSES["cn_zh"][1]),
}


def cn_blocked():
    out = []
    for f in sorted(RAW.glob("cn_en_*.json")):
        out += [it["appid"] for it in json.loads(f.read_text(encoding="utf-8"))
                if it.get("appid") and it.get("unvailable_for_country_restriction")]
    return out


def get_items(appids, context, data_request):
    inp = {"ids": [{"appid": a} for a in appids], "context": {**context, "steam_realm": 1},
           "data_request": data_request}
    url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=" + urllib.parse.quote(json.dumps(inp))
    for attempt in range(4):
        st, d = request(url)
        if st == 200:
            return d["response"].get("store_items", [])
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GetItems failed: HTTP {st} {str(d)[:120]}")


def main():
    appids = [g["appid"] for g in json.loads(CORE.read_text(encoding="utf-8"))]
    RAW.mkdir(parents=True, exist_ok=True)
    for name, (ctx, dr) in PASSES.items():
        n = 0
        for b, i in enumerate(range(0, len(appids), BATCH)):
            f = RAW / f"{name}_{b:03d}.json"
            if not f.exists():
                f.write_text(json.dumps(get_items(appids[i:i + BATCH], ctx, dr)), encoding="utf-8")
                time.sleep(0.5)
            n += len(json.loads(f.read_text(encoding="utf-8")))
        print(f"{name}: {n} items", flush=True)
    blocked = cn_blocked()
    for name, (ctx, dr) in BACKFILL.items():
        n = 0
        for b, i in enumerate(range(0, len(blocked), BATCH)):
            f = RAW / f"{name}_{b:03d}.json"
            if not f.exists():
                f.write_text(json.dumps(get_items(blocked[i:i + BATCH], ctx, dr)), encoding="utf-8")
                time.sleep(0.5)
            n += sum(1 for it in json.loads(f.read_text(encoding="utf-8")) if it.get("success") == 1)
        print(f"{name}: {n} of {len(blocked)} CN-blocked games returned", flush=True)
    for lang in ("english", "schinese"):
        st, d = request(f"https://api.steampowered.com/IStoreService/GetTagList/v1/?language={lang}")
        (RAW.parent / f"steam_tags_{lang}.json").write_text(json.dumps(d["response"]["tags"], ensure_ascii=False), encoding="utf-8")
        print(f"tags {lang}: {len(d['response']['tags'])}")


if __name__ == "__main__":
    main()
