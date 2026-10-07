"""Paths, configuration and loaders.  Every table is a parquet, csv or json under data/.

data/reference/   daily.parquet (date, symbol, open..volume), dividends.parquet (symbol, ex_date, amount), symbols.json,
                  rates.parquet (date, tbill_1m..tsy_1y, SOFR, EFFR, ESTR, SONIA; percent), issuer/ (NAV, holdings), issuer_status.json
data/intraday/    bars_1m.parquet (ts UTC = bar start, symbol, open..volume; a minute with no trade has a NaN close)
data/derived/     what the run writes
configs/          lines.json (the four lines and their reference facts, each with its source), params.json (the quoter and the bound)
"""
from __future__ import annotations

import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("ETFMM_DATA", os.path.join(ROOT, "data"))
REF = os.path.join(DATA, "reference")
INTRA = os.path.join(DATA, "intraday")
DERIVED = os.path.join(DATA, "derived")
RESULTS = os.environ.get("ETFMM_RESULTS", os.path.join(ROOT, "results"))
CONFIGS = os.path.join(ROOT, "configs")


def _json(name: str) -> dict:
    with open(os.path.join(CONFIGS, name), encoding="utf-8") as f:
        return json.load(f)


def lines() -> dict:
    """The ETF lines keyed by their short name; entries starting with '_' are notes."""
    return {k: v for k, v in _json("lines.json").items() if not k.startswith("_")}


def params() -> dict:
    return _json("params.json")


def daily(symbols=None) -> pd.DataFrame:
    df = pd.read_parquet(os.path.join(REF, "daily.parquet"))
    if symbols is not None:
        df = df[df.symbol.isin(list(symbols))]
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def closes(symbols) -> pd.DataFrame:
    d = daily(symbols)
    return d.pivot(index="date", columns="symbol", values="close").sort_index()


def dividends(symbol: str) -> pd.DataFrame:
    p = os.path.join(REF, "dividends.parquet")
    if not os.path.exists(p):
        return pd.DataFrame(columns=["symbol", "ex_date", "amount"])
    df = pd.read_parquet(p)
    return df[df.symbol == symbol].sort_values("ex_date").reset_index(drop=True)


def rates() -> pd.DataFrame:
    """Daily rates in percent, date index, forward-filled over weekends and holidays."""
    r = pd.read_parquet(os.path.join(REF, "rates.parquet")).set_index("date").sort_index()
    idx = pd.date_range(r.index.min(), max(r.index.max(), pd.Timestamp.today().normalize()) + pd.Timedelta(days=3), freq="D")
    return r.reindex(idx).ffill()


def bars_1m(symbols=None) -> pd.DataFrame:
    df = pd.read_parquet(os.path.join(INTRA, "bars_1m.parquet"))
    if symbols is not None:
        df = df[df.symbol.isin(list(symbols))]
    df["ts"] = pd.to_datetime(df["ts"], utc=True).astype("datetime64[us, UTC]")  # one resolution for every merge
    return df.sort_values(["symbol", "ts"]).reset_index(drop=True)


def issuer_nav(name: str) -> pd.DataFrame | None:
    """Issuer NAV series (date, nav in USD) from data/reference/issuer/{name}.parquet if the download produced one; None
    otherwise.  The iShares file has (date, nav, currency); the Vanguard page tables have (date, nav_usd, price_gbp)."""
    p = os.path.join(REF, "issuer", f"{name}.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    if "nav_usd" in df.columns:
        df = df.rename(columns={"nav_usd": "nav"})
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "nav"]].dropna().sort_values("date").reset_index(drop=True)


def issuer_status() -> dict:
    p = os.path.join(REF, "issuer_status.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def save_derived(df: pd.DataFrame, name: str):
    os.makedirs(DERIVED, exist_ok=True)
    df.to_parquet(os.path.join(DERIVED, f"{name}.parquet"), index=False, compression="zstd")


def derived(name: str) -> pd.DataFrame:
    p = os.path.join(DERIVED, f"{name}.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()
