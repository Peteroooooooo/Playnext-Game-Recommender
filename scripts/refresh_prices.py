"""Refresh the daily price snapshot (design 4.6 "价格时效"): current Steam price and ITAD Steam-store low for every
core game, per region (src/playnext/refresh.py).

Usage:
  uv run python scripts/refresh_prices.py                 # CN and US; replaces data/processed/prices.parquet if the
                                                          # check passes, old file kept as prices_backup_<date>.parquet
  uv run python scripts/refresh_prices.py --regions CN    # other regions keep their rows
  uv run python scripts/refresh_prices.py --dry-run       # new snapshot to a temp file, prints the comparison;
                                                          # the live file is not touched
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import refresh  # noqa: E402


def show(res):
    print(f"status: {res['status']}  ({res.get('seconds')} s)")
    old, new = res.get("old_snapshot"), res.get("new_snapshot")
    if old:
        print(f"old snapshot: {old['snapshot_date']} (from {old['source']}; regions {old.get('regions') or 'all at once'})")
    if new:
        print(f"new snapshot: {new['snapshot_date']} {new['regions']}")
    if res.get("requests"):
        print(f"requests: {res['requests']}")
    for r, rep in (res.get("check") or {}).items():
        print(f"\n[{r}] currency {rep.get('currency')}; Steam items {rep.get('steam_items')}; "
              f"store says not sold in this region {rep.get('cn_store_blocked')}; "
              f"prices with another currency symbol {rep.get('wrong_symbol')}; ITAD low currencies {rep.get('low_currencies')}")
        for k in ("old", "new"):
            if k in rep:
                s = rep[k]
                print(f"  {k}: rows {s['rows']:,}, with price {s['priced']:.1%}, free {s['free']:,}, "
                      f"with record low {s['low']:.1%}, discounted {s['discounted']:,}")
        c = (res.get("comparison") or {}).get(r)
        if c:
            print(f"  price changed {c['price_changed']:,} of {c['both_priced']:,} priced in both "
                  f"(cheaper {c['cheaper']:,}, dearer {c['dearer']:,}); price appeared {c['price_appeared']}, gone {c['price_gone']}; "
                  f"discount changed {c['discount_changed']:,} (discounted {c['discounted_before']:,} -> {c['discounted_now']:,}); "
                  f"new record lows {c['new_record_low']:,}; low appeared {c['low_appeared']}, gone {c['low_gone']}")
            for e in c["examples"]:
                print(f"    {e['appid']:>8} {str(e['name'])[:40]:<40} {e['old']:>8.2f} -> {e['new']:>8.2f} "
                      f"(-{e['discount_old']}% -> -{e['discount_new']}%)")
    for p in res.get("problems") or []:
        print(f"problem: {p}")
    if res.get("error"):
        print(f"error: {res['error']}")
    if res.get("backup"):
        print(f"backup: {res['backup']}")
    print(f"target: {res.get('target')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default="CN,US")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="also print the full result as JSON")
    a = ap.parse_args()
    regions = [r.strip().upper() for r in a.regions.split(",") if r.strip()]
    out = Path(tempfile.gettempdir()) / "playnext_prices_dryrun.parquet" if a.dry_run else None
    try:
        res = refresh.refresh_prices(regions, out=out)
    except Exception as e:  # unexpected failure: show it without any URL / key
        print(f"failed: {refresh._scrub(f'{type(e).__name__}: {e}')}")
        sys.exit(2)
    show(res)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    sys.exit(0 if res["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
