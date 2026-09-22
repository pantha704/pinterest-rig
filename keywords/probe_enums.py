#!/usr/bin/env python3
"""Probe helper: learn the trendsPreset / rankingMethod / lookbackWindow enums empirically.
Polite: sequential, 4s gaps, tiny payloads."""
import json, time, urllib.request, urllib.parse, os

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://trends.pinterest.com"
HDRS = {"User-Agent": UA, "Accept": "application/json",
        "Referer": "https://trends.pinterest.com/"}
DELAY = 4.0
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_reqcount.txt")


def bump(n=1):
    c = 0
    if os.path.exists(STATE):
        try:
            c = int(open(STATE).read().strip() or 0)
        except ValueError:
            c = 0
    c += n
    open(STATE, "w").write(str(c))
    return c


def get(path, params, tries=1):
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    for attempt in range(tries):
        req = urllib.request.Request(url, headers=HDRS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            bump()
            return r.status, body
        except urllib.error.HTTPError as e:
            bump()
            return e.code, e.read().decode("utf-8", "replace")[:400]
        except Exception as e:  # noqa
            bump()
            return -1, str(e)[:200]
    return -1, "exhausted"


def top(path, params, n=3):
    st, body = get(path, params)
    try:
        j = json.loads(body)
        vals = j.get("values", j) if isinstance(j, dict) else j
        terms = [v.get("term") for v in vals][:n]
    except Exception:
        terms = body[:120]
    return st, terms


if __name__ == "__main__":
    END = "2026-09-18"
    print("== trendsPreset sweep (lookbackWindow=2, rankingMethod=3, US) ==")
    for p in (1, 2, 3, 4, 5):
        st, t = top("/top_trends_filtered/",
                    {"lookbackWindow": 2, "endDate": END, "rankingMethod": 3,
                     "country": "US", "trendsPreset": p, "numTermsToReturn": 5})
        print(f"  preset={p} -> {st} {t}")
        time.sleep(DELAY)
    print("== rankingMethod sweep (trendsPreset=3, lookbackWindow=2, US) ==")
    for rm in (1, 2, 3, 4):
        st, t = top("/top_trends_filtered/",
                    {"lookbackWindow": 2, "endDate": END, "rankingMethod": rm,
                     "country": "US", "trendsPreset": 3, "numTermsToReturn": 5})
        print(f"  rank={rm} -> {st} {t}")
        time.sleep(DELAY)
    print("== lookbackWindow sweep (trendsPreset=3, rankingMethod=3, US) ==")
    for lb in (1, 2, 3, 4, 5):
        st, t = top("/top_trends_filtered/",
                    {"lookbackWindow": lb, "endDate": END, "rankingMethod": 3,
                     "country": "US", "trendsPreset": 3, "numTermsToReturn": 5})
        print(f"  lookback={lb} -> {st} {t}")
        time.sleep(DELAY)
    print("== endDate check (today vs app date) ==")
    for ed in ("2026-09-22", "2026-09-19", "2026-09-18", "2026-09-17"):
        st, t = top("/top_trends_filtered/",
                    {"lookbackWindow": 2, "endDate": ed, "rankingMethod": 3,
                     "country": "US", "trendsPreset": 3, "numTermsToReturn": 3})
        print(f"  endDate={ed} -> {st} {t}")
        time.sleep(DELAY)
    print("total requests this run:", open(STATE).read().strip())
