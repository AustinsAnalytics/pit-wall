"""Download NASCAR Cup Series race lists and per-race results (Next Gen era, 2022-2026) from NASCAR's public feeds.

    python pipeline/fetch.py        -> data/raw/race_list_{year}.json, data/raw/weekend/{race_id}.json
Skips files it already has; spaces requests out politely.
"""
import json
import time
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
YEARS = range(2022, 2027)
UA = {"User-Agent": "pit-wall research script (personal, non-commercial)"}


def get(url):
    for i in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            print("retry", url, e)
            time.sleep(3 * (i + 1))
    raise RuntimeError(url)


def main():
    (RAW / "weekend").mkdir(parents=True, exist_ok=True)
    for y in YEARS:
        f = RAW / f"race_list_{y}.json"
        if not f.exists():
            f.write_bytes(get(f"https://cf.nascar.com/cacher/{y}/race_list_basic.json"))
        races = [r for r in json.loads(f.read_text())["series_1"]]
        done = 0
        for r in races:
            out = RAW / "weekend" / f"{r['race_id']}.json"
            if out.exists():
                continue
            body = get(f"https://cf.nascar.com/cacher/{y}/1/{r['race_id']}/weekend-feed.json")
            out.write_bytes(body)
            done += 1
            time.sleep(0.3)
        print(y, len(races), "races listed,", done, "downloaded")


if __name__ == "__main__":
    main()
