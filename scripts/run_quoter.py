#!/usr/bin/env python3
"""The quoter on every line, over the half-spread grid and the sensitivity cases.   python scripts/run_quoter.py [--fast]

Writes
    data/derived/quoter_daily.parquet      per line, case, half-spread and day: fills, notional, the five P&L components
    data/derived/fills_<line>.parquet      the fills of the base case at the base half-spread
    data/derived/hedges_<line>.parquet     the hedges of the same run
    data/derived/path_<line>.parquet       the minute path of the same run (position, hedge, cash, quotes, marks) for the monitor
    results/quoter_grid.csv                totals by line, case and half-spread (P&L per fill in bp and USD, components)
    results/breakeven.json                 break-even half-spread per line with block-bootstrap intervals, the P&L curve
    results/sensitivity.csv                break-even per line and case
    results/quoter_summary.json            the base run per line: components, fills, identity gap
--fast: a shorter half-spread grid, fewer bootstrap draws (CI).
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etfmm import bound as B  # noqa: E402
from etfmm import data as D  # noqa: E402
from etfmm import quoter as Q  # noqa: E402
from etfmm import stats as S  # noqa: E402


def cases(params: dict) -> dict:
    """The base case and one-parameter-at-a-time sensitivities (name -> overrides)."""
    s, q = params["sensitivity"], params["quoter"]
    out = {"base": {}}
    for v in s["through_ticks"]:
        if v != q["through_ticks"]:
            out[f"through_ticks={v}"] = {"through_ticks": v}
    for v in s["max_participation"]:
        if v != q["max_participation"]:
            out[f"participation={v}"] = {"max_participation": v}
    for v in s["eod"]:
        if v != q["eod"]:
            out[f"eod={v}"] = {"eod": v}
    for v in s["hedge_delay_bars"]:
        if v != q["hedge_delay_bars"]:
            out[f"hedge_delay={v}"] = {"hedge_delay_bars": v}
    out["kappa=nav"] = {"fair_column": "nav_fair"}
    out["skew=0"] = {"skew_bp_per_clip": 0.0}
    for v in s.get("recentre_halflife_min", []):
        out[f"recentre={v}min"] = {"recentre_halflife_min": v}
    for v in s.get("track_es", []):
        out["quotes_track_es"] = {"track_es": bool(v)}
    out["quotes_track_es+recentre"] = {"track_es": True, "recentre_halflife_min": 30}
    return out


def main(argv):
    fast = "--fast" in argv
    t0 = time.time()
    lines, params = D.lines(), D.params()
    q = params["quoter"]
    grid = [h for h in q["half_spread_bp_grid"] if (not fast or h in (1, 2, 3, 5, 8, 12))]
    base_h = q["base_half_spread_bp"]
    bs = params["bootstrap"]
    n_boot = 100 if fast else bs["n_boot"]
    bound = json.load(open(os.path.join(D.RESULTS, "bound.json")))
    daily_rows, grid_rows, summary, be, sens = [], [], {}, {}, []
    for name, cfg in lines.items():
        frame = D.derived(f"frame_{name}")
        frame["date"] = pd.to_datetime(frame.date).dt.date
        redeem_bp = bound["one_unit_bp"][name]
        for case, over in cases(params).items():
            if fast and case not in ("base", "through_ticks=0", "eod=flatten_close", "kappa=nav", "quotes_track_es"):
                continue
            if case == "kappa=nav" and frame.nav_fair.notna().sum() < 0.5 * frame.fair.notna().sum():
                continue  # the issuer NAV covers too few days of this line
            p0 = Q.QuoterParams.from_params(params, cfg, redeem_cost_bp=redeem_bp, **over)
            arrays = Q.prepare(frame, p0)
            for h in grid:
                p = Q.QuoterParams.from_params(params, cfg, redeem_cost_bp=redeem_bp, half_spread_bp=h, **over)
                rec = case == "base" and h == base_h
                r = Q.replay(arrays, p, record_path=rec)
                d = r["daily"].assign(line=name, case=case, h=h)
                daily_rows.append(d)
                c = r["components_usd"]
                grid_rows.append({"line": name, "case": case, "h": h, "n_fills": r["n_fills"], "notional_usd": r["notional_usd"], "pnl_usd": r["total_pnl_usd"],
                                  "pnl_bp": r["pnl_bp"], "pnl_per_fill_usd": r["total_pnl_usd"] / max(r["n_fills"], 1), **{f"{k}_usd": v for k, v in c.items()},
                                  **{f"{k}_bp": v / r["notional_usd"] * 1e4 if r["notional_usd"] > 0 else np.nan for k, v in c.items()},
                                  "quoted_bars": r["quoted_bars"], "pulled_bars": r["pulled_bars"], "identity_gap_usd": r["identity_gap_usd"], "q_end": r["q_end"], "es_end": r["es_end"],
                                  "fills_per_day": r["n_fills"] / max(int((d.n_fills > 0).sum() + (d.quoted_bars > 0).sum() - (d.n_fills > 0).sum()), 1)})
                if rec:
                    D.save_derived(r["fills"].assign(ts=pd.to_datetime(r["fills"].ts, utc=True), date=r["fills"].date.astype(str)) if len(r["fills"]) else pd.DataFrame(), f"fills_{name}")
                    D.save_derived(r["hedges"].assign(ts=pd.to_datetime(r["hedges"].ts, utc=True)) if len(r["hedges"]) else pd.DataFrame(), f"hedges_{name}")
                    D.save_derived(r["path"].assign(ts=pd.to_datetime(r["path"].ts, utc=True), date=r["path"].date.astype(str)), f"path_{name}")
                    f = r["fills"]
                    summary[name] = {"h_bp": h, "n_fills": r["n_fills"], "notional_usd": r["notional_usd"], "pnl_usd": r["total_pnl_usd"], "pnl_bp": r["pnl_bp"],
                                     "pnl_per_fill_usd": r["total_pnl_usd"] / max(r["n_fills"], 1), "components_usd": c,
                                     "components_bp": {k: v / r["notional_usd"] * 1e4 for k, v in c.items()} if r["notional_usd"] > 0 else {},
                                     "identity_gap_usd": r["identity_gap_usd"], "quoted_bars": r["quoted_bars"], "pulled_bars": r["pulled_bars"],
                                     "days_quoting": int((d.quoted_bars > 0).sum()), "fills_per_quoting_day": r["n_fills"] / max(int((d.quoted_bars > 0).sum()), 1),
                                     "buy_share": float((f.side == 1).mean()) if len(f) else np.nan, "median_fill_shares": float(f["size"].median()) if len(f) else np.nan,
                                     "median_clip_shares": float(f["clip"].median()) if len(f) else np.nan, "max_abs_inventory_clips": float((f.q_after / f["clip"]).abs().max()) if len(f) else 0.0,
                                     "fill_share_of_quoted_bars": r["n_fills"] / max(r["quoted_bars"], 1), "hedges": int(len(r["hedges"])),
                                     "daily_pnl_mean_usd": float(d.pnl_usd[d.quoted_bars > 0].mean()), "daily_pnl_sd_usd": float(d.pnl_usd[d.quoted_bars > 0].std()),
                                     "worst_day_usd": float(d.pnl_usd.min()), "best_day_usd": float(d.pnl_usd.max())}
            print(f"{name} {case}: done ({time.time() - t0:.0f} s)", flush=True)
    daily = pd.concat(daily_rows, ignore_index=True)
    daily["date"] = daily.date.astype(str)
    D.save_derived(daily, "quoter_daily")
    gridf = pd.DataFrame(grid_rows)
    gridf.to_csv(os.path.join(D.RESULTS, "quoter_grid.csv"), index=False)
    # break-even with intervals, base case; sensitivity break-evens (point estimates) for the other cases
    for name in lines:
        dd = daily[(daily.line == name) & (daily.case == "base")]
        dd = dd[dd.quoted_bars > 0]  # days without quotes (the first day, no kappa) carry no information
        res = S.bootstrap_curve(dd, grid, n_boot=n_boot, block=bs["block_days"], seed=bs["seed"], base_h=base_h)
        res["bound_one_unit_bp"] = bound["one_unit_bp"][name]
        res["bound_by_units_bp"] = bound["by_units"][name]
        res["clears_bound_one_unit"] = bool(res["breakeven_bp"] <= bound["one_unit_bp"][name]) if np.isfinite(res["breakeven_bp"]) else False
        res["hedge_cost_bp"] = bound["components_one_unit"][name]["hedge_bp"]
        # components at the break-even's neighbours: the mix of capture, slippage and the rest at the base h
        g = gridf[(gridf.line == name) & (gridf.case == "base")].sort_values("h")
        res["grid"] = g[["h", "n_fills", "pnl_bp", "capture_bp", "hedge_slip_bp", "fx_bp", "inventory_bp", "fees_bp", "pnl_usd"]].to_dict(orient="records")
        be[name] = res
        for case in daily[daily.line == name].case.unique():
            dc = daily[(daily.line == name) & (daily.case == case) & (daily.quoted_bars > 0)]
            rc = S.bootstrap_curve(dc, grid, n_boot=max(100, n_boot // 5), block=bs["block_days"], seed=bs["seed"], base_h=base_h)
            sens.append({"line": name, "case": case, "breakeven_bp": rc["breakeven_bp"], "breakeven_lo": rc["breakeven_lo"], "breakeven_hi": rc["breakeven_hi"],
                         "pnl_bp_at_base_h": rc.get("base_pnl_bp"), "n_fills_at_base_h": int(gridf[(gridf.line == name) & (gridf.case == case) & (gridf.h == base_h)].n_fills.sum()),
                         "pnl_usd_at_base_h": float(gridf[(gridf.line == name) & (gridf.case == case) & (gridf.h == base_h)].pnl_usd.sum())})
    json.dump(be, open(os.path.join(D.RESULTS, "breakeven.json"), "w"), indent=1, default=float)
    pd.DataFrame(sens).to_csv(os.path.join(D.RESULTS, "sensitivity.csv"), index=False)
    summary["_run"] = {"grid": grid, "base_h": base_h, "n_boot": n_boot, "fast": fast, "seconds": round(time.time() - t0, 1), "cases": list(cases(params))}
    json.dump(summary, open(os.path.join(D.RESULTS, "quoter_summary.json"), "w"), indent=1, default=float)
    for name in lines:
        r = be[name]
        print(f"{name}: break-even {r['breakeven_bp']:.2f} bp [{r['breakeven_lo']:.2f}, {r['breakeven_hi']:.2f}]  bound(1 unit) {r['bound_one_unit_bp']:.2f} bp  base h {base_h}: {r.get('base_pnl_bp', float('nan')):.2f} bp/fill")
    print("done in", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main(sys.argv[1:])
