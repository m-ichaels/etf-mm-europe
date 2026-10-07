#!/usr/bin/env python3
"""The creation/redemption bound by line and unit count.   python scripts/run_bound.py

Inputs: configs/lines.json (unit sizes), configs/params.json (the cost assumptions), the latest NAV per line (issuer file where
there is one, else the line's last fair in USD), the last ES price and the overnight rate (SOFR) from the data.
Writes results/bound.csv and results/bound.json.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etfmm import bound as B  # noqa: E402
from etfmm import data as D  # noqa: E402


def latest_navs(lines: dict) -> dict:
    navs, src = {}, {}
    for name, cfg in lines.items():
        nav = D.issuer_nav(cfg["nav_file"]) if cfg.get("nav_file") else None
        if nav is not None and not nav.empty:
            navs[name] = float(nav.nav.iloc[-1])
            src[name] = f"issuer NAV {nav.date.iloc[-1].date()}"
        else:
            dt = D.derived(f"daytab_{name}")
            navs[name] = float(dt.fair_close_usd.dropna().iloc[-1])
            src[name] = f"last fair (USD) {dt.date.iloc[-1]}"
    return navs, src


def main():
    lines, params = D.lines(), D.params()
    navs, src = latest_navs(lines)
    es = D.daily(["ES=F"])
    es_price = float(es.close.dropna().iloc[-1])
    r = D.rates()
    sofr = float(r["SOFR"].dropna().iloc[-1]) / 100.0
    tab = B.bound_table(lines, navs, es_price, sofr, params)
    tab.to_csv(os.path.join(D.RESULTS, "bound.csv"), index=False)
    base = tab[tab.case == "base"]
    out = {"inputs": {"es_price": es_price, "es_date": str(es.date.iloc[-1].date()), "overnight_rate_sofr": sofr, "navs_usd": navs, "nav_sources": src,
                      "assumptions": {k: params["bound"][k] for k in ("fixed_fee_usd", "basket_half_spread_bp", "es_half_spread_ticks", "fx_half_spread_bp", "settlement_mismatch_days")},
                      "unit_shares": {k: v["creation_unit_shares"] for k, v in lines.items()}, "unit_published": {k: v.get("creation_unit_published", False) for k, v in lines.items()}},
           "one_unit_bp": {row.line: float(row.bound_bp) for row in base[base.n_units == 1].itertuples()},
           "by_units": {line: {int(row.n_units): float(row.bound_bp) for row in base[base.line == line].itertuples()} for line in lines},
           "components_one_unit": {row.line: {"fixed_fee_bp": row.fixed_fee_bp, "basket_bp": row.basket_bp, "hedge_bp": row.hedge_bp, "fx_bp": row.fx_bp, "settlement_bp": row.settlement_bp}
                                   for row in base[base.n_units == 1].itertuples()},
           "sensitivity": {case: tab[tab.case == case][["line", "fixed_fee_usd", "settlement_days", "basket_bp", "bound_bp"]].to_dict(orient="records") for case in ("fixed_fee", "settlement_days", "basket_bp")}}
    json.dump(out, open(os.path.join(D.RESULTS, "bound.json"), "w"), indent=1, default=float)
    print(base[["line", "n_units", "notional_usd", "fixed_fee_bp", "basket_bp", "hedge_bp", "fx_bp", "settlement_bp", "bound_bp"]].round(3).to_string())


if __name__ == "__main__":
    main()
