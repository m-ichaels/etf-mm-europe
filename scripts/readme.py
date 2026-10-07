#!/usr/bin/env python3
"""README.md from the results files, so every number in it is the run's.   python scripts/readme.py [--check]
--check: regenerate in memory and fail if README.md on disk differs (CI)."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etfmm import data as D  # noqa: E402


def f2(x, nd=1):
    if x is None:
        return "n/a"
    x = float(x)
    if np.isnan(x):
        return "n/a"
    if not np.isfinite(x):
        return "none on the grid"
    return f"{x:.{nd}f}"


def be_text(x, lo, hi, nd=1):
    """'5.8 bp [3.5, 8.1]' or 'no break-even on the grid (bootstrap [4.3, 11.5])'."""
    x = float(x)
    if np.isfinite(x):
        return f"{x:.{nd}f} bp [{f2(lo, nd)}, {f2(hi, nd)}]"
    return f"no break-even on the grid (bootstrap [{f2(lo, nd)}, {f2(hi, nd)}])"


def ci(r, key="breakeven", nd=1):
    lo, hi = r[f"{key}_lo"], r[f"{key}_hi"]
    return f"[{f2(lo, nd)}, {f2(hi, nd)}]"


def build() -> str:
    R = D.RESULTS
    lines = D.lines()
    L = list(lines)
    fv = json.load(open(os.path.join(R, "fair_value.json")))
    prem = pd.read_csv(os.path.join(R, "premium.csv")).set_index("line")
    be = json.load(open(os.path.join(R, "breakeven.json")))
    bound = json.load(open(os.path.join(R, "bound.json")))
    qs = json.load(open(os.path.join(R, "quoter_summary.json")))
    sens = pd.read_csv(os.path.join(R, "sensitivity.csv"))
    facts = json.load(open(os.path.join(R, "reference_facts.json")))
    mon = json.load(open(os.path.join(R, "monitor_faults.json")))
    kap = pd.read_csv(os.path.join(R, "kappa.csv"))
    params = D.params()
    run = qs["_run"]
    base_h = run["base_h"]
    sw = fv["contract_switches"][0]
    S = lambda line, case: sens[(sens.line == line) & (sens.case == case)].iloc[0]  # noqa: E731
    bars = facts["bars_1m"]
    ticks = {t["line"]: t for t in facts["ticks"]}
    days = int(prem.days.iloc[0])
    date0, date1 = fv["lines"][L[0]]["first_day"], fv["lines"][L[0]]["last_day"]

    # ---- headline numbers
    hl = []
    for name in L:
        r = be[name]
        tr = S(name, "quotes_track_es")
        hl.append(f"**{name}** {be_text(r['breakeven_bp'], r['breakeven_lo'], r['breakeven_hi'])} against a one-unit bound of {f2(r['bound_one_unit_bp'])} bp "
                  f"({be_text(tr.breakeven_bp, tr.breakeven_lo, tr.breakeven_hi)} when the quotes follow ES inside the minute)")
    n_clear_fixed = sum(1 for name in L if be[name]["clears_bound_one_unit"])
    n_clear_track = sum(1 for name in L if np.isfinite(S(name, "quotes_track_es").breakeven_bp) and S(name, "quotes_track_es").breakeven_bp <= be[name]["bound_one_unit_bp"])
    base_pnl = {name: be[name].get("base_pnl_bp") for name in L}
    comp = {name: qs[name]["components_bp"] for name in L}
    cap_range = (min(c["capture"] for c in comp.values()), max(c["capture"] for c in comp.values()))
    slip_range = (min(c["hedge_slip"] for c in comp.values()), max(c["hedge_slip"] for c in comp.values()))
    sd_range = (prem.prem_sd_bp.min(), prem.prem_sd_bp.max())
    wsd_range = (prem.prem_within_day_sd_bp.min(), prem.prem_within_day_sd_bp.max())
    nav_prem = {name: fv["lines"][name]["prem_nav_close_median_bp"] for name in L}
    bound_hedge = {name: bound["components_one_unit"][name]["hedge_bp"] for name in L}
    bound_range = (min(bound["one_unit_bp"].values()), max(bound["one_unit_bp"].values()))
    bound10 = (min(v["10"] for v in (bound["by_units"][n] for n in L)), max(v["10"] for v in (bound["by_units"][n] for n in L)))

    md = []
    md.append("# etf-mm-europe — a futures-hedged two-way quote on UCITS S&P 500 ETF lines: the spread that clears the creation bound, and what a fill earns")
    md.append("")
    md.append("**Question.** A market maker quotes a UCITS S&P 500 ETF on the London and Frankfurt order books and hedges every fill in the E-mini, "
              "with the FX leg hedged daily. How wide must the two-way quote be to clear the creation/redemption arbitrage bound and the hedge cost, "
              "and what does the quoter earn per fill, by line (CSPX and VUAA in USD on the LSE, VUSA in GBP on the LSE, SXR8 in EUR on Xetra)?")
    md.append("")
    md.append(f"**Answer (§Results).** On {days} days of 1-minute bars ({date0} to {date1}), with quotes fixed for each minute and a fill only when the bar trades "
              f"one tick through the quote (the pessimistic reading of a bar), the break-even half-spread is " + "; ".join(hl) + ". "
              f"The one-unit bound is {f2(bound_range[0])}–{f2(bound_range[1])} bp (fixed fee amortised over one unit, basket half-spread, E-mini half-tick and fee, one FX conversion for the GBP and EUR lines, one day of T+2/T+1 settlement financing) "
              f"and {f2(bound10[0])}–{f2(bound10[1])} bp over ten units; the hedge cost alone is {f2(list(bound_hedge.values())[0], 2)} bp. "
              f"With fixed quotes {n_clear_fixed} of the 4 lines {'clears' if n_clear_fixed == 1 else 'clear'} the one-unit bound; with quotes that track ES inside the bar {n_clear_track} of 4 do. "
              f"At the base half-spread of {base_h} bp the fixed-quote book loses {f2(-max(base_pnl.values()))} to {f2(-min(base_pnl.values()))} bp per fill: it captures "
              f"{f2(cap_range[0])}–{f2(cap_range[1])} bp against the fair at the fill and gives {f2(-slip_range[1])}–{f2(-slip_range[0])} bp back between the fill and the hedge one minute later, "
              f"because a bar that trades through a quote is mostly a bar in which the index moved. The lines sit within {f2(sd_range[0])}–{f2(sd_range[1])} bp (sd) of the ES-implied fair, "
              f"{f2(wsd_range[0])}–{f2(wsd_range[1])} bp within the day, and close {f2(min(v for v in nav_prem.values() if v is not None))}–{f2(max(v for v in nav_prem.values() if v is not None))} bp rich to the issuer's NAV-fair where a NAV exists. "
              f"The monitor's fault-injection score is {mon['overall_detection_rate']:.0%} detection within {mon['limits']['detect_window_minutes']} minutes with {mon['clean_alerts_per_day']:.2f} alerts per clean line-day.")
    md.append("")
    md.append("- *Fair value.* $E^* = I_{\\mathrm{fair}} / (\\kappa_d X)$: the E-mini with the cost of carry removed and the quarter's dividend accrual added back (the vendored "
              f"model), less the contract's richness to the cash index ({', '.join(f'{k}: {v:+.1f} bp' for k, v in fv['richness_by_contract_bp'].items())}; the September contract's two "
              f"weeks of carry and the December contract's three months are both measured, not assumed), divided by the fund/index ratio struck from the previous closes "
              f"and by the spot rate. Yahoo's continuous ES=F switched from the {sw['from_expiry']} to the {sw['to_expiry']} contract at {sw['ts'][:16]} UTC "
              f"(a {sw['one_minute_return_bp']:.0f} bp one-minute jump that the cash index confirms); every bar carries its own contract and the hedge rolls there.")
    md.append(f"- *Premium.* The four lines are within {f2(sd_range[0])}–{f2(sd_range[1])} bp (sd) of fair at the minute and {f2(prem.share_abs_gt_5bp.min() * 100, 0)}–{f2(prem.share_abs_gt_5bp.max() * 100, 0)} % of minutes are more than 5 bp away; "
              f"the premium to the issuer's NAV is persistent: CSPX closes a median {f2(nav_prem['CSPX'])} bp and SXR8 {f2(nav_prem['SXR8'])} bp above NAV-fair over the {fv['lines']['CSPX']['nav_days_available']} NAV days, "
              f"so a quoter centred on NAV would be sold to all day — the quoter here centres on where the line itself closed (kappa from the closing prints), and the `kappa=nav` row of the sensitivity table shows the cost of centring on NAV.")
    fxf = {n: S(n, "fx_hedge=fill") for n in L if lines[n]["currency"] != "USD" and len(sens[(sens.line == n) & (sens.case == "fx_hedge=fill")])}
    if fxf:
        md.append(f"- *FX.* Hedging the FX leg once a day costs the GBP and EUR lines " + " and ".join(f"{f2(-comp[n]['fx'])} bp per fill ({n})" for n in fxf) + f" at h = {base_h}: a fill arrives after the spot rate has moved the local-currency fair, "
                  f"so the cash the quoter is left holding is on the wrong side of a move that continues through the day (daily FX P&L against net flow x spot change: negative correlation). Converting each fill's cash at the next bar instead "
                  + "; ".join(f"moves the {n} break-even from {f2(be[n]['breakeven_bp'])} to {f2(fxf[n].breakeven_bp)} bp" for n in fxf) + " (the FX component at h = 3 goes from "
                  + ", ".join(f"{f2(comp[n]['fx'])} to {f2(float(pd.read_csv(os.path.join(R, 'quoter_grid.csv')).query('line == @n and case == \"fx_hedge=fill\" and h == @base_h').fx_bp.iloc[0]))} bp ({n})" for n in fxf) + ").")
    md.append(f"- *Attribution.* Per fill at h = {base_h} bp: " + "; ".join(f"{n}: capture {f2(comp[n]['capture'])}, hedge slippage {f2(comp[n]['hedge_slip'])}, FX {f2(comp[n]['fx'])}, inventory {f2(comp[n]['inventory'])}, fees {f2(comp[n]['fees'])}, total {f2(qs[n]['pnl_bp'])} bp ({qs[n]['n_fills']} fills, {f2(qs[n]['pnl_per_fill_usd'], 0)} USD per fill)" for n in L) + ". "
              "The identity cash + inventory at the closing mark = capture + slippage + FX + inventory + fees holds to 1e-6 USD on every run.")
    md.append(f"- *The two brackets.* With quotes fixed for the minute, a fill is a stale quote hit after the index moved: the quoter captures the half-spread against the bar-start fair and gives most of it back before the hedge (hedge slippage {f2(slip_range[0])} to {f2(slip_range[1])} bp per fill at h = {base_h}). "
              f"With quotes that follow the ES bar's range (`quotes_track_es`), every fill is at the minute's extreme and the mark then reverts towards the close, so the slippage turns positive and the break-even falls to the bottom of the grid; that is the optimistic reading. "
              f"A quoter re-pricing on every ES tick with a known queue position lies between the two columns; the bars cannot place it, and §Limits says so. The end-of-day choice (carry the hedged inventory, flatten at the close, redeem at NAV less the one-unit bound), the hedge delay, the inventory skew and the participation cap move the break-even less than the fill rule does (§Results).")
    md.append("")
    md.append(f"Data checked {fv['generated'][:10]}. Python package `etfmm` (numpy/pandas), {count_tests()} tests, CI runs the pipeline on the checked-in data. The faulted monitor days are simulated and said so; everything else is the replay on Yahoo's bars. "
              "1-minute bars are not a tick book: the quoter re-prices once a minute (or follows the ES bar's range in the tracking case), queue position is unknown, and the sample is 30 calendar days.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Layout")
    md.append("")
    md.append("""```
scripts/download.py     Yahoo daily bars since 2019 and 1-minute bars over the trailing 30 days (the API limit; appended on each run) for
                        CSPX.L VUAA.L VUSA.L SXR8.DE SPY ^GSPC ES=F GBPUSD=X EURUSD=X; Treasury par curve, NY Fed SOFR/EFFR, ECB ESTR,
                        BoE SONIA; the iShares product-data API (daily NAV since 2010, key facts, listings); the Vanguard professional
                        product pages (latest NAV, a short price table); data/reference/issuer_status.json records every attempt
etfmm/vendor/           copied from m-ichaels/delta-one-basis (NOTICE): the Yahoo loader, the cost-of-carry fair value, the dividend
                        accrual profile, the bill-curve interpolation, the expiry calendar
etfmm/calendar.py       LSE and Xetra sessions, minutes from the open, the US cash session
etfmm/fairvalue.py      the contract each ES bar carries (the switch inside expiry week), the implied index and its richness by contract,
                        the minute frame per line (inputs as of the bar start, with their ages), kappa from the closes and from the NAV
etfmm/reference.py      the tick each line trades on, inferred from the prints; the session grid the bars cover
etfmm/bound.py          the creation/redemption bound by unit count
etfmm/quoter.py         the quoter replay: skewed quotes, pull rules, the bar fill rule, the E-mini hedge, the daily FX conversion,
                        the end-of-day modes, the five-way attribution with its identity
etfmm/stats.py          break-even half-spread, circular block bootstrap over days
etfmm/monitor.py        the positions monitor (position, flows, delta, FX exposure, stale/stuck quotes, hedge slip, bands, drawdown,
                        reconciliation) and the fault-injection harness
scripts/                build_fair.py, run_bound.py, run_quoter.py, run_monitor.py, make_figures.py, summarize.py, readme.py, run_all.sh
configs/                lines.json (the four lines), params.json (every assumption), sources.json (the documents each fact came from)
tests/                  known-answer tests on small fixtures
data/reference/         daily bars, dividends, rates, issuer files;  data/intraday/  the 1-minute archive;  data/derived/  frames, fills, paths
results/                summary.md and the machine-written files the README is built from;  figures/  the png files
```""")
    md.append("")
    md.append("Install: `pip install -e .[test]`; `python -m pytest`; `scripts/run_all.sh [--skip-download] [--fast]` (download, fair value, bound, quoter, monitor, figures, summary, README, tests; "
              f"about {int(run['seconds'] // 60) + 2} minutes after the downloads). `python scripts/readme.py --check` fails CI when the README no longer matches the results.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Data")
    md.append("")
    md.append("| layer | source | span | notes |")
    md.append("|---|---|---|---|")
    md.append(f"| ETF lines, 1-minute | Yahoo chart API, `CSPX.L VUAA.L VUSA.L SXR8.DE`, 7-day windows over the trailing 30 days | {bars['first'][:10]} – {bars['last'][:10]}, {days + 1} trading days | "
              + "; ".join(f"{n}: {facts['session_grids'][n]['prints_per_day_median']:.0f} printed minutes a day, {prem.loc[n, 'median_volume_per_day']:,.0f} shares a day" for n in L) + "; a minute with no trade keeps a NaN close |")
    md.append(f"| hedge and FX, 1-minute | Yahoo `ES=F` (continuous front month), `GBPUSD=X`, `EURUSD=X`; `SPY`, `^GSPC` for the dividend model and the richness | same | ES prints every London minute; the FX series are indicative mids; the contract switch is detected per bar (§Method) |")
    md.append(f"| daily | the same symbols since 2019 with SPY's distributions | 2019 – {bars['last'][:10]} | SPY's dividends and its accrual profile against the index give the index dividend points |")
    md.append("| financing | US Treasury par curve 1m–1y, NY Fed SOFR and EFFR, ECB €STR, BoE SONIA | 2019 – | the carry uses bills interpolated to the contract's tenor; the bound uses SOFR for the settlement day |")
    nav_i = facts["issuer_status"]["attempts"]
    md.append(f"| issuer NAV | iShares product-data API: daily NAV of the Core S&P 500 UCITS ETF since 2010 ({[a for a in nav_i if a['name'] == 'CSPX_nav'][0]['result']}); Vanguard professional pages: the latest NAV and a short price table "
              f"({[a for a in nav_i if a['name'] == 'VUSA_page_nav'][0]['result']}, {[a for a in nav_i if a['name'] == 'VUAA_page_nav'][0]['result']}) | to {bars['last'][:10]} | "
              "the old iShares `.ajax` csv endpoints and the Vanguard investor-site json endpoints return the page html (recorded in `data/reference/issuer_old/`); the Vanguard NAV history is therefore four to five days, used as a check only |")
    md.append("| reference facts | iShares VII plc prospectus; Vanguard Funds plc prospectus (2 June 2026) and the 16 Jan 2023 creation-unit notice; LSE MIT201; Deutsche Börse Xetra trading parameters (1 Dec 2025); RTS 11 tick table | read 2026-10-07 | `configs/sources.json` quotes each passage; creation unit 60,000 shares (Vanguard, published), 50,000 (iShares, not published, assumption); creation fees are 'available from the Investment Manager' at both issuers, so the fixed fee is an assumption with a sensitivity |")
    md.append("| not available, and said so | the LSE Business Parameters tick schedule (an xlsx the pipeline could not locate), the issuers' actual creation fees and the iShares unit size, Vanguard's daily NAV history (the investor-site json endpoints return html), any order-book or tick data | — | ticks are inferred from the prints; the fees are assumptions with sensitivities; the Vanguard NAV is the page's last five days; the bar fill rule stands in for the book |")
    md.append("")
    md.append("Ticks inferred from the prints: " + "; ".join(f"{n} {ticks[n]['tick_inferred']} {ticks[n]['currency']} ({ticks[n]['on_grid_share']:.1%} of {ticks[n]['n_prices']:,} prices on the grid)" for n in L)
              + ". The RTS 11 band-6 table would put SXR8 at 0.10 EUR; the Xetra prints sit on 0.02, so the prints are used.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Method")
    md.append("")
    md.append("**Fair value.** For the E-mini $F$, financing $r$ (bills to the contract's expiry, act/360), expected index dividend points $D$ to expiry (the point-in-time forecast of SPY's distribution, grossed up by its fee, through the accrual profile measured from SPY against the index), and the contract's richness $\\rho_c$ (the median of $10^4 (I_{\\mathrm{impl}} - I)/I$ over the US cash session while $c$ is the front):")
    md.append("")
    md.append("$$I_{\\mathrm{impl}} = \\frac{F + D}{1 + r\\tau},\\qquad I_{\\mathrm{fair}} = I_{\\mathrm{impl}}\\,(1 - \\rho_c/10^4),\\qquad E^*_{\\mathrm{USD}} = \\frac{I_{\\mathrm{fair}}}{\\kappa_d},\\qquad E^* = \\frac{E^*_{\\mathrm{USD}}}{X},\\qquad \\mathrm{prem} = 10^4\\,\\frac{P - E^*}{E^*}.$$")
    md.append("")
    md.append(f"$\\kappa_d$ is index over fund price. The quoter's $\\kappa_d$ is the median over the previous {params['fair_value']['kappa_window_days']} closes of $I_{{\\mathrm{{fair}}}}/(P X)$ in the last 30 minutes of each session, each drifted to day $d$ for the fee ({lines['CSPX']['ter_bp']} bp a year), "
              "the dividend accrual between the two dates and, for the distributing line, its own ex-date. The NAV $\\kappa$ is the S&P 500 close over the issuer's NAV on the last NAV date before $d$ with the same drifts; `prem_nav` is the premium to that fair. "
              "The fair at the start of bar $t$ uses the last ES and FX bars that closed by $t$; a bar's own ES range is used only by the tracking quoter.")
    md.append("")
    md.append("**Contract.** Each ES bar's expiry is the calendar front for its New York date; inside expiry week a one-minute move larger than 40 bp whose level persists marks the switch to the next contract (confirmed here by the ratio to the cash index). Before the switch $F$ is back-adjusted by the switch ratio ($F_{\\mathrm{cont}}$) so marks are continuous; a hedge held across it pays two half-spreads and two fees per contract.")
    md.append("")
    q = params["quoter"]
    md.append(f"**Quoter.** At bar $t$: $m = E^*(1 - s\\,q/\\mathrm{{clip}}/10^4)$ with skew $s$ = {q['skew_bp_per_clip']} bp per clip of inventory; bid $= \\lfloor m(1 - h/10^4)\\rfloor_{{\\mathrm{{tick}}}}$, ask $= \\lceil m(1 + h/10^4)\\rceil_{{\\mathrm{{tick}}}}$; clip = one E-mini's worth of shares ($50F/E^*_{{\\mathrm{{USD}}}}$), the fill capped at {q['max_participation']:.0%} of the bar's volume. "
              f"No quotes in the first and last {q['skip_open_minutes']} minutes, when the last ES or FX bar is older than {q['stale_minutes']} minutes, or when ES moved more than {q['fast_market_bp']} bp over the previous bar; one side only at {q['max_inventory_clips']:.0f} clips. "
              f"**Fill rule:** the bid fills if the bar's low is at or below bid − {q['through_ticks']} tick (the price traded through the quote; the pessimistic reading of a bar with no queue information), the ask if the high is at or above ask + {q['through_ticks']} tick; the fill is at the quote. "
              "In the `quotes_track_es` case the bid follows the fair down the ES bar's low and the ask up its high before the test is applied, which is what a quoter re-pricing on every ES tick would have shown the market. "
              f"**Hedge:** the whole-contract position nearest $-qE^*_{{\\mathrm{{USD}}}}/(50F)$ at the close of the next bar, at $F \\pm$ {q['es_half_spread_ticks']} tick and {q['es_fee_usd_per_contract']} USD a contract. "
              f"**FX:** the local-currency cash is converted once a day, {q['fx_hedge_minutes_before_close']} minutes before the close, at {q['fx_half_spread_bp']} bp. ETF venue fee {q['etf_fee_bp']} bp of notional.")
    md.append("")
    md.append("**Attribution (USD).** $V = \\mathrm{cash}_{\\mathrm{USD}} + \\mathrm{cash}_{\\mathrm{loc}} X + q E^*_{\\mathrm{USD}} + \\mathrm{es}\\cdot 50F$. Spread capture is $\\sum \\mathrm{size}\\,(E^* - \\mathrm{price})X$ at the fill's fair; hedge slippage the mark change of the filled shares between the fill and the hedge plus the E-mini half-spreads; FX the local cash's $\\Delta X$ and the conversion spread; fees the venue and exchange fees; inventory everything else (the fractional contract, the overnight $\\kappa$ re-strike, the end-of-day liquidation cost). $V_{\\mathrm{end}} - V_0$ equals the sum, checked on every run.")
    md.append("")
    b = params["bound"]
    md.append(f"**Bound.** Per unit notional $N = n\\cdot\\mathrm{{unit}}\\cdot\\mathrm{{NAV}}$: fixed fee $/N$ ({b['fixed_fee_usd']} USD an order, assumption) + basket half-spread ({b['basket_half_spread_bp']} bp, assumption) + E-mini half-tick and fee per contract + one FX conversion ({b['fx_half_spread_bp']} bp, GBP and EUR lines) + {b['settlement_mismatch_days']} day of SOFR for the ETF's T+2 against the US basket's T+1. The quoter's `create_redeem` end-of-day mode redeems its inventory at fair less the one-unit bound per share.")
    md.append("")
    md.append(f"**Statistics.** P&L per fill in bp is total P&L over total fill notional. The break-even $h^*$ is the first zero crossing of that curve over the half-spread grid {run['grid']} (linear interpolation; 'none' when the curve stays below zero). Intervals: circular block bootstrap over quoting days (blocks of {params['bootstrap']['block_days']} days, {run['n_boot']} draws), $h^*$ re-solved on each draw.")
    md.append("")
    md.append("**Monitor.** The minute table carries position (shares, clips), the day's flows, the net delta (inventory at fair plus the E-mini, in USD and contracts), the FX exposure (unconverted local cash), the day's P&L and the input ages; rules in `configs/params.json`. The harness plants one fault per injection on a real day (stale ES feed with live quotes, dropped or wrong-way hedge, phantom fill, 1 % bad ES tick, FX spike, fat finger, drawdown, missed FX conversion) and scores detection within the window; clean days count false alerts.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Results")
    md.append("")
    md.append("### Where the lines trade against fair")
    md.append("")
    md.append("![premium](figures/premium.png)")
    md.append("")
    md.append("*Figure 1. Left: the premium of each line's 1-minute close to the ES-implied fair (continuous trading). Right: by time of day; the US cash open at 14:30 London is shaded.*")
    md.append("")
    md.append("| line | venue, ccy | days | minutes | mean (bp) | sd | within-day sd | q05 / median / q95 | share of minutes beyond 5 bp | median closing premium to NAV-fair (NAV days) | prints / day | shares / day |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in L:
        p = prem.loc[n]
        m = fv["lines"][n]
        md.append(f"| {n} | {p.venue}, {p.currency} | {int(p.days)} | {int(p.minutes):,} | {p.prem_mean_bp:+.2f} | {p.prem_sd_bp:.2f} | {p.prem_within_day_sd_bp:.2f} | {p.q05:+.1f} / {p.q50:+.1f} / {p.q95:+.1f} | {p.share_abs_gt_5bp:.1%} | "
                  f"{f2(m['prem_nav_close_median_bp'])} ({m['nav_days_available']}) | {p.median_prints_per_day:.0f} | {p.median_volume_per_day:,.0f} |")
    md.append("")
    md.append("### The bound and the break-even")
    md.append("")
    md.append("![pnl](figures/pnl_curve.png)")
    md.append("")
    md.append("*Figure 2. Left: P&L per fill (bp of fill notional) against the half-spread, fixed quotes, with the 95 % block-bootstrap band; dotted verticals are each line's one-unit bound. Right: total P&L over the sample, which falls as the quote widens and the fills dry up.*")
    md.append("")
    md.append(f"| line | break-even h* fixed quotes (bp) | 95 % CI | h* quotes track ES | 95 % CI | bound 1 unit | bound 10 units | hedge cost | P&L/fill at h = {base_h} | fills at h = {base_h} | clears the one-unit bound (fixed / tracking) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for n in L:
        r = be[n]
        tr = S(n, "quotes_track_es")
        clears_tr = np.isfinite(tr.breakeven_bp) and tr.breakeven_bp <= r["bound_one_unit_bp"]
        md.append(f"| {n} | {f2(r['breakeven_bp'])} | {ci(r)} | {f2(tr.breakeven_bp)} | [{f2(tr.breakeven_lo)}, {f2(tr.breakeven_hi)}] | {f2(r['bound_one_unit_bp'])} | {f2(r['bound_by_units_bp']['10'])} | {f2(r['hedge_cost_bp'], 2)} | "
                  f"{f2(r.get('base_pnl_bp'))} [{f2(r.get('base_pnl_bp_lo'))}, {f2(r.get('base_pnl_bp_hi'))}] | {qs[n]['n_fills']} | {'yes' if r['clears_bound_one_unit'] else 'no'} / {'yes' if clears_tr else 'no'} |")
    md.append("")
    bt = pd.read_csv(os.path.join(R, "bound.csv"))
    base_b = bt[(bt.case == "base") & (bt.n_units == 1)].set_index("line")
    md.append("The bound, one unit (bp): " + "; ".join(f"{n}: fixed fee {base_b.loc[n, 'fixed_fee_bp']:.2f} + basket {base_b.loc[n, 'basket_bp']:.1f} + hedge {base_b.loc[n, 'hedge_bp']:.2f} + FX {base_b.loc[n, 'fx_bp']:.1f} + settlement {base_b.loc[n, 'settlement_bp']:.2f} = {base_b.loc[n, 'bound_bp']:.2f} on {base_b.loc[n, 'notional_usd'] / 1e6:.1f}m USD" for n in L)
              + f". With the fixed fee at 500 / 5,000 USD the one-unit bound of VUSA is {[r['bound_bp'] for r in bound['sensitivity']['fixed_fee'] if r['line'] == 'VUSA' and r['fixed_fee_usd'] == 500][0]:.2f} / {[r['bound_bp'] for r in bound['sensitivity']['fixed_fee'] if r['line'] == 'VUSA' and r['fixed_fee_usd'] == 5000][0]:.2f} bp; with no settlement mismatch {[r['bound_bp'] for r in bound['sensitivity']['settlement_days'] if r['line'] == 'VUSA' and r['settlement_days'] == 0][0]:.2f} bp (`results/bound.csv`).")
    md.append("")
    md.append("### What a fill earns")
    md.append("")
    md.append("![replay](figures/replay_day.png)")
    md.append("")
    md.append(f"*Figure 3. One day of CSPX: last trade, fair, the quoter's bid and ask at h = {base_h} bp, fills, inventory and the E-mini hedge.*")
    md.append("")
    md.append(f"| line | fills | fills / day | notional (USD m) | median fill / clip (shares) | capture | hedge slippage | FX | inventory | fees | **total (bp)** | USD / fill | total USD | max inventory (clips) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in L:
        s = qs[n]
        c = s["components_bp"]
        md.append(f"| {n} | {s['n_fills']} | {s['fills_per_quoting_day']:.1f} | {s['notional_usd'] / 1e6:.1f} | {s['median_fill_shares']:.0f} / {s['median_clip_shares']:.0f} | {c['capture']:+.2f} | {c['hedge_slip']:+.2f} | {c['fx']:+.2f} | {c['inventory']:+.2f} | {c['fees']:+.2f} | **{s['pnl_bp']:+.2f}** | {s['pnl_per_fill_usd']:+.0f} | {s['pnl_usd']:+,.0f} | {s['max_abs_inventory_clips']:.1f} |")
    md.append("")
    md.append("P&L per fill by half-spread, fixed quotes (bp; fills in brackets):")
    md.append("")
    for n in L:
        g = pd.DataFrame(be[n]["grid"])
        md.append(f"- **{n}**: " + ", ".join(f"h {r.h:g}: {r.pnl_bp:+.1f} ({int(r.n_fills)})" for r in g.itertuples()))
    md.append("")
    md.append("### Sensitivity")
    md.append("")
    md.append("![sensitivity](figures/sensitivity.png)")
    md.append("")
    md.append(f"*Figure 4. Break-even half-spread by case, with bootstrap intervals; 'none' where the curve never crosses zero on the grid.*")
    md.append("")
    md.append("| case | " + " | ".join(f"{n} h*" for n in L) + " | " + " | ".join(f"{n} P&L/fill at h = {base_h}" for n in L) + " |")
    md.append("|---|" + "---|" * (2 * len(L)))
    piv = sens.pivot(index="case", columns="line", values="breakeven_bp").reindex(columns=L)
    pivp = sens.pivot(index="case", columns="line", values="pnl_bp_at_base_h").reindex(columns=L)
    order = ["base"] + [c for c in piv.index if c != "base"]
    for case in order:
        md.append(f"| {case} | " + " | ".join(f2(piv.loc[case, n]) for n in L) + " | " + " | ".join(f2(pivp.loc[case, n], 2) for n in L) + " |")
    md.append("")
    md.append("`through_ticks=0`: a touch fills. `participation`: the share of the bar's volume a fill may take. `eod`: carry the hedged inventory overnight (base), flatten at the close at 5 bp, or redeem at fair less the one-unit bound. `hedge_delay`: bars between the fill and the E-mini hedge. `kappa=nav`: quotes centred on the issuer's NAV-fair instead of the line's own closes (CSPX and SXR8, where the NAV history exists). `skew=0`: no inventory skew. `recentre=30min`: the quote mid follows an EWMA of the day's observed premium. `quotes_track_es`: the quotes re-price inside the bar along the ES bar's range.")
    md.append("")
    md.append("### Monitoring")
    md.append("")
    md.append("![monitor](figures/monitor.png)")
    md.append("")
    md.append(f"*Figure 5. Left and middle: the monitor table of {mon['example_line']} on {mon['example_day']} (position, net delta, flow, day P&L, alerts). Right: fault-injection detection rates and median delays.*")
    md.append("")
    md.append("| fault | injections | detection rate | median delay (min) |")
    md.append("|---|---|---|---|")
    for r in mon["by_fault"]:
        md.append(f"| {r['fault']} | {r['n']} | {r['detection_rate']:.0%} | {f2(r['median_delay_min'], 0)} |")
    md.append("")
    md.append(f"Alerts on the {mon['clean_days']} clean line-days: {mon['clean_alerts']} ({mon['clean_alerts_per_day']:.2f} a day; by rule {mon['clean_alerts_by_rule'] or 'none'}). "
              f"The example day: bought {mon['example_table_extremes']['bought']:.0f} and sold {mon['example_table_extremes']['sold']:.0f} shares, net flow {mon['example_table_extremes']['net_flow_end']:+.0f}, max |position| {mon['example_table_extremes']['max_abs_position_clips']:.2f} clips, max |net delta| {mon['example_table_extremes']['max_abs_delta_clips']:.2f} contracts, day P&L {f2(mon['example_table_extremes']['pnl_day_usd'], 0)} USD; the full minute table is `results/monitor_table.csv`.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Validation")
    md.append("")
    md.append("- Fair value: the implied index inverts the fair futures price exactly; the contract switch is found on a synthetic 90 bp jump in expiry week and not on a 20 bp move; the back-adjusted series is continuous; the as-of merge uses only bars closed by the grid time; the ex-dividend factor equals $1/(1 - \\mathrm{div}/P)$.")
    md.append("- Quoter: on a synthetic day whose bars swing 10 bp around a flat fair, a 3 bp quote fills both sides every bar at exactly the rounded prices and captures exactly the half-spread; a 12 bp quote never fills; the through-tick rule distinguishes a touch from a trade-through; a one-sided market accumulates inventory to the cap with one E-mini per clip; the attribution identity holds to 1e-6 with costs on; the FX line converts its cash daily; both end-of-day modes leave the book flat; stale inputs pull quotes.")
    md.append("- Bound and statistics: the bound arithmetic by component and the amortisation of the fixed fee; the break-even interpolation; the bootstrap recovers a known break-even and is reproducible; tick inference on float32 prices with 5 % off-grid prints; session minutes and the US cash window.")
    md.append("- Monitor: a clean synthetic day raises no alert; each of the nine faults is caught by its rule; the reconciliation fires only for the phantom fill.")
    md.append("")
    md.append("## Limits, stated")
    md.append("")
    md.append("- **1-minute bars are not a tick book.** A quote fixed for a minute is a one-minute-latency market maker; the bar cannot say whether the ETF's low was a taker hitting a stale quote or the whole market moving, and the trade-through rule treats every fill as the latter. The `quotes_track_es` case brackets the other side; the truth for a quoter re-pricing on every ES tick with a real queue position lies between the two columns and needs the order book.")
    md.append(f"- **30 calendar days, {days} quoting days.** The intervals are wide and the sample holds one contract switch, one Vanguard ex-date and no stress day. Yahoo keeps 30 days of 1-minute bars; the archive grows each day the downloader runs.")
    md.append("- **Fills are capped at half the bar's volume**, Yahoo's volume (on-book and reported off-book trades are not separated), and the hedge rounds to whole contracts, so the small fills of the thin lines sit unhedged until they add up to half a contract; that residual is in `inventory`.")
    md.append("- **The bound's fixed fee and basket cost are assumptions.** Both prospectuses say the charge is available from the Investment Manager; the iShares unit size is not published. The sensitivity rows show the range.")
    md.append("- **Kappa.** The quoter's fair is centred on the line's own previous closes; the issuer NAV is daily and 16:00 New York, so the NAV comparison carries the ES move between the two closes through the same model. Vanguard's NAV history from the page is four to five days.")
    md.append("- **Costs not modelled:** market-data and connectivity, capital and margin on the E-mini, the balance-sheet cost of the ETF inventory, taxes (there is no stamp duty on these Irish ETFs) and the FX forward points of a longer hedge.")
    md.append("")
    md.append("## Reproduce")
    md.append("")
    md.append("```")
    md.append("pip install -e .[test]")
    md.append("python scripts/download.py            # Yahoo, rates, issuer files (appends to the 1-minute archive)")
    md.append("python scripts/build_fair.py          # frames, premium, kappa, reference facts")
    md.append("python scripts/run_bound.py           # the bound by unit count")
    md.append("python scripts/run_quoter.py          # the grid, the cases, the bootstrap (--fast for the CI subset)")
    md.append("python scripts/run_monitor.py         # the monitor table and the fault-injection score")
    md.append("python scripts/make_figures.py && python scripts/summarize.py && python scripts/readme.py")
    md.append("python -m pytest")
    md.append("```")
    md.append("")
    md.append("## References")
    md.append("")
    md.append("- Cornell, B. and French, K. R. (1983). The pricing of stock index futures. *Journal of Futures Markets* 3(1) — the cost-of-carry fair value.")
    md.append("- Avellaneda, M. and Stoikov, S. (2008). High-frequency trading in a limit order book. *Quantitative Finance* 8(3) — inventory skew.")
    md.append("- Petajisto, A. (2017). Inefficiencies in the pricing of exchange-traded funds. *Financial Analysts Journal* 73(1) — ETF premiums against a fair value.")
    md.append("- iShares VII plc Prospectus; Vanguard Funds plc Prospectus (2 June 2026); Vanguard notice to shareholders (16 January 2023); LSE MIT201 Guide to the Trading System (Issue 15.6); Deutsche Börse Trading Parameters Xetra (1 December 2025); Commission Delegated Regulation (EU) 2017/588 (RTS 11) — `configs/sources.json`.")
    md.append("- m-ichaels/delta-one-basis (vendored fair value and loader) and m-ichaels/futures-desk-analytics (the attribution identity and the fault-injection pattern) — `etfmm/vendor/NOTICE`.")
    md.append("")
    return "\n".join(md) + "\n"


def count_tests() -> int:
    import re
    n = 0
    for fn in os.listdir(os.path.join(ROOT, "tests")):
        if fn.startswith("test_") and fn.endswith(".py"):
            n += len(re.findall(r"^def test_", open(os.path.join(ROOT, "tests", fn), encoding="utf-8").read(), flags=re.M))
    return n


def main(argv):
    text = build()
    path = os.path.join(ROOT, "README.md")
    if "--check" in argv:
        cur = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if cur != text:
            print("README.md differs from the regenerated text")
            sys.exit(1)
        print("README.md matches the results")
        return
    open(path, "w", encoding="utf-8").write(text)
    print("README.md written", len(text), "chars")


if __name__ == "__main__":
    main(sys.argv[1:])
