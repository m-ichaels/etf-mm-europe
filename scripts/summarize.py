#!/usr/bin/env python3
"""results/summary.md from the results files.   python scripts/summarize.py"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etfmm import data as D  # noqa: E402


def fmt(x, nd=2):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "none" if x == float("inf") or x is None else "nan"
    return f"{x:.{nd}f}"


def table(df: pd.DataFrame, cols: list, nd: int = 2) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df[cols].itertuples(index=False):
        out.append("| " + " | ".join(fmt(v, nd) if isinstance(v, (float, np.floating)) else str(v) for v in r) + " |")
    return "\n".join(out)


def main():
    R = D.RESULTS
    lines = list(D.lines())
    fv = json.load(open(os.path.join(R, "fair_value.json")))
    prem = pd.read_csv(os.path.join(R, "premium.csv"))
    be = json.load(open(os.path.join(R, "breakeven.json")))
    bound = json.load(open(os.path.join(R, "bound.json")))
    qs = json.load(open(os.path.join(R, "quoter_summary.json")))
    sens = pd.read_csv(os.path.join(R, "sensitivity.csv"))
    facts = json.load(open(os.path.join(R, "reference_facts.json")))
    mon = json.load(open(os.path.join(R, "monitor_faults.json"))) if os.path.exists(os.path.join(R, "monitor_faults.json")) else None
    run = qs["_run"]
    md = [f"# etf-mm-europe — run summary ({fv['generated'][:10]}; quoter grid {run['grid']}, base h {run['base_h']} bp, {run['n_boot']} bootstrap draws, {run['seconds']} s)", ""]
    b = facts["bars_1m"]
    md.append(f"Data: 1-minute bars {b['first'][:10]} .. {b['last'][:10]} ({b['rows']} rows, {len(b['symbols'])} symbols); {prem.days.iloc[0]} quoting days per line (the first day strikes kappa). "
              f"ES contract switch in Yahoo's continuous series: {fv['contract_switches'][0]['from_expiry']} -> {fv['contract_switches'][0]['to_expiry']} at {fv['contract_switches'][0]['ts'][:16]} UTC "
              f"({fv['contract_switches'][0]['one_minute_return_bp']:.0f} bp jump, cash index confirms: {fv['contract_switches'][0].get('cash_index_confirms')}). "
              f"Richness of the implied index to the cash index (bp, median over the US session, removed from the fair): " + ", ".join(f"{k}: {v:+.1f}" for k, v in fv["richness_by_contract_bp"].items()) + ".")
    md += ["", "## Break-even half-spread against the creation/redemption bound (bp)", ""]
    rows = []
    for name in lines:
        r = be[name]
        s_track = sens[(sens.line == name) & (sens.case == "quotes_track_es")]
        rows.append({"line": name, "break-even h* (fixed quotes)": fmt(r["breakeven_bp"]), "95% CI": f"[{fmt(r['breakeven_lo'])}, {fmt(r['breakeven_hi'])}]",
                     "h* (quotes track ES within the bar)": fmt(float(s_track.breakeven_bp.iloc[0])) if len(s_track) else "-",
                     "bound, 1 unit": fmt(r["bound_one_unit_bp"]), "bound, 10 units": fmt(r["bound_by_units_bp"]["10"]), "hedge cost": fmt(r["hedge_cost_bp"]),
                     f"P&L/fill at h={run['base_h']} (bp)": f"{fmt(r.get('base_pnl_bp'))} [{fmt(r.get('base_pnl_bp_lo'))}, {fmt(r.get('base_pnl_bp_hi'))}]", "clears bound": "yes" if r["clears_bound_one_unit"] else "no"})
    df = pd.DataFrame(rows)
    md.append(table(df, list(df.columns)))
    md += ["", "## Premium / discount to the ES-implied fair (1-minute closes, continuous trading)", ""]
    pc = prem.rename(columns={"prem_mean_bp": "mean", "prem_sd_bp": "sd", "prem_within_day_sd_bp": "within-day sd", "q05": "q05", "q50": "median", "q95": "q95",
                              "share_abs_gt_5bp": "share |prem|>5bp", "prem_nav_mean_bp": "mean vs NAV-fair", "nav_days": "NAV days", "median_volume_per_day": "median shares/day"})
    md.append(table(pc, ["line", "venue", "currency", "days", "minutes", "mean", "sd", "within-day sd", "q05", "median", "q95", "share |prem|>5bp", "mean vs NAV-fair", "NAV days", "median shares/day"]))
    md += ["", "## The quoter at the base half-spread: attribution per fill (bp of fill notional)", ""]
    rows = []
    for name in lines:
        s = qs[name]
        c = s["components_bp"]
        rows.append({"line": name, "fills": s["n_fills"], "fills/day": round(s["fills_per_quoting_day"], 1), "notional (USD m)": s["notional_usd"] / 1e6, "median fill (shares)": s["median_fill_shares"],
                     "clip (shares)": s["median_clip_shares"], "capture": c.get("capture"), "hedge slip": c.get("hedge_slip"), "FX": c.get("fx"), "inventory": c.get("inventory"), "fees": c.get("fees"),
                     "total": s["pnl_bp"], "USD/fill": s["pnl_per_fill_usd"], "total USD": s["pnl_usd"], "identity gap USD": s["identity_gap_usd"], "max |inv| (clips)": s["max_abs_inventory_clips"]})
    df = pd.DataFrame(rows)
    md.append(table(df, list(df.columns)))
    md += ["", "## P&L per fill by half-spread (bp), base case", ""]
    for name in lines:
        g = pd.DataFrame(be[name]["grid"])
        md.append(f"- **{name}**: " + "; ".join(f"h {r.h:g}: {r.pnl_bp:+.2f} ({int(r.n_fills)} fills; capture {r.capture_bp:+.2f}, slip {r.hedge_slip_bp:+.2f}, fx {r.fx_bp:+.2f}, inv {r.inventory_bp:+.2f}, fees {r.fees_bp:+.2f})" for r in g.itertuples()))
    md += ["", "## Sensitivity: break-even half-spread (bp) by case", ""]
    piv = sens.pivot(index="case", columns="line", values="breakeven_bp").reindex(columns=lines)
    piv_n = sens.pivot(index="case", columns="line", values="pnl_bp_at_base_h").reindex(columns=lines)
    out = ["| case | " + " | ".join(f"{l} h*" for l in lines) + " | " + " | ".join(f"{l} P&L/fill at base h" for l in lines) + " |", "|---|" + "---|" * (2 * len(lines))]
    for case in piv.index:
        out.append(f"| {case} | " + " | ".join(fmt(piv.loc[case, l]) for l in lines) + " | " + " | ".join(fmt(piv_n.loc[case, l]) for l in lines) + " |")
    md += out
    md += ["", "## The creation/redemption bound (bp of unit notional)", ""]
    bt = pd.read_csv(os.path.join(R, "bound.csv"))
    base = bt[bt.case == "base"]
    md.append(table(base.assign(**{"notional (USD m)": base.notional_usd / 1e6}), ["line", "n_units", "notional (USD m)", "fixed_fee_bp", "basket_bp", "hedge_bp", "fx_bp", "settlement_bp", "bound_bp", "unit_published"]))
    md.append("")
    md.append(f"Inputs: ES {bound['inputs']['es_price']:.2f} ({bound['inputs']['es_date']}), SOFR {bound['inputs']['overnight_rate_sofr'] * 100:.2f} %, NAVs " + ", ".join(f"{k} {v:.2f} ({bound['inputs']['nav_sources'][k]})" for k, v in bound["inputs"]["navs_usd"].items())
              + f"; assumptions {bound['inputs']['assumptions']}. Sensitivity (one unit): fixed fee " + "; ".join(f"{r['line']} ${r['fixed_fee_usd']:.0f}: {r['bound_bp']:.2f}" for r in bound["sensitivity"]["fixed_fee"][:4])
              + " ...; settlement days " + "; ".join(f"{r['line']} {r['settlement_days']} d: {r['bound_bp']:.2f}" for r in bound["sensitivity"]["settlement_days"][:3]) + " ... (results/bound.csv).")
    md += ["", "## Kappa and the premium to NAV", ""]
    for name, m in fv["lines"].items():
        md.append(f"- **{name}**: {m['days']} days ({m['first_day']} .. {m['last_day']}); issuer NAV on {m['nav_days_available']} days from {m['nav_file']}; median (self kappa / NAV kappa - 1): "
                  f"{fmt(m['kappa_nav_minus_self_bp_median'])} bp; median closing premium to the self fair {fmt(m['prem_close_median_bp'])} bp, to the NAV fair {fmt(m['prem_nav_close_median_bp'])} bp.")
    if mon:
        md += ["", f"## Monitor: fault injection ({mon['n_injections']} injections on real days, detection within {mon['limits']['detect_window_minutes']} min)", ""]
        bf = pd.DataFrame(mon["by_fault"])
        md.append(table(bf, ["fault", "n", "detection_rate", "median_delay_min"]))
        md.append("")
        md.append(f"Overall detection {mon['overall_detection_rate']:.0%}; alerts on the {mon['clean_days']} clean line-days: {mon['clean_alerts']} ({mon['clean_alerts_per_day']:.2f} per day; by rule {mon['clean_alerts_by_rule']}). "
                  f"Example day {mon['example_line']} {mon['example_day']}: bought {mon['example_table_extremes']['bought']:.0f}, sold {mon['example_table_extremes']['sold']:.0f} shares, max |position| {mon['example_table_extremes']['max_abs_position_clips']:.2f} clips, "
                  f"max |net delta| {mon['example_table_extremes']['max_abs_delta_clips']:.2f} contracts, day P&L {fmt(mon['example_table_extremes']['pnl_day_usd'], 0)} USD, alerts: {[a['rule'] for a in mon['example_alerts']] or 'none'}.")
    md += ["", "## Reference facts read from the data", ""]
    tk = pd.DataFrame(facts["ticks"])
    md.append(table(tk, ["line", "symbol", "currency", "tick_inferred", "on_grid_share", "tick_config", "n_prices", "median_price"], 4))
    md.append("")
    md.append("Session grids (local time, modal first/last print, median prints per day): " + "; ".join(f"{k}: {v['first_print_mode']}-{v['last_print_mode']}, {v['prints_per_day_median']:.0f}" for k, v in facts["session_grids"].items()) + ".")
    md.append("")
    st = facts["issuer_status"].get("attempts", [])
    md.append("Issuer files: " + "; ".join(f"{a['source']} {a['name']}: {a['result']}" for a in st) + ".")
    open(os.path.join(R, "summary.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md[:12]))


if __name__ == "__main__":
    main()
