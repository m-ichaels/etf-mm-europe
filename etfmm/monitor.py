"""The positions monitor for the quoter's book, and the fault-injection harness that scores it.

The monitor reads what a desk's monitor reads: the position and hedge path minute by minute, the fills, the hedges, the
input feeds and their ages, the quotes.  Each row of its table carries the position (shares, clips), the day's flows
(bought, sold, net), the instantaneous delta (ETF inventory marked at fair plus the E-mini hedge, in USD and in contracts),
the FX exposure (unconverted local-currency cash, in USD), the day's P&L and the alerts raised.

Rules (configs/params.json "monitor"): POSITION_LIMIT, DELTA_UNHEDGED (a net delta beyond the limit for several bars),
FX_EXPOSURE, STALE_INPUT (quotes live on an input older than the limit), STUCK_QUOTE (quotes unchanged while the fair moved),
HEDGE_SLIP (a hedge executed far from the fill's reference), PREMIUM_BAND (a print far from fair: a feed error or a
dislocation), FAT_FINGER (a fill larger than the clip limit), DRAWDOWN (the day's P&L below its high by more than the limit),
RECON (end of day: the position implied by the fills differs from the position held).

The harness takes the real replay of each day, plants one fault from the catalogue at a random minute, and scores: caught if
an alert of the fault's rule arrives within detect_window_minutes; clean days count false alerts.  The faulted paths are
simulated and the README says so; the clean paths are the replay on the real bars.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

RULE_FOR_FAULT = {"stale_feed": ["STALE_INPUT", "STUCK_QUOTE"], "hedge_dropped": ["DELTA_UNHEDGED"], "wrong_side_hedge": ["DELTA_UNHEDGED"],  # the hedge channel down for 15 min
                  "phantom_fill": ["RECON", "DELTA_UNHEDGED"], "bad_es_price": ["PREMIUM_BAND"], "fx_spike": ["PREMIUM_BAND", "FX_EXPOSURE"],
                  "fat_finger": ["FAT_FINGER", "POSITION_LIMIT"], "drawdown": ["DRAWDOWN"], "fx_unhedged": ["FX_EXPOSURE"]}
FAULTS = list(RULE_FOR_FAULT)


@dataclass
class Alert:
    ts: object
    rule: str
    detail: str


def day_table(path: pd.DataFrame, fills: pd.DataFrame, hedges: pd.DataFrame, mp: dict, mult: float = 50.0, usd_line: bool = True) -> tuple[pd.DataFrame, list]:
    """The monitor table and the alerts for one day's path (rows in time order, one day)."""
    P = path.reset_index(drop=True)
    n = len(P)
    f = fills[fills.ts.isin(P.ts)] if len(fills) else fills
    h = hedges[hedges.ts.isin(P.ts)] if len(hedges) else hedges
    bought = np.zeros(n)
    sold = np.zeros(n)
    fill_clips = np.zeros(n)
    if len(f):
        pos = P.ts.searchsorted(f.ts.to_numpy())
        for i, s, sz, clip in zip(pos, f.side.to_numpy(), f["size"].to_numpy(), f["clip"].to_numpy()):
            if i < n:
                (bought if s == 1 else sold)[i] += sz
                fill_clips[i] = max(fill_clips[i], sz / clip if np.isfinite(clip) and clip > 0 else 0)
    clip = P["clip"].ffill().bfill().fillna(1.0).to_numpy()
    q = P.q.to_numpy(float)
    es = P.es.to_numpy(float)
    F = P.F.to_numpy(float)
    delta_usd = q * P.fair_usd.ffill().to_numpy() + es * mult * pd.Series(F).ffill().to_numpy()
    delta_clips = delta_usd / (mult * pd.Series(F).ffill().to_numpy())
    fx_usd = (P.cash_loc * P.X).to_numpy(float) if not usd_line else np.zeros(n)
    V = P.V.to_numpy(float)
    pnl_day = V - (V[np.isfinite(V)][0] if np.isfinite(V).any() else 0.0)
    live = P.bid.notna().to_numpy() | P.ask.notna().to_numpy()
    tab = pd.DataFrame({"ts": P.ts, "position_shares": q, "position_clips": q / clip, "bought": bought.cumsum(), "sold": sold.cumsum(), "net_flow": (bought - sold).cumsum(),
                        "es_contracts": es, "delta_usd": delta_usd, "delta_clips": delta_clips, "fx_exposure_usd": fx_usd, "pnl_day_usd": pnl_day,
                        "F_age": P.F_age, "X_age": P.X_age, "quotes_live": live, "bid": P.bid, "ask": P.ask, "fair": P.fair, "P": P.P})
    # rules
    alerts: list[Alert] = []
    last = {}

    def alert(i, rule, detail, cooldown=15):
        if i - last.get(rule, -10**9) < cooldown:
            return
        last[rule] = i
        alerts.append(Alert(P.ts.iloc[i], rule, detail))

    persist = 0
    hi = -np.inf
    fair = P.fair.to_numpy(float)
    bid, ask = P.bid.to_numpy(float), P.ask.to_numpy(float)
    for i in range(n):
        if abs(q[i]) > mp["position_limit_clips"] * clip[i]:
            alert(i, "POSITION_LIMIT", f"{q[i]:.0f} shares = {q[i] / clip[i]:.1f} clips against {mp['position_limit_clips']}")
        if np.isfinite(delta_clips[i]) and abs(delta_clips[i]) > mp["delta_limit_clips"]:
            persist += 1
            if persist >= mp["delta_persist_bars"]:
                alert(i, "DELTA_UNHEDGED", f"net delta {delta_clips[i]:+.2f} contracts for {persist} bars")
        else:
            persist = 0
        if abs(fx_usd[i]) > mp["fx_exposure_limit_usd"]:
            alert(i, "FX_EXPOSURE", f"unconverted cash {fx_usd[i] / 1e6:+.2f}m USD")
        if live[i] and (P.F_age.iloc[i] > mp["stale_minutes"] or P.X_age.iloc[i] > mp["stale_minutes"]):
            alert(i, "STALE_INPUT", f"quotes live with ES age {P.F_age.iloc[i]:.0f} min, FX age {P.X_age.iloc[i]:.0f} min", cooldown=5)
        k = mp["stale_minutes"]
        if i >= k and live[i] and live[i - k] and np.isfinite(bid[i]) and bid[i] == bid[i - k] and np.isfinite(ask[i]) and ask[i] == ask[i - k] \
                and np.isfinite(fair[i]) and np.isfinite(fair[i - k]) and abs(fair[i] / fair[i - k] - 1) * 1e4 > mp["stuck_quote_bp"]:
            alert(i, "STUCK_QUOTE", f"quotes unchanged for {k} min while fair moved {abs(fair[i] / fair[i - k] - 1) * 1e4:.0f} bp", cooldown=5)
        if np.isfinite(P.P.iloc[i]) and np.isfinite(fair[i]) and abs(P.P.iloc[i] / fair[i] - 1) * 1e4 > mp["premium_band_bp"]:
            alert(i, "PREMIUM_BAND", f"print {P.P.iloc[i]:.4f} is {(P.P.iloc[i] / fair[i] - 1) * 1e4:+.0f} bp from fair", cooldown=5)
        if fill_clips[i] > mp["fat_finger_clips"]:
            alert(i, "FAT_FINGER", f"fill of {fill_clips[i]:.1f} clips", cooldown=0)
        if np.isfinite(pnl_day[i]):
            hi = max(hi, pnl_day[i])
            if hi - pnl_day[i] > mp["drawdown_usd"]:
                alert(i, "DRAWDOWN", f"{hi - pnl_day[i]:,.0f} USD below the day's high", cooldown=30)
    if len(h) and len(f):
        for r in h.itertuples():
            if abs(getattr(r, "F_exec") / getattr(r, "F_mid") - 1) * 1e4 > mp["hedge_slip_bp"]:
                i = int(P.ts.searchsorted(r.ts))
                alert(min(i, n - 1), "HEDGE_SLIP", f"hedge at {r.F_exec:.2f} against reference {r.F_mid:.2f}", cooldown=0)
    # end of day reconciliation: position from the day's fills against the path
    q0 = q[0] - (bought[0] - sold[0])
    implied = q0 + (bought - sold).sum()
    if abs(implied - q[-1]) > 0.5:
        alert(n - 1, "RECON", f"fills imply {implied:.0f} shares, book holds {q[-1]:.0f}", cooldown=0)
    tab["alerts"] = ""
    for a_ in alerts:
        i = int(P.ts.searchsorted(a_.ts))
        tab.loc[min(i, n - 1), "alerts"] = (tab.loc[min(i, n - 1), "alerts"] + " " + a_.rule).strip()
    return tab, alerts


