"""The two-way quoter, replayed on 1-minute bars, hedged in the E-mini, FX hedged daily.

Quotes.  At the start of bar t the quoter knows the fair E*(t) (from the ES and FX bars that closed by t) and its inventory q.
    mid_q = E* (1 - s q/clip / 1e4)                       inventory skew: s bp per clip of inventory, both quotes shift against it
    bid   = floor_tick( mid_q (1 - h/1e4) ),  ask = ceil_tick( mid_q (1 + h/1e4) )      half-spread h bp, rounded away
    size  = clip = one E-mini's worth of shares (50 F / E*_USD), capped at max_participation x the bar's volume
Pull rules: no quotes when an input is stale (last ES or FX bar older than stale_minutes), when the E-mini moved more than
fast_market_bp over the last bar, in the first/last minutes of the session, outside continuous trading; one side only once
|q| reaches max_inventory_clips.

Fills (the bar rule, stated).  The bid is filled in bar t if the bar's low is at or below bid - through_ticks x tick: the price
has to trade THROUGH the quote by `through_ticks` (default 1), the pessimistic reading of a bar that cannot say where in the
queue the quote sat.  Symmetrically for the ask with the high.  The fill price is the quote.  Both sides can fill in one bar.

Hedge.  Every fill is hedged in the E-mini at the close of the next bar (hedge_delay_bars = 1): the target is the whole-contract
position nearest to -q E*_USD / (50 F), traded at F plus/minus half a tick and the fee.  Across Yahoo's contract switch the
hedge is rolled (two half-spreads and two fees per contract) and the marks use the back-adjusted series F_cont.
FX.  The local-currency cash from ETF fills is converted to USD once a day at fx_hedge_time_local, at half a spread.

Marks and attribution (USD).  V = cash_USD + cash_loc X + q E*_USD + es 50 F.  Over the replay
    V_end - V_0 = spread capture + hedge slippage + FX + inventory + fees        (an identity, checked to 1e-6)
    spread capture  sum over fills of size (E*_loc - price) X at the fill bar's fair
    hedge slippage  the mark change of the filled shares between the fill bar and the hedge execution, plus the ES half-spreads
    FX              cash_loc dX between fills and the daily conversion, plus the FX half-spread
    inventory       the hedged book's mark-to-mark less what hedge slippage took: the fractional contract, the overnight
                    kappa re-strike, the fair's non-ES moves, and the end-of-day liquidation cost in the flatten/redeem modes
    fees            ETF venue fee per fill and ES commissions
End of day: carry (inventory kept, hedged, marked at fair), flatten_close (sold back at the closing price less a half-spread),
create_redeem (redeemed at fair less the one-unit creation/redemption bound per share).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import calendar as CAL


@dataclass
class QuoterParams:
    half_spread_bp: float = 3.0
    skew_bp_per_clip: float = 1.0
    max_inventory_clips: float = 5.0
    through_ticks: int = 1
    max_participation: float = 0.5
    skip_open_minutes: int = 5
    skip_close_minutes: int = 5
    stale_minutes: float = 3.0
    fast_market_bp: float = 15.0
    hedge_delay_bars: int = 1
    eod: str = "carry"
    etf_fee_bp: float = 0.3
    es_fee_usd: float = 1.40
    es_half_spread_ticks: float = 0.5
    es_tick: float = 0.25
    es_multiplier: float = 50.0
    fx_half_spread_bp: float = 0.5
    fx_hedge_minutes_before_close: int = 6
    flatten_half_spread_bp: float = 5.0
    track_es: bool = False  # True: the quotes are re-priced within the bar as ES moves (the ES bar's high/low), see module doc
    redeem_cost_bp: float = 5.0
    recentre_halflife_min: float = 0.0  # > 0: shift the quote mid by an EWMA of the observed premium of the day's prints
    fair_column: str = "fair"
    tick: float = 0.01
    currency: str = "USD"
    venue: str = "LSE"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_params(cls, params: dict, cfg: dict, **over) -> "QuoterParams":
        q, fv = params["quoter"], params["fair_value"]
        kw = dict(half_spread_bp=q["base_half_spread_bp"], skew_bp_per_clip=q["skew_bp_per_clip"], max_inventory_clips=q["max_inventory_clips"],
                  through_ticks=q["through_ticks"], max_participation=q["max_participation"], skip_open_minutes=q["skip_open_minutes"],
                  skip_close_minutes=q["skip_close_minutes"], stale_minutes=q["stale_minutes"], fast_market_bp=q["fast_market_bp"],
                  hedge_delay_bars=q["hedge_delay_bars"], eod=q["eod"], etf_fee_bp=q["etf_fee_bp"], es_fee_usd=q["es_fee_usd_per_contract"],
                  es_half_spread_ticks=q["es_half_spread_ticks"], es_tick=fv["futures_tick"], es_multiplier=fv["futures_multiplier"],
                  fx_half_spread_bp=q["fx_half_spread_bp"], fx_hedge_minutes_before_close=q["fx_hedge_minutes_before_close"], flatten_half_spread_bp=q["flatten_half_spread_bp"],
                  track_es=q.get("track_es", False), recentre_halflife_min=q.get("recentre_halflife_min", 0.0), tick=cfg["tick"], currency=cfg["currency"], venue=cfg["venue"])
        kw.update(over)
        return cls(**kw)


def prepare(frame: pd.DataFrame, p: QuoterParams) -> dict:
    """The arrays the replay loop reads, in row order (the frame is one row per minute of each day's grid, days in order)."""
    f = frame.sort_values(["date", "ts"]).reset_index(drop=True)
    fair_loc = f[p.fair_column].to_numpy(float)
    fair_usd = (f[p.fair_column] * f.X).to_numpy(float)
    X = f.X.to_numpy(float)
    Fc = f.F_cont.to_numpy(float)
    # marking series: forward-filled so a position is always marked; quoting uses the raw availability through the ages
    def ffill(a):
        s = pd.Series(a)
        return s.ffill().to_numpy(float)
    day = pd.factorize(f.date)[0]
    n_sess = CAL.session_length_minutes(p.venue)
    fx_minute = n_sess - p.fx_hedge_minutes_before_close
    minute = f.minute.to_numpy()
    cont = f.continuous.to_numpy() & (minute >= p.skip_open_minutes) & (minute < n_sess - p.skip_close_minutes)
    # last quoting bar of each day
    is_last = np.zeros(len(f), bool)
    for d in np.unique(day):
        idx = np.where((day == d) & cont)[0]
        if len(idx):
            is_last[idx[-1]] = True
    Fc_m = ffill(Fc)
    es_ret = np.zeros(len(f))
    with np.errstate(invalid="ignore", divide="ignore"):
        r = Fc_m[1:] / Fc_m[:-1] - 1
    es_ret[1:] = np.where(day[1:] == day[:-1], r, 0.0)
    es_ret = np.nan_to_num(es_ret)
    return {"n": len(f), "ts": f.ts.to_numpy(), "date": f.date.to_numpy(), "day": day, "minute": minute, "cont": cont, "is_last": is_last,
            "is_fx": (minute == fx_minute), "fair_loc": fair_loc, "fair_usd": fair_usd, "fair_loc_m": ffill(fair_loc), "fair_usd_m": ffill(fair_usd),
            "X": X, "X_m": ffill(X), "Fc": Fc, "Fc_m": Fc_m, "F_age": f.F_age_min.to_numpy(float), "X_age": f.X_age_min.to_numpy(float),
            "P": f.P.to_numpy(float), "high": f.high.to_numpy(float), "low": f.low.to_numpy(float), "volume": np.nan_to_num(f.volume.to_numpy(float)),
            "switch": f.es_switch.to_numpy(bool), "es_ret": es_ret, "has_print": f.P.notna().to_numpy(),
            "Fh": f.F_bar_high.to_numpy(float) if "F_bar_high" in f else np.full(len(f), np.nan), "Fl": f.F_bar_low.to_numpy(float) if "F_bar_low" in f else np.full(len(f), np.nan)}


def _floor(x: float, tick: float) -> float:
    return math.floor(x / tick + 1e-9) * tick


def _ceil(x: float, tick: float) -> float:
    return math.ceil(x / tick - 1e-9) * tick


def replay(a: dict, p: QuoterParams, record_path: bool = False) -> dict:
    """Run the quoter over the prepared arrays.  Returns fills, hedges, the per-day attribution and the totals."""
    n = a["n"]
    mult, hs_es = p.es_multiplier, p.es_half_spread_ticks * p.es_tick
    usd_line = p.currency == "USD"
    q = 0.0
    es = 0
    cash_loc = 0.0
    cash_usd = 0.0
    pending: list = []  # (ref_row, dq, exec_row)
    nd = int(a["day"].max()) + 1
    comp = {k: np.zeros(nd) for k in ("capture", "hedge_slip", "fx", "inventory", "fees")}
    n_fills = np.zeros(nd, int)
    notional = np.zeros(nd)
    fills, hedges = [], []
    path = {k: np.full(n, np.nan) for k in ("q", "es", "cash_loc", "cash_usd", "bid", "ask", "V", "clip")} if record_path else None
    quoted = np.zeros(nd, int)
    pulled = np.zeros(nd, int)
    fair_m, fusd_m, X_m, Fc_m = a["fair_loc_m"], a["fair_usd_m"], a["X_m"], a["Fc_m"]
    day = a["day"]
    V_start = None
    ew_alpha = 1 - math.exp(-math.log(2) / p.recentre_halflife_min) if p.recentre_halflife_min > 0 else 0.0
    ew_prem = 0.0

    def value(t):
        return cash_usd + cash_loc * X_m[t] + q * fusd_m[t] + es * mult * Fc_m[t]

    def hedge_now(t, due):
        nonlocal es, cash_usd
        d = day[t]
        if not np.isfinite(Fc_m[t]) or not np.isfinite(fusd_m[t]):
            return False
        target = -int(round(q * fusd_m[t] / (mult * Fc_m[t]))) if q != 0 else 0
        d_es = target - es
        if d_es != 0:
            F_exec = Fc_m[t] + math.copysign(hs_es, d_es)
            cash_usd -= d_es * mult * F_exec
            cost = abs(d_es) * hs_es * mult
            fee = abs(d_es) * p.es_fee_usd
            cash_usd -= fee
            comp["hedge_slip"][d] -= cost
            comp["fees"][d] -= fee
            es = target
            hedges.append({"row": t, "ts": a["ts"][t], "d_es": d_es, "F_exec": F_exec, "F_mid": Fc_m[t], "cost_usd": cost, "fee_usd": fee, "es_after": es, "q": q})
        for (ref_usd, dq, _) in due:
            delta = dq * (fusd_m[t] - ref_usd)
            comp["hedge_slip"][d] += delta
            comp["inventory"][d] -= delta
        return True

    for t in range(n):
        d = day[t]
        if V_start is None and np.isfinite(fusd_m[t]) and np.isfinite(Fc_m[t]) and np.isfinite(X_m[t]):
            V_start = value(t)
        if ew_alpha > 0:
            if t == 0 or day[t] != day[t - 1]:
                ew_prem = 0.0  # the kappa re-strike resets the level each day
            elif a["has_print"][t - 1] and np.isfinite(a["fair_loc"][t - 1]):
                ew_prem += ew_alpha * ((a["P"][t - 1] - a["fair_loc"][t - 1]) / a["fair_loc"][t - 1] - ew_prem)
        # 1. marks over the bar that just ended (positions held during bar t-1)
        if t > 0 and np.isfinite(fusd_m[t]) and np.isfinite(fusd_m[t - 1]) and np.isfinite(Fc_m[t]) and np.isfinite(Fc_m[t - 1]):
            comp["inventory"][d] += q * (fusd_m[t] - fusd_m[t - 1]) + es * mult * (Fc_m[t] - Fc_m[t - 1])
            comp["fx"][d] += cash_loc * (X_m[t] - X_m[t - 1])
            if a["switch"][t] and es != 0:  # roll the hedge onto the new contract
                cost = abs(es) * 2 * hs_es * mult
                fee = abs(es) * 2 * p.es_fee_usd
                cash_usd -= cost + fee
                comp["hedge_slip"][d] -= cost
                comp["fees"][d] -= fee
        # 2. hedges due
        due = [x for x in pending if x[2] <= t]
        if due and hedge_now(t, due):
            pending = [x for x in pending if x[2] > t]
        # 3. daily FX conversion
        if a["is_fx"][t] and not usd_line and cash_loc != 0 and np.isfinite(X_m[t]):
            cost = abs(cash_loc) * X_m[t] * p.fx_half_spread_bp / 1e4
            cash_usd += cash_loc * X_m[t] - cost
            cash_loc = 0.0
            comp["fx"][d] -= cost
        # 4. quotes and fills during bar t
        if a["cont"][t] and np.isfinite(a["fair_loc"][t]) and np.isfinite(a["Fc"][t]) and np.isfinite(a["X"][t]):
            is_pulled = (a["F_age"][t] > p.stale_minutes) or (a["X_age"][t] > p.stale_minutes) or (abs(a["es_ret"][t]) > p.fast_market_bp / 1e4)
            if is_pulled:
                pulled[d] += 1
            else:
                quoted[d] += 1
                fair_loc, fair_usd, X = a["fair_loc"][t], a["fair_usd"][t], a["X"][t]
                clip = max(1, int(round(mult * a["Fc"][t] / fair_usd)))
                q_clips = q / clip
                level = (1 + ew_prem) * (1 - p.skew_bp_per_clip * q_clips / 1e4)
                # the fair's path within the bar: fixed quotes see the bar-start fair on both sides; tracking quotes follow
                # the ES bar's low on the bid and its high on the ask
                fair_dn, fair_up = fair_loc, fair_loc
                if p.track_es and np.isfinite(a["Fl"][t]) and np.isfinite(a["Fh"][t]) and a["Fc"][t] > 0:
                    fair_dn = fair_loc * min(a["Fl"][t] / a["Fc"][t], 1.0)
                    fair_up = fair_loc * max(a["Fh"][t] / a["Fc"][t], 1.0)
                bid = _floor(fair_dn * level * (1 - p.half_spread_bp / 1e4), p.tick)
                ask = _ceil(fair_up * level * (1 + p.half_spread_bp / 1e4), p.tick)
                if ask - bid < p.tick - 1e-12:
                    ask = bid + p.tick
                want_bid = q_clips < p.max_inventory_clips - 1e-9
                want_ask = q_clips > -p.max_inventory_clips + 1e-9
                if record_path:
                    path["bid"][t] = bid if want_bid else np.nan
                    path["ask"][t] = ask if want_ask else np.nan
                    path["clip"][t] = clip
                if a["has_print"][t]:
                    hit_bid = want_bid and a["low"][t] <= bid - p.through_ticks * p.tick + 1e-9
                    hit_ask = want_ask and a["high"][t] >= ask + p.through_ticks * p.tick - 1e-9
                    both = hit_bid and hit_ask
                    cap = math.floor(p.max_participation * a["volume"][t] / (2 if both else 1))
                    size = min(clip, cap)
                    if size >= 1:
                        for side, price, fref in ((1, bid, fair_dn), (-1, ask, fair_up)):
                            if (side == 1 and hit_bid) or (side == -1 and hit_ask):
                                q += side * size
                                cash_loc -= side * size * price
                                fee = p.etf_fee_bp / 1e4 * size * price * X
                                cash_usd -= fee
                                cap_usd = side * size * (fref - price) * X  # against the fair at the time of the fill
                                comp["capture"][d] += cap_usd
                                comp["inventory"][d] += side * size * (fair_loc - fref) * X  # the fair's move before the fill, booked where the marks put it
                                comp["fees"][d] -= fee
                                n_fills[d] += 1
                                notional[d] += size * price * X
                                pending.append((fref * X, side * size, t + 1 + p.hedge_delay_bars))
                                fills.append({"row": t, "ts": a["ts"][t], "date": a["date"][t], "side": side, "size": size, "price": price, "fair": fref,
                                              "X": X, "capture_usd": cap_usd, "notional_usd": size * price * X, "clip": clip, "q_after": q,
                                              "prem_of_fill_bp": 1e4 * (price - fref) / fref})
        # 5. end of day
        if a["is_last"][t] and p.eod != "carry" and q != 0 and np.isfinite(fair_m[t]) and np.isfinite(X_m[t]):
            if p.eod == "flatten_close":
                base = a["P"][t] if np.isfinite(a["P"][t]) else fair_m[t]
                price = base * (1 - math.copysign(p.flatten_half_spread_bp, q) / 1e4)
            else:  # create_redeem: at fair (NAV) less the one-unit bound per share
                price = fair_m[t] * (1 - math.copysign(p.redeem_cost_bp, q) / 1e4)
            cash_loc += q * price
            comp["inventory"][d] += q * (price - fair_m[t]) * X_m[t]
            fee = p.etf_fee_bp / 1e4 * abs(q) * price * X_m[t] if p.eod == "flatten_close" else 0.0
            cash_usd -= fee
            comp["fees"][d] -= fee
            fills.append({"row": t, "ts": a["ts"][t], "date": a["date"][t], "side": -int(np.sign(q)), "size": abs(q), "price": price, "fair": fair_m[t], "X": X_m[t],
                          "capture_usd": 0.0, "notional_usd": abs(q) * price * X_m[t], "clip": np.nan, "q_after": 0.0, "prem_of_fill_bp": np.nan, "eod": p.eod})
            q = 0.0
            pending = []
            hedge_now(t, [])
            if not usd_line and cash_loc != 0:
                cost = abs(cash_loc) * X_m[t] * p.fx_half_spread_bp / 1e4
                cash_usd += cash_loc * X_m[t] - cost
                cash_loc = 0.0
                comp["fx"][d] -= cost
        if record_path:
            path["q"][t], path["es"][t], path["cash_loc"][t], path["cash_usd"][t] = q, es, cash_loc, cash_usd
            path["V"][t] = value(t) if np.isfinite(fusd_m[t]) and np.isfinite(Fc_m[t]) and np.isfinite(X_m[t]) else np.nan
    V_end = value(n - 1)
    total = sum(float(v.sum()) for v in comp.values())
    daily = pd.DataFrame({"day": np.arange(nd), **{k: v for k, v in comp.items()}, "n_fills": n_fills, "notional_usd": notional, "quoted_bars": quoted, "pulled_bars": pulled})
    daily["pnl_usd"] = daily[["capture", "hedge_slip", "fx", "inventory", "fees"]].sum(axis=1)
    dates = pd.Series(a["date"]).groupby(day).first()
    daily["date"] = daily.day.map(dates)
    out = {"daily": daily, "fills": pd.DataFrame(fills), "hedges": pd.DataFrame(hedges), "V_start": float(V_start or 0.0), "V_end": float(V_end),
           "total_pnl_usd": total, "identity_gap_usd": float((V_end - (V_start or 0.0)) - total), "n_fills": int(n_fills.sum()), "notional_usd": float(notional.sum()),
           "pnl_bp": float(total / notional.sum() * 1e4) if notional.sum() > 0 else np.nan,
           "components_usd": {k: float(v.sum()) for k, v in comp.items()}, "q_end": q, "es_end": es, "quoted_bars": int(quoted.sum()), "pulled_bars": int(pulled.sum())}
    if record_path:
        out["path"] = pd.DataFrame({"ts": a["ts"], "date": a["date"], **path, "fair": a["fair_loc"], "fair_usd": a["fair_usd"], "X": a["X"], "F": a["Fc"],
                                    "F_age": a["F_age"], "X_age": a["X_age"], "P": a["P"], "cont": a["cont"]})
    return out
