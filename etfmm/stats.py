"""Break-even half-spread and the block bootstrap over days.

The quoter is replayed on a grid of half-spreads h.  For each h the days give totals (P&L in USD by component, fill notional,
fill count).  P&L per fill in bp of the fill notional is sum(P&L) / sum(notional) x 1e4; the break-even h* is where that curve
crosses zero (linear interpolation between grid points, the first crossing from below; grid points with fewer than `min_fills`
fills over the sample carry no estimate).  Uncertainty: a circular block
bootstrap over trading days (blocks of `block_days`), re-solving h* on each resample.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def pnl_bp(pnl_usd: np.ndarray, notional_usd: np.ndarray) -> float:
    n = float(np.nansum(notional_usd))
    return float(np.nansum(pnl_usd) / n * 1e4) if n > 0 else np.nan


def breakeven(h: np.ndarray, y: np.ndarray) -> float:
    """First h where the curve y(h) crosses zero from below (linear interpolation); +inf if never positive, h[0] if y[0] >= 0."""
    h = np.asarray(h, float)
    y = np.asarray(y, float)
    ok = np.isfinite(y)
    h, y = h[ok], y[ok]
    if len(h) == 0:
        return np.nan
    if y[0] >= 0:
        return float(h[0])
    for i in range(1, len(h)):
        if y[i] >= 0 > y[i - 1]:
            return float(h[i - 1] + (h[i] - h[i - 1]) * (0 - y[i - 1]) / (y[i] - y[i - 1]))
    return float("inf")


def block_indices(n_days: int, block: int, rng: np.random.Generator) -> np.ndarray:
    nb = int(np.ceil(n_days / block))
    starts = rng.integers(0, n_days, nb)
    idx = np.concatenate([(s + np.arange(block)) % n_days for s in starts])[:n_days]
    return idx


def bootstrap_curve(daily: pd.DataFrame, h_grid: list, n_boot: int = 1000, block: int = 3, seed: int = 0, base_h: float | None = None, min_fills: int = 10) -> dict:
    """daily: rows (h, date, pnl_usd, notional_usd, n_fills, ...).  Returns the point estimates and intervals of P&L per fill
    (bp) by h, the break-even h*, and the P&L per fill at base_h."""
    piv_pnl = daily.pivot(index="date", columns="h", values="pnl_usd").reindex(columns=h_grid).fillna(0.0)
    piv_not = daily.pivot(index="date", columns="h", values="notional_usd").reindex(columns=h_grid).fillna(0.0)
    P, N = piv_pnl.to_numpy(), piv_not.to_numpy()
    h = np.asarray(h_grid, float)
    if "n_fills" in daily.columns:
        enough = daily.pivot(index="date", columns="h", values="n_fills").reindex(columns=h_grid).fillna(0.0).to_numpy().sum(0) >= min_fills
    else:
        enough = np.ones(len(h_grid), bool)

    def curve(idx):
        y = np.where(N[idx].sum(0) > 0, P[idx].sum(0) / np.maximum(N[idx].sum(0), 1e-12) * 1e4, np.nan)
        return np.where(enough, y, np.nan)  # grid points with fewer than min_fills fills over the sample carry no estimate

    y0 = curve(np.arange(len(P)))
    he0 = breakeven(h, y0)
    rng = np.random.default_rng(seed)
    ys, hes = [], []
    for _ in range(n_boot):
        idx = block_indices(len(P), block, rng)
        y = curve(idx)
        ys.append(y)
        hes.append(breakeven(h, y))
    ys = np.array(ys)
    hes = np.array(hes, float)
    fin = np.isfinite(hes)
    out = {"h": h.tolist(), "pnl_bp": y0.tolist(), "pnl_bp_lo": np.nanpercentile(ys, 2.5, axis=0).tolist(), "pnl_bp_hi": np.nanpercentile(ys, 97.5, axis=0).tolist(),
           "breakeven_bp": he0, "breakeven_lo": float(np.nanpercentile(hes[fin], 2.5)) if fin.any() else np.nan,
           "breakeven_hi": float(np.nanpercentile(hes[fin], 97.5)) if fin.any() else np.nan,
           "breakeven_share_inf": float(1 - fin.mean()), "n_days": int(len(P)), "n_boot": n_boot, "block_days": block, "min_fills": min_fills, "h_with_enough_fills": h[enough].tolist()}
    if base_h is not None and base_h in h_grid:
        j = h_grid.index(base_h)
        out["base_h"] = base_h
        out["base_pnl_bp"] = float(y0[j])
        out["base_pnl_bp_lo"] = float(np.nanpercentile(ys[:, j], 2.5))
        out["base_pnl_bp_hi"] = float(np.nanpercentile(ys[:, j], 97.5))
    return out


def bootstrap_mean(x: np.ndarray, n_boot: int = 1000, block: int = 3, seed: int = 0) -> dict:
    """Block-bootstrap interval for the mean of a daily series."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {"mean": np.nan, "lo": np.nan, "hi": np.nan, "n": 0}
    rng = np.random.default_rng(seed)
    ms = [x[block_indices(len(x), block, rng)].mean() for _ in range(n_boot)]
    return {"mean": float(x.mean()), "lo": float(np.percentile(ms, 2.5)), "hi": float(np.percentile(ms, 97.5)), "n": int(len(x))}