def inject(path: pd.DataFrame, fills: pd.DataFrame, hedges: pd.DataFrame, fault: str, t0: int, mult: float = 50.0, usd_line: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """A faulted copy of one day's (path, fills, hedges), the fault starting at row t0."""
    P = path.reset_index(drop=True).copy()
    f = fills.copy()
    h = hedges.copy()
    n = len(P)
    rng = np.arange(t0, min(n, t0 + 12))
    clip = float(P["clip"].ffill().bfill().fillna(1.0).iloc[t0])
    if fault == "stale_feed":  # the ES feed freezes for 12 minutes but the quotes stay live
        P.loc[rng, "F_age"] = np.arange(1, len(rng) + 1) + 1.0
        P.loc[rng, "F"] = P.F.iloc[t0 - 1] if t0 > 0 else P.F.iloc[t0]
        P.loc[rng, "fair"] = P.fair.iloc[t0 - 1] if t0 > 0 else P.fair.iloc[t0]
        P.loc[rng, "fair_usd"] = P.fair_usd.iloc[t0 - 1] if t0 > 0 else P.fair_usd.iloc[t0]
        P.loc[rng, "bid"] = P.bid.ffill().iloc[t0]
        P.loc[rng, "ask"] = P.ask.ffill().iloc[t0]
        # the stuck quotes sit on a moving market: make the fair reference move by 15 bp in the frozen window
        true_fair = P.fair.iloc[t0 - 1] * (1 + 15e-4) if t0 > 0 else P.fair.iloc[t0] * (1 + 15e-4)
        P.loc[min(n - 1, t0 + 11), "fair"] = true_fair
    elif fault in ("hedge_dropped", "wrong_side_hedge"):
        # the hedge channel is down for 15 minutes: hedges in the window are dropped (or sent with the wrong sign); the first
        # hedge after the window re-targets the whole position, as the quoter's target rule does
        t_end = P.ts.iloc[t0] + pd.Timedelta(minutes=15)
        hh = h[(h.ts >= P.ts.iloc[t0]) & (h.ts < t_end)]
        if len(hh) == 0:  # a quiet window: one clip bought and left unhedged for the window
            after = h[h.ts >= t_end]
            j = int(P.ts.searchsorted(after.ts.iloc[0])) if len(after) else n
            P.loc[t0:j - 1, "q"] = P.q.iloc[t0:j] + clip
        else:
            after = h[h.ts >= t_end]
            j = int(P.ts.searchsorted(after.ts.iloc[0])) if len(after) else n
            shift = hh.d_es.sum() if fault == "hedge_dropped" else 2 * hh.d_es.sum()
            i = int(P.ts.searchsorted(hh.ts.iloc[0]))
            P.loc[i:j - 1, "es"] = P.es.iloc[i:j] - shift
            h = h[~h.ts.isin(hh.ts)] if fault == "hedge_dropped" else h.assign(d_es=np.where(h.ts.isin(hh.ts), -h.d_es, h.d_es))
    elif fault == "phantom_fill":  # the position feed shows a buy that no quote produced
        P.loc[t0:, "q"] = P.q.iloc[t0:] + clip
    elif fault == "bad_es_price":  # one ES tick 1 % off
        P.loc[t0, "F"] = P.F.iloc[t0] * 1.01
        P.loc[t0, "fair"] = P.fair.iloc[t0] * 1.01
        P.loc[t0, "fair_usd"] = P.fair_usd.iloc[t0] * 1.01
    elif fault == "fx_spike":  # the FX feed prints 1 % off for one bar (a USD line has no FX leg: the fault is the fair)
        P.loc[t0, "X"] = P.X.iloc[t0] * 1.01
        P.loc[t0, "fair"] = P.fair.iloc[t0] / 1.01
    elif fault == "fat_finger":
        sz = 5 * clip
        P.loc[t0:, "q"] = P.q.iloc[t0:] + sz
        row = {"ts": P.ts.iloc[t0], "side": 1, "size": sz, "price": P.fair.iloc[t0], "fair": P.fair.iloc[t0], "X": P.X.iloc[t0], "clip": clip, "capture_usd": 0.0, "notional_usd": sz * P.fair.iloc[t0] * P.X.iloc[t0]}
        f = pd.concat([f, pd.DataFrame([row])], ignore_index=True).sort_values("ts")
    elif fault == "drawdown":
        P.loc[t0:, "V"] = P.V.iloc[t0:] - 60000.0
    elif fault == "fx_unhedged":  # the daily FX conversion did not happen: 3m of local cash left unconverted
        P.loc[t0:, "cash_loc"] = P.cash_loc.iloc[t0:] - 3e6 / max(P.X.iloc[t0], 1e-9)
    return P, f, h


def score(paths: dict, fills: dict, hedges: dict, lines: dict, mp: dict, n_days_per_fault: int = 8, seed: int = 0, mult: float = 50.0) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Clean days: alerts per rule.  Faulted days: detection and delay per fault type.  Returns (clean alerts, fault scores,
    per-injection records)."""
    rng = np.random.default_rng(seed)
    clean_rows, fault_rows, inj = [], [], []
    for name, cfg in lines.items():
        P = paths[name]
        usd = cfg["currency"] == "USD"
        days = sorted(P.date.unique())
        for d in days:
            pd_ = P[P.date == d]
            if pd_.q.notna().sum() == 0 or not pd_.cont.any():
                continue
            tab, al = day_table(pd_, fills[name], hedges[name], mp, mult, usd)
            for a_ in al:
                clean_rows.append({"line": name, "date": d, "ts": a_.ts, "rule": a_.rule, "detail": a_.detail})
        quoting_days = [d for d in days if P[(P.date == d) & P.cont].bid.notna().any()]
        for fault in FAULTS:
            if fault in ("fx_spike", "fx_unhedged") and usd:
                continue
            for d in rng.choice(quoting_days, size=min(n_days_per_fault, len(quoting_days)), replace=False):
                pd_ = P[P.date == d].reset_index(drop=True)
                cont_idx = np.where(pd_.cont.to_numpy() & pd_.bid.notna().to_numpy())[0]
                if len(cont_idx) < 60:
                    continue
                t0 = int(rng.choice(cont_idx[30:-20]))
                Pf, ff, hf = inject(pd_, fills[name][fills[name].ts.isin(pd_.ts)], hedges[name][hedges[name].ts.isin(pd_.ts)], fault, t0, mult, usd)
                _, al_f = day_table(Pf, ff, hf, mp, mult, usd)
                _, al_c = day_table(pd_, fills[name][fills[name].ts.isin(pd_.ts)], hedges[name][hedges[name].ts.isin(pd_.ts)], mp, mult, usd)
                t_fault = pd_.ts.iloc[t0]
                clean_set = {(a.rule, a.ts) for a in al_c}
                new = [a for a in al_f if (a.rule, a.ts) not in clean_set and a.rule in RULE_FOR_FAULT[fault]]
                window = pd.Timedelta(minutes=mp["detect_window_minutes"])
                hits = [a for a in new if t_fault <= pd.Timestamp(a.ts) <= t_fault + window] or ([a for a in new if a.rule == "RECON"] if "RECON" in RULE_FOR_FAULT[fault] else [])
                delay = min((pd.Timestamp(a.ts) - t_fault).total_seconds() / 60 for a in hits) if hits else np.nan
                inj.append({"line": name, "date": d, "fault": fault, "t0": str(t_fault), "caught": bool(hits), "delay_min": delay,
                            "rule": hits[0].rule if hits else None, "detail": hits[0].detail if hits else None})
    inj = pd.DataFrame(inj)
    clean = pd.DataFrame(clean_rows)
    if len(inj):
        fault_rows = inj.groupby(["line", "fault"]).agg(n=("caught", "size"), caught=("caught", "sum"), detection_rate=("caught", "mean"), median_delay_min=("delay_min", "median")).reset_index()
    return clean, pd.DataFrame(fault_rows), inj
