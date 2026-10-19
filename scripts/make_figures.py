#!/usr/bin/env python3
"""Figures from the results and derived files.   python scripts/make_figures.py   -> figures/*.png"""
from __future__ import annotations

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etfmm import data as D  # noqa: E402

FIG = os.path.join(ROOT, "figures")
COLORS = {"CSPX": "#1f77b4", "VUAA": "#2ca02c", "VUSA": "#d62728", "SXR8": "#9467bd"}
plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 130})


def fig_premium(lines):
    tod = pd.read_csv(os.path.join(D.RESULTS, "premium_tod.csv"))
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for name in lines:
        f = D.derived(f"frame_{name}")
        c = f[f.continuous & f.P.notna() & f.prem_bp.notna()]
        axes[0].hist(c.prem_bp.clip(-15, 15), bins=np.arange(-15, 15.5, 0.5), histtype="step", density=True, label=f"{name} (sd {c.prem_bp.std():.1f} bp)", color=COLORS[name])
        t = tod[tod.line == name]
        axes[1].plot(t.halfhour / 60, t.median_bp, color=COLORS[name], label=name)
        axes[1].fill_between(t.halfhour / 60, t.q25_bp, t.q75_bp, color=COLORS[name], alpha=0.12)
    axes[0].set_xlabel("premium to fair (bp), 1-minute closes, continuous trading")
    axes[0].set_ylabel("density")
    axes[0].legend(fontsize=8)
    axes[0].set_title("Premium / discount to the ES-implied fair")
    axes[1].axvspan(6.5, 8.5, color="grey", alpha=0.12, label="US cash open (14:30 London)")
    axes[1].set_xlabel("hours after the venue open (half-hour buckets)")
    axes[1].set_ylabel("median premium (bp), IQR shaded")
    axes[1].set_title("By time of day")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "premium.png"))
    plt.close(fig)


def fig_pnl_curve(lines):
    be = json.load(open(os.path.join(D.RESULTS, "breakeven.json")))
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for name in lines:
        r = be[name]
        h = np.array(r["h"])
        axes[0].plot(h, r["pnl_bp"], marker="o", ms=3, color=COLORS[name], label=f"{name}: break-even {r['breakeven_bp']:.1f} bp" if np.isfinite(r["breakeven_bp"]) else f"{name}: no break-even on the grid")
        axes[0].fill_between(h, r["pnl_bp_lo"], r["pnl_bp_hi"], color=COLORS[name], alpha=0.12)
        axes[0].axvline(r["bound_one_unit_bp"], color=COLORS[name], ls=":", lw=1)
        g = pd.DataFrame(r["grid"])
        axes[1].plot(g.h, g.pnl_usd / 1e3, marker="o", ms=3, color=COLORS[name], label=name)
    axes[0].axhline(0, color="k", lw=0.8)
    # wider quotes fill too rarely to read and their bands would set the scale; the full grid is in the method page
    shown = [p for name in lines for x, p in zip(be[name]["h"], be[name]["pnl_bp"]) if x <= 8]
    axes[0].set_xlim(0, 8.5)
    axes[0].set_ylim(min(shown) - 1.5, max(shown) + 1.5)
    axes[0].set_xlabel("half-spread h (bp)")
    axes[0].set_ylabel("P&L per fill (bp of fill notional), 95% block-bootstrap band")
    axes[0].set_title("P&L per fill against the half-spread; dotted: one-unit creation bound")
    axes[0].legend(fontsize=7.5, loc="upper left")
    axes[1].axhline(0, color="k", lw=0.8)
    axes[1].set_xlabel("half-spread h (bp)")
    axes[1].set_ylabel("total P&L over the sample (kUSD)")
    axes[1].set_title("Total P&L: fewer fills as the quote widens")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "pnl_curve.png"))
    plt.close(fig)


def fig_replay_day(lines, line="CSPX"):
    path = D.derived(f"path_{line}")
    path["ts"] = pd.to_datetime(path.ts, utc=True)
    fills = D.derived(f"fills_{line}")
    fills["ts"] = pd.to_datetime(fills.ts, utc=True)
    days = sorted(path[path.bid.notna()].date.unique())
    day = days[len(days) // 2]
    p = path[(path.date == day) & path.cont]
    f = fills[fills.date == day]
    t = p.ts.dt.tz_convert("Europe/London")
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    axes[0].plot(t, p.P, color="grey", lw=0.8, label="last trade (1-min close)")
    axes[0].plot(t, p.fair, color="k", lw=1.0, label="fair (ES-implied, kappa from the closes)")
    axes[0].plot(t, p.bid, color=COLORS[line], lw=0.7, alpha=0.8, label="bid / ask")
    axes[0].plot(t, p.ask, color=COLORS[line], lw=0.7, alpha=0.8)
    if len(f):
        buys, sells = f[f.side == 1], f[f.side == -1]
        axes[0].scatter(buys.ts.dt.tz_convert("Europe/London"), buys.price, marker="^", color="green", s=28, zorder=5, label=f"buys ({len(buys)})")
        axes[0].scatter(sells.ts.dt.tz_convert("Europe/London"), sells.price, marker="v", color="red", s=28, zorder=5, label=f"sells ({len(sells)})")
    axes[0].set_title(f"{line} on {day}: fair, quotes and fills (half-spread {json.load(open(os.path.join(D.RESULTS, 'quoter_summary.json')))[line]['h_bp']} bp)")
    axes[0].set_ylabel("price")
    axes[0].legend(fontsize=8, ncol=3)
    axes[1].step(t, p.q / p["clip"].ffill().bfill(), where="post", color=COLORS[line], label="inventory (clips)")
    axes[1].step(t, -p.es, where="post", color="orange", label="-ES hedge (contracts)")
    axes[1].set_ylabel("clips / contracts")
    axes[1].legend(fontsize=8)
    axes[1].set_xlabel("London time")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "replay_day.png"))
    plt.close(fig)


