#!/usr/bin/env python3
"""Fair value, premium and reference facts.   python scripts/build_fair.py

Reads data/intraday/bars_1m.parquet, the daily bars, dividends, rates and the issuer NAV files; writes
    data/derived/es_implied.parquet        ES bars with their contract, carry and implied index
    data/derived/frame_<line>.parquet      the minute frame per line (fair, premium, inputs and their ages)
    data/derived/daytab_<line>.parquet     the day table per line (kappa self/nav, premium statistics)
    results/fair_value.json                contract switch, carry, richness by contract and day, dividend model
    results/premium.csv, premium_tod.csv   premium distribution per line, and by half-hour of the session
    results/kappa.csv                      kappa per line and day: self against NAV, premium to NAV at the close
    results/reference_facts.json           ticks inferred from the prints, session grids, issuer file status
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
from etfmm import calendar as CAL  # noqa: E402
from etfmm import data as D  # noqa: E402
from etfmm import fairvalue as FVL  # noqa: E402
from etfmm import reference as REF  # noqa: E402


def main():
    t0 = time.time()
    os.makedirs(D.RESULTS, exist_ok=True)
    lines, params = D.lines(), D.params()
    fvp = params["fair_value"]
    bars = D.bars_1m()
    rates = D.rates()
    model = FVL.dividend_model(fvp["index"], fvp["dividend_fund"])
    es = bars[bars.symbol == fvp["futures"]]
    idx = bars[bars.symbol == fvp["index"]]
    es_c, switches = FVL.contract_by_bar(es, idx)
    es_i, carry = FVL.es_implied(es_c, model, rates, fvp["rate"])
    rich_min, rich_c, rich_day = FVL.richness(es_i, idx)
    D.save_derived(es_i[["ts", "close", "F_cont", "ny_date", "expiry", "r", "tau", "D", "I_impl"]].assign(expiry=lambda x: x.expiry.astype(str).str[:10], ny_date=lambda x: x.ny_date.astype(str)), "es_implied")
    print("contract switches:", switches)
    print("richness by contract (bp):", rich_c)
    prem_rows, tod_rows, kappa_rows, line_meta = [], [], [], {}
    for name, cfg in lines.items():
        nav = D.issuer_nav(cfg["nav_file"]) if cfg.get("nav_file") else None
        frame, daytab = FVL.build_frame(name, cfg, bars, es_i, rich_c, model, params, nav)
        D.save_derived(frame.assign(date=frame.date.astype(str)), f"frame_{name}")
        D.save_derived(daytab.assign(date=daytab.date.astype(str)), f"daytab_{name}")
        c = frame[frame.continuous & frame.P.notna() & frame.prem_bp.notna()]
        qs = c.prem_bp.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
        within = c.prem_bp - c.groupby("date").prem_bp.transform("median")
        prem_rows.append({"line": name, "venue": cfg["venue"], "currency": cfg["currency"], "days": int(c.date.nunique()), "minutes": int(len(c)),
                          "prem_mean_bp": c.prem_bp.mean(), "prem_sd_bp": c.prem_bp.std(), "prem_within_day_sd_bp": within.std(), "abs_prem_median_bp": c.prem_bp.abs().median(),
                          **{f"q{int(k*100):02d}": v for k, v in qs.items()}, "share_abs_gt_5bp": float((c.prem_bp.abs() > 5).mean()), "share_abs_gt_10bp": float((c.prem_bp.abs() > 10).mean()),
                          "prem_nav_mean_bp": c.prem_nav_bp.mean() if c.prem_nav_bp.notna().any() else np.nan, "prem_nav_sd_bp": c.prem_nav_bp.std() if c.prem_nav_bp.notna().any() else np.nan,
                          "nav_days": int(daytab.kappa_nav.notna().sum()), "kappa_source_quoter": "self (closing prints)",
                          "stale_es_share": float((c.F_age_min > params["quoter"]["stale_minutes"]).mean()), "stale_fx_share": float((c.X_age_min > params["quoter"]["stale_minutes"]).mean()),
                          "median_prints_per_day": float(daytab.n_prints.median()), "median_volume_per_day": float(daytab.volume.median())})
        c = c.assign(halfhour=(c.minute // 30) * 30)
        g = c.groupby("halfhour").prem_bp
        tod = pd.DataFrame({"line": name, "halfhour": g.median().index, "median_bp": g.median().values, "q25_bp": g.quantile(0.25).values, "q75_bp": g.quantile(0.75).values,
                            "sd_bp": g.std().values, "n": g.size().values, "us_open_share": c.groupby("halfhour").us_open.mean().values})
        tod_rows.append(tod)
        kappa_rows.append(daytab.assign(line=name))
        line_meta[name] = {"days": int(len(daytab)), "first_day": str(daytab.date.iloc[0]), "last_day": str(daytab.date.iloc[-1]), "nav_file": cfg.get("nav_file"),
                           "nav_days_available": int(daytab.kappa_nav.notna().sum()), "kappa_nav_minus_self_bp_median": float(daytab.nav_vs_self_bp.median()) if daytab.nav_vs_self_bp.notna().any() else None,
                           "prem_close_median_bp": float(daytab.prem_close_bp.median()), "prem_nav_close_median_bp": float(daytab.prem_nav_close_bp.median()) if daytab.prem_nav_close_bp.notna().any() else None}
        print(name, "frame", frame.shape, "days", len(daytab), "prem sd", round(prem_rows[-1]["prem_sd_bp"], 2), "nav days", line_meta[name]["nav_days_available"])
    pd.DataFrame(prem_rows).to_csv(os.path.join(D.RESULTS, "premium.csv"), index=False)
    pd.concat(tod_rows).to_csv(os.path.join(D.RESULTS, "premium_tod.csv"), index=False)
    pd.concat(kappa_rows).to_csv(os.path.join(D.RESULTS, "kappa.csv"), index=False)
    # reference facts: ticks and session grids
    ticks = REF.line_ticks(bars, lines)
    grids = {name: REF.session_grid(bars, cfg["yahoo"], cfg["tz"]) for name, cfg in lines.items()}
    es_grid = REF.session_grid(bars, fvp["futures"], "America/New_York")
    facts = {"ticks": ticks.to_dict(orient="records"), "session_grids": grids, "es_grid": es_grid, "issuer_status": D.issuer_status(), "lines": lines,
             "sessions": CAL.SESSIONS, "bars_1m": {"rows": int(len(bars)), "first": str(bars.ts.min()), "last": str(bars.ts.max()),
                                                   "symbols": sorted(bars.symbol.unique().tolist())}}
    json.dump(facts, open(os.path.join(D.RESULTS, "reference_facts.json"), "w"), indent=1, default=str)
    fv = {"generated": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "contract_switches": switches, "richness_by_contract_bp": rich_c,
          "richness_by_day": rich_day.assign(ny_date=rich_day.ny_date.astype(str), expiry=rich_day.expiry.astype(str).str[:10]).to_dict(orient="records"),
          "carry": carry.assign(ny_date=carry.ny_date.astype(str), expiry=carry.expiry.astype(str).str[:10]).to_dict(orient="records"),
          "rate_kind": fvp["rate"], "dividend_model": {"fund": fvp["dividend_fund"], "quarters": int(len(model["q"])), "profile_n_quarters": int(model["prof"]["n"].sum()) if "n" in model["prof"] else None,
                                                       "last_quarterly_distribution": float(model["q"].amount.iloc[-1]) if len(model["q"]) else None},
          "lines": line_meta, "seconds": round(time.time() - t0, 1)}
    json.dump(fv, open(os.path.join(D.RESULTS, "fair_value.json"), "w"), indent=1, default=str)
    print("done in", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
