#!/usr/bin/env python3
"""The monitor on the base replay of each line, and the fault-injection score.   python scripts/run_monitor.py [--fast]

Writes results/monitor_table.csv (the minute table of the last quoting day of CSPX as the worked example),
results/monitor_clean_alerts.csv (alerts raised on the real replays), results/monitor_faults.csv and monitor_faults.json
(detection rate and delay by fault type and line), data/derived/monitor_injections.parquet (every injection).
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
from etfmm import data as D  # noqa: E402
from etfmm import monitor as M  # noqa: E402


def main(argv):
    fast = "--fast" in argv
    t0 = time.time()
    lines, params = D.lines(), D.params()
    mp = params["monitor"]
    paths, fills, hedges = {}, {}, {}
    for name in lines:
        p = D.derived(f"path_{name}")
        p["ts"] = pd.to_datetime(p.ts, utc=True)
        paths[name] = p
        f = D.derived(f"fills_{name}")
        if len(f):
            f["ts"] = pd.to_datetime(f.ts, utc=True)
        fills[name] = f
        h = D.derived(f"hedges_{name}")
        if len(h):
            h["ts"] = pd.to_datetime(h.ts, utc=True)
        hedges[name] = h
    clean, faults, inj = M.score(paths, fills, hedges, lines, mp, n_days_per_fault=3 if fast else 8, seed=params["bootstrap"]["seed"], mult=params["fair_value"]["futures_multiplier"])
    clean.to_csv(os.path.join(D.RESULTS, "monitor_clean_alerts.csv"), index=False)
    faults.to_csv(os.path.join(D.RESULTS, "monitor_faults.csv"), index=False)
    D.save_derived(inj.assign(date=inj.date.astype(str)), "monitor_injections")
    # the worked example: the last quoting day of CSPX
    P = paths["CSPX"]
    last_day = sorted(P[P.cont & P.bid.notna()].date.unique())[-1]
    tab, al = M.day_table(P[P.date == last_day], fills["CSPX"], hedges["CSPX"], mp, params["fair_value"]["futures_multiplier"], True)
    tab.to_csv(os.path.join(D.RESULTS, "monitor_table.csv"), index=False)
    by_fault = inj.groupby("fault").agg(n=("caught", "size"), detection_rate=("caught", "mean"), median_delay_min=("delay_min", "median")).reset_index()
    n_clean_days = int(sum(len(p[p.cont & p.bid.notna()].date.unique()) for p in paths.values()))
    out = {"by_fault": by_fault.to_dict(orient="records"), "by_line_fault": faults.to_dict(orient="records"), "overall_detection_rate": float(inj.caught.mean()),
           "n_injections": int(len(inj)), "clean_days": n_clean_days, "clean_alerts": int(len(clean)), "clean_alerts_per_day": float(len(clean) / max(n_clean_days, 1)),
           "clean_alerts_by_rule": clean.rule.value_counts().to_dict() if len(clean) else {}, "example_day": str(last_day), "example_line": "CSPX",
           "example_alerts": [{"ts": str(a.ts), "rule": a.rule, "detail": a.detail} for a in al],
           "example_table_extremes": {"max_abs_position_clips": float(tab.position_clips.abs().max()), "max_abs_delta_clips": float(tab.delta_clips.abs().max()),
                                      "max_abs_fx_exposure_usd": float(tab.fx_exposure_usd.abs().max()), "net_flow_end": float(tab.net_flow.iloc[-1]),
                                      "bought": float(tab.bought.iloc[-1]), "sold": float(tab.sold.iloc[-1]), "pnl_day_usd": float(tab.pnl_day_usd.dropna().iloc[-1]) if tab.pnl_day_usd.notna().any() else None},
           "limits": mp, "seconds": round(time.time() - t0, 1)}
    json.dump(out, open(os.path.join(D.RESULTS, "monitor_faults.json"), "w"), indent=1, default=str)
    print(by_fault.round(3).to_string())
    print("clean alerts:", len(clean), out["clean_alerts_by_rule"])
    print("done in", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main(sys.argv[1:])