def fig_sensitivity(lines):
    s = pd.read_csv(os.path.join(D.RESULTS, "sensitivity.csv"))
    cases = [c for c in s.case.unique()]
    fig, ax = plt.subplots(figsize=(11, 4))
    w = 0.8 / len(lines)
    x = np.arange(len(cases))
    for i, name in enumerate(lines):
        v = s[s.line == name].set_index("case").reindex(cases)
        raw = v.breakeven_bp.to_numpy(float)
        y = np.where(np.isfinite(raw), raw, np.nan)
        lo = np.maximum(y - v.breakeven_lo.to_numpy(), 0)
        hi = np.maximum(v.breakeven_hi.replace(np.inf, np.nan).to_numpy() - y, 0)
        ax.bar(x + i * w, np.nan_to_num(y, nan=0), w, color=COLORS[name], label=name, yerr=[np.nan_to_num(lo), np.nan_to_num(hi)], capsize=2, error_kw={"lw": 0.7})
        for xi, yi in zip(x + i * w, raw):
            if not np.isfinite(yi):
                ax.text(xi, 0.3, "none" if yi == np.inf else "n/a", rotation=90, fontsize=7, ha="center", va="bottom")
    ax.set_xticks(x + w * (len(lines) - 1) / 2)
    ax.set_xticklabels(cases, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("break-even half-spread (bp)")
    ax.set_title("Break-even half-spread by fill rule, participation, end-of-day mode, hedge delay, kappa source, skew and recentring")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "sensitivity.png"))
    plt.close(fig)


def fig_monitor(lines):
    tab = pd.read_csv(os.path.join(D.RESULTS, "monitor_table.csv"))
    mf = json.load(open(os.path.join(D.RESULTS, "monitor_faults.json")))
    tab["ts"] = pd.to_datetime(tab.ts, utc=True).dt.tz_convert("Europe/London")
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), gridspec_kw={"width_ratios": [2, 2, 1.6]})
    axes[0].plot(tab.ts, tab.position_clips, color=COLORS["CSPX"], label="position (clips)")
    axes[0].plot(tab.ts, tab.delta_clips, color="orange", label="net delta (ES contracts)")
    axes[0].plot(tab.ts, tab.net_flow / tab.position_shares.abs().replace(0, np.nan).max(), color="grey", lw=0.8, label="net flow (scaled)")
    axes[0].set_title(f"Monitor, {mf['example_line']} {mf['example_day']}: position, delta, flow")
    axes[0].legend(fontsize=7.5)
    axes[0].tick_params(axis="x", rotation=30)
    axes[1].plot(tab.ts, tab.pnl_day_usd, color="k", label="day P&L (USD, marked at fair)")
    al = tab[tab.alerts.fillna("") != ""]
    if len(al):
        axes[1].scatter(al.ts, al.pnl_day_usd, color="red", s=20, zorder=5, label="alerts")
    axes[1].set_title("Day P&L and alerts")
    axes[1].legend(fontsize=7.5)
    axes[1].tick_params(axis="x", rotation=30)
    bf = pd.DataFrame(mf["by_fault"])
    axes[2].barh(bf.fault, bf.detection_rate, color="#555")
    for y, (r, d) in enumerate(zip(bf.detection_rate, bf.median_delay_min)):
        axes[2].text(min(r, 0.95) + 0.01, y, f"{r:.0%}, {d:.0f} min" if np.isfinite(d) else f"{r:.0%}", va="center", fontsize=7)
    axes[2].set_xlim(0, 1.3)
    axes[2].set_title(f"Fault injection: detection within {mf['limits']['detect_window_minutes']} min")
    axes[2].set_xlabel("detection rate (median delay)")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "monitor.png"))
    plt.close(fig)


def main():
    os.makedirs(FIG, exist_ok=True)
    lines = list(D.lines())
    fig_premium(lines)
    fig_pnl_curve(lines)
    fig_replay_day(lines)
    fig_sensitivity(lines)
    if os.path.exists(os.path.join(D.RESULTS, "monitor_table.csv")):
        fig_monitor(lines)
    print("figures:", sorted(os.listdir(FIG)))


if __name__ == "__main__":
    main()
