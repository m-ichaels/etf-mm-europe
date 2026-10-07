"""Yahoo chart-API loader.  Vendored from m-ichaels/delta-one-basis tools/download.py (see NOTICE).

yahoo_daily(symbol, since)  -> (daily bars with date in the exchange's calendar, dividends with ex-dates)
yahoo_intraday(symbol)      -> 1-minute bars (ts UTC, bar start) over the trailing 30 days, fetched in 7-day windows;
                               a minute with no trade keeps a NaN close so the grid of the session is preserved.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36"}


def get(url: str, retries: int = 4, timeout: int = 60, headers: dict | None = None) -> bytes:
    h = dict(UA)
    if headers:
        h.update(headers)
    for k in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", None)
            if code == 429 or "429" in str(e):
                time.sleep(20 * (k + 1))
            elif code in (404, 422) or k == retries - 1:
                raise
            else:
                time.sleep(2 * (k + 1))
    raise RuntimeError(url)


def yahoo_chart(symbol: str, **params) -> dict | None:
    q = urllib.parse.urlencode(params)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}"
    try:
        d = json.loads(get(url))
    except Exception:  # noqa: BLE001
        return None
    r = d.get("chart", {}).get("result")
    if not r or not r[0].get("timestamp"):
        return None
    return r[0]


def _frame(r: dict, symbol: str, keep_empty: bool) -> pd.DataFrame:
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"ts": pd.to_datetime(r["timestamp"], unit="s", utc=True), "open": q.get("open"), "high": q.get("high"),
                       "low": q.get("low"), "close": q.get("close"), "volume": q.get("volume")})
    df["symbol"] = symbol
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if not keep_empty:
        df = df.dropna(subset=["close"])
    return df[["ts", "symbol", "open", "high", "low", "close", "volume"]]


def yahoo_daily(symbol: str, since: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    p1 = int(pd.Timestamp(since, tz="UTC").timestamp())
    p2 = int(time.time()) + 86400
    r = yahoo_chart(symbol, period1=p1, period2=p2, interval="1d", events="div")
    if r is None:
        return pd.DataFrame(), pd.DataFrame(), {}
    tz = r["meta"].get("exchangeTimezoneName", "America/New_York")
    df = _frame(r, symbol, keep_empty=False)
    df["date"] = df.ts.dt.tz_convert(ZoneInfo(tz)).dt.normalize().dt.tz_localize(None)
    df = df.drop(columns="ts").drop_duplicates("date", keep="last")
    div = r.get("events", {}).get("dividends", {})
    dv = pd.DataFrame([{"symbol": symbol, "ex_date": pd.Timestamp(v["date"], unit="s", tz="UTC").tz_convert(ZoneInfo(tz)).normalize().tz_localize(None),
                        "amount": float(v["amount"])} for v in div.values()])
    meta = {k: r["meta"].get(k) for k in ("currency", "exchangeName", "fullExchangeName", "exchangeTimezoneName", "instrumentType", "longName", "shortName")}
    return df[["date", "symbol", "open", "high", "low", "close", "volume"]], dv, meta


def yahoo_intraday_1m(symbol: str, pause: float = 0.3) -> pd.DataFrame:
    """Five 7-day windows back to Yahoo's 30-day limit (a window that starts beyond it is clipped), de-duplicated on ts."""
    frames = []
    now = int(time.time())
    floor = now - 29 * 86400 + 3600
    for k in range(5):
        p2 = now - k * 7 * 86400
        p1 = max(p2 - 7 * 86400, floor)
        if p2 <= p1:
            break
        r = yahoo_chart(symbol, period1=p1, period2=p2, interval="1m")
        if r is not None:
            frames.append(_frame(r, symbol, keep_empty=True))
        time.sleep(pause)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).drop_duplicates(["ts"]).sort_values("ts").reset_index(drop=True)
