"""Reference facts read from the data: the tick size each line trades on, and the session grid the bars actually cover.

The venues' tick schedules live in files this pipeline cannot fetch (the LSE Business Parameters workbook) or in the ESMA
bands (Xetra), so the tick is inferred from the prints: the smallest candidate increment on which almost all of a line's
open/high/low/close prices sit.  Yahoo stores prices as float32, so the test allows a residual of a few 1e-5 of the price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CANDIDATE_TICKS = (1.0, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.0025, 0.002, 0.001, 0.0005)


def on_grid_share(prices: np.ndarray, tick: float) -> float:
    """Share of prices within float32 tolerance of a multiple of `tick`."""
    px = np.asarray(prices, float)
    px = px[np.isfinite(px)]
    if len(px) == 0:
        return np.nan
    k = px / tick
    resid = np.abs(k - np.round(k)) * tick
    tol = np.maximum(2e-4 * px / 100.0, 1e-5)  # ~2e-6 relative: float32 noise with margin
    return float(np.mean(resid <= tol))


def infer_tick(prices: np.ndarray, min_share: float = 0.9, candidates=CANDIDATE_TICKS) -> dict:
    """The coarsest candidate tick on which at least `min_share` of the prints sit (coarsest first, so 0.02 is preferred
    to 0.01 when both fit).  Returns the tick, its on-grid share and the shares of every candidate."""
    shares = {t: on_grid_share(prices, t) for t in candidates}
    chosen = None
    for t in sorted(candidates, reverse=True):
        if shares[t] >= min_share:
            chosen = t
            break
    return {"tick": chosen, "share": shares.get(chosen, np.nan), "shares": shares, "n": int(np.isfinite(np.asarray(prices, float)).sum())}


def line_ticks(bars: pd.DataFrame, lines: dict) -> pd.DataFrame:
    rows = []
    for name, cfg in lines.items():
        x = bars[(bars.symbol == cfg["yahoo"]) & bars.close.notna()]
        px = np.concatenate([x.open.to_numpy(), x.high.to_numpy(), x.low.to_numpy(), x.close.to_numpy()])
        r = infer_tick(px)
        rows.append({"line": name, "symbol": cfg["yahoo"], "currency": cfg["currency"], "tick_inferred": r["tick"], "on_grid_share": r["share"],
                     "tick_config": cfg.get("tick"), "n_prices": r["n"], "median_price": float(np.nanmedian(px)) if len(px) else np.nan})
    return pd.DataFrame(rows)


def session_grid(bars: pd.DataFrame, symbol: str, tz: str) -> dict:
    """First and last minute with a print, by local time, and the modal count of printed minutes per day."""
    x = bars[(bars.symbol == symbol) & bars.close.notna()].copy()
    lt = x.ts.dt.tz_convert(tz)
    x["hm"] = lt.dt.strftime("%H:%M")
    x["d"] = lt.dt.date
    per_day = x.groupby("d").agg(first=("hm", "min"), last=("hm", "max"), n=("hm", "size"))
    return {"days": int(len(per_day)), "first_print_mode": per_day["first"].mode().iloc[0], "last_print_mode": per_day["last"].mode().iloc[0],
            "prints_per_day_median": float(per_day.n.median()), "prints_per_day_min": int(per_day.n.min())}
