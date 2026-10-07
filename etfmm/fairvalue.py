"""Fair value of a UCITS S&P 500 ETF line from the E-mini, minute by minute.

    I_impl(t) = (F(t) + D(t, T)) / (1 + r tau)        the index level the E-mini implies: cost of carry removed, expected dividend
                                                      points to the contract's expiry from the vendored accrual model
    I_fair(t) = I_impl(t) (1 - rho_c / 1e4)           less the contract's richness rho_c, the median of 1e4 (I_impl - I) / I over the
                                                      US cash session while contract c is the front (the implied financing spread
                                                      over bills; measured in-sample, one number per contract)
    E*_USD(t) = I_fair(t) / kappa_d                   the fund's fair USD price; kappa_d = index / NAV struck strictly before day d:
                                                      from the line's own closing prints (self, the quoter's default) or from the
                                                      issuer's NAV file (nav), both drifted for the fee and the dividend accrual
    E*_loc(t) = E*_USD(t) / X(t)                      in the trading currency; X = USD per unit of it (1 for the USD lines)
    prem_bp   = 1e4 (P - E*_loc) / E*_loc             the line's premium to fair at a bar with a trade (P the bar's close)

Timing: the fair at the start of ETF bar t uses the last ES and FX bars that CLOSED by t.  The day's r, tau and D are fixed per
(date, contract).  Yahoo's continuous ES=F switches contract during expiry week; the switch bar is detected and every bar
carries its own contract, so the fair is continuous across it and the quoter rolls its hedge there.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import calendar as CAL
from . import data as D
from .vendor import d1_fairvalue as FV

SPY_FEE_BP = 9.45  # SPY's expense ratio: the gross-up of its distributions in the dividend model
NY = "America/New_York"


# ----------------------------------------------------------------------------- the dividend model (S&P 500 via SPY)
def dividend_model(index_sym: str = "^GSPC", fund: str = "SPY") -> dict:
    px = D.closes([index_sym, fund]).dropna()
    q = FV.quarterly_distributions(D.dividends(fund))
    prof = FV.accrual_profile(px, index_sym, fund, q, SPY_FEE_BP)
    kap = FV.kappa_series(px, index_sym, fund, q)
    return {"px": px, "q": q, "prof": prof, "kap": kap, "index": index_sym, "fund": fund}


def day_carry(date, expiry, model: dict, rates: pd.DataFrame, rate_kind: str = "bill") -> dict:
    """r, tau, D for a date and a contract expiry."""
    d = pd.Timestamp(date).normalize()
    days = FV.days_to(d, expiry)
    r = FV.rate_at(rates, d, days, rate_kind)
    px = model["px"]
    prev = px.index[px.index <= d]
    ref = prev[-1] if len(prev) else px.index[0]
    kappa_spy = float(model["kap"].get(ref, model["kap"].iloc[-1]))
    spy_px = float(px[model["fund"]].get(ref, np.nan))
    Dpts = FV.dividend_points(model["q"], kappa_spy, d, expiry, model["prof"], SPY_FEE_BP, spy_px)
    return {"date": str(d.date()), "expiry": str(pd.Timestamp(expiry).date()), "days": days, "tau": days / 360.0, "r": r, "D": Dpts}


def accrual_fraction(model: dict, t0, t1) -> float:
    """Expected index dividend points going ex in [t0, t1) as a fraction of the index level at t0: how much a total-return
    fund's NAV gains on the price index between the two dates."""
    t0, t1 = pd.Timestamp(t0).normalize(), pd.Timestamp(t1).normalize()
    if t1 <= t0:
        return 0.0
    px = model["px"]
    prev = px.index[px.index <= t0]
    ref = prev[-1] if len(prev) else px.index[0]
    kappa_spy = float(model["kap"].get(ref, model["kap"].iloc[-1]))
    spy_px = float(px[model["fund"]].get(ref, np.nan))
    I0 = float(px[model["index"]].get(ref, np.nan))
    Dpts = FV.dividend_points(model["q"], kappa_spy, t0, t1, model["prof"], SPY_FEE_BP, spy_px)
    return float(Dpts / I0) if np.isfinite(I0) and I0 > 0 else 0.0


# ----------------------------------------------------------------------------- which contract is Yahoo's ES=F carrying
def contract_by_bar(es: pd.DataFrame, idx: pd.DataFrame | None = None, jump_bp: float = 40.0, persist_bars: int = 30) -> tuple[pd.DataFrame, list]:
    """Per ES bar (close not NaN, sorted): the expiry of the contract the continuous series carries, and the switches found.

    Default: the calendar front for the bar's New York date (the contract still trading; on its last day the next one).
    Inside an expiry week (the Monday through the third Friday) the series switches to the next contract at one bar; it is
    detected as a one-minute move larger than `jump_bp` whose level persists over the next `persist_bars` closes.  Where the
    cash index prints around the bar (US session), the change in the ratio F / I is reported as confirmation."""
    e = es.dropna(subset=["close"]).sort_values("ts").reset_index(drop=True).copy()
    ny = e.ts.dt.tz_convert(NY)
    e["ny_date"] = ny.dt.normalize().dt.tz_localize(None)
    e["expiry"] = [FV.front_expiry(d) for d in e.ny_date]
    e["F_cont"] = e.close.astype(float)
    switches = []
    ret = np.log(e.close).diff().to_numpy()
    for exp in sorted(set(e.expiry)):
        exp = pd.Timestamp(exp)
        week0 = exp - pd.Timedelta(days=exp.weekday())  # Monday of expiry week
        in_week = (e.ny_date >= week0) & (e.ny_date <= exp)
        cand = np.where(in_week.to_numpy() & (np.abs(ret) > jump_bp / 1e4))[0]
        found = None
        for i in cand:
            before = e.close.iloc[i - 1]
            after = e.close.iloc[i:i + persist_bars].median()
            if np.sign(after - before) == np.sign(ret[i]) and abs(after / before - 1) > 0.5 * jump_bp / 1e4:
                found = int(i)
                break
        if found is None:
            continue
        i = found
        nxt = FV.front_expiry(exp)  # the contract after `exp`: the front from the expiry date on
        mask = (np.arange(len(e)) >= i) & (e.expiry.to_numpy() == exp)
        e.loc[mask, "expiry"] = nxt
        ratio = float(e.close.iloc[i] / e.close.iloc[i - 1])
        e.loc[np.arange(len(e)) < i, "F_cont"] = e.F_cont[np.arange(len(e)) < i] * ratio  # back-adjust the old contract
        rec = {"from_expiry": str(exp.date()), "to_expiry": str(nxt.date()), "ts": str(e.ts.iloc[i]), "one_minute_return_bp": float(ret[i] * 1e4),
               "ratio_after_to_before": ratio, "n_bars_before": i, "n_bars_after": int(len(e) - i)}
        if idx is not None:
            ii = idx.dropna(subset=["close"])
            t = e.ts.iloc[i]
            w0 = ii[(ii.ts >= t - pd.Timedelta(minutes=30)) & (ii.ts < t)]
            w1 = ii[(ii.ts >= t) & (ii.ts < t + pd.Timedelta(minutes=30))]
            if len(w0) >= 5 and len(w1) >= 5:
                m0 = pd.merge_asof(w0[["ts", "close"]].rename(columns={"close": "I"}), e[["ts", "close"]].rename(columns={"close": "F"}), on="ts", direction="backward").dropna()
                m1 = pd.merge_asof(w1[["ts", "close"]].rename(columns={"close": "I"}), e[["ts", "close"]].rename(columns={"close": "F"}), on="ts", direction="backward").dropna()
                rec["ratio_F_over_I_before"] = float((m0.F / m0.I).median())
                rec["ratio_F_over_I_after"] = float((m1.F / m1.I).median())
                rec["cash_index_confirms"] = bool(abs((rec["ratio_F_over_I_after"] / rec["ratio_F_over_I_before"]) / ratio - 1) < 0.002)
        switches.append(rec)
    return e, switches


def es_implied(es_c: pd.DataFrame, model: dict, rates: pd.DataFrame, rate_kind: str = "bill") -> tuple[pd.DataFrame, pd.DataFrame]:
    """ES bars (from contract_by_bar) with I_impl = (F + D) / (1 + r tau) for their own (date, expiry); and the carry table."""
    keys = es_c[["ny_date", "expiry"]].drop_duplicates()
    rows = []
    for d, x in zip(keys.ny_date, keys.expiry):
        rows.append({"ny_date": d, "expiry": x, **{k: v for k, v in day_carry(d, x, model, rates, rate_kind).items() if k not in ("date", "expiry")}})
    carry = pd.DataFrame(rows)
    out = es_c.merge(carry, on=["ny_date", "expiry"], how="left")
    out["I_impl"] = (out.close + out.D) / (1 + out.r * out.tau)
    return out, carry


def richness(es_i: pd.DataFrame, idx: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Implied index against the cash index, minute by minute in the US cash session; the per-contract median (the number
    the fair removes) and the per-day medians."""
    ii = idx.dropna(subset=["close"])[["ts", "close"]].rename(columns={"close": "I"}).sort_values("ts")
    m = pd.merge_asof(ii, es_i[["ts", "I_impl", "expiry", "close"]].rename(columns={"close": "F"}), on="ts", direction="backward", tolerance=pd.Timedelta(minutes=2)).dropna()
    m = m[CAL.us_cash_open(m.ts)].copy()
    m["rich_bp"] = 1e4 * (m.I_impl - m.I) / m.I
    m["ny_date"] = m.ts.dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)
    by_c = {str(pd.Timestamp(k).date()): float(v) for k, v in m.groupby("expiry").rich_bp.median().items()}
    by_day = m.groupby(["ny_date", "expiry"]).agg(rich_median_bp=("rich_bp", "median"), rich_sd_bp=("rich_bp", "std"), n=("rich_bp", "size")).reset_index()
    return m, by_c, by_day


# ----------------------------------------------------------------------------- minute grids
def _asof_input(grid: pd.DatetimeIndex, bars: pd.DataFrame, cols: dict) -> pd.DataFrame:
    """The last bar that closed by each grid time (bar start < t), the requested columns and its age in minutes (0 = the bar
    starting at t - 1 min)."""
    b = bars.dropna(subset=[list(cols)[0]]).sort_values("ts")
    g = pd.DataFrame({"ts": grid})
    right = b[["ts"] + list(cols)].rename(columns={"ts": "_src_ts", **cols})
    right["_src_ts"] = right["_src_ts"].astype(g.ts.dtype)
    m = pd.merge_asof(g, right, left_on="ts", right_on="_src_ts", direction="backward", allow_exact_matches=False)
    age_col = f"{list(cols.values())[0]}_age_min"
    m[age_col] = (m.ts - m._src_ts).dt.total_seconds() / 60.0 - 1.0
    return m.drop(columns=["_src_ts"])


def day_grid(date, venue: str, pad_minutes: int = 5) -> pd.DatetimeIndex:
    s = CAL.SESSIONS[venue]
    d = pd.Timestamp(date)
    t0 = pd.Timestamp(f"{d.date()} {s['open']}", tz=s["tz"]).tz_convert("UTC")
    t1 = pd.Timestamp(f"{d.date()} {s['close']}", tz=s["tz"]).tz_convert("UTC")
    return pd.date_range(t0, t1 + pd.Timedelta(minutes=pad_minutes), freq="1min")


# ----------------------------------------------------------------------------- kappa
def self_kappa_by_day(frame: pd.DataFrame, last_minutes: int = 30) -> pd.Series:
    """kappa_hat_d = median over the last `last_minutes` of continuous trading of I_fair / (P X): the index/fund ratio the
    line's own prints imply at the European close of day d."""
    f = frame[frame.continuous & frame.P.notna() & frame.I_fair.notna() & frame.X.notna()]
    n = f.groupby("date").minute.transform("max")
    f = f[f.minute > n - last_minutes]
    return (f.I_fair / (f.P * f.X)).groupby(f.date).median()  # fund USD price = P x (USD per unit of the trading currency)


def exdiv_factor(line_divs: pd.DataFrame, px_close: pd.Series, t0, t1) -> float:
    """For a distributing line: kappa rises by 1 / (1 - div / P) at each of the line's ex-dates in (t0, t1]."""
    if line_divs is None or line_divs.empty:
        return 1.0
    f = 1.0
    for x, amt in zip(line_divs.ex_date, line_divs.amount):
        x = pd.Timestamp(x)
        if pd.Timestamp(t0) < x <= pd.Timestamp(t1):
            prev = px_close[px_close.index < x]
            if len(prev) and prev.iloc[-1] > 0:
                f *= 1.0 / (1.0 - float(amt) / float(prev.iloc[-1]))
    return f


def kappa_table(dates: list, self_k: pd.Series, cfg: dict, model: dict, index_px: pd.Series, line_px: pd.Series, line_divs: pd.DataFrame | None,
                nav: pd.DataFrame | None, window: int) -> pd.DataFrame:
    """Per trading date d: the self-calibrated kappa (median over the last `window` closes before d, each drifted to d for the
    fee, the dividend accrual and the line's own ex-dates) and, where an issuer NAV exists, the NAV kappa struck at the US close
    of the last NAV date before d."""
    ter = cfg["ter_bp"] / 1e4
    rows = []
    for d in dates:
        d = pd.Timestamp(d)
        prev = self_k[pd.to_datetime(self_k.index) < d]
        ks = []
        for j, kj in zip(pd.to_datetime(prev.index[-window:]), prev.iloc[-window:]):
            dt_days = (d - j).days
            adj = (1 + ter * dt_days / 365.0) * (1 - accrual_fraction(model, j, d)) * exdiv_factor(line_divs, line_px, j, d)
            ks.append(kj * adj)
        k_self = float(np.median(ks)) if ks else np.nan
        k_nav, nav_date = np.nan, None
        if nav is not None and not nav.empty:
            pn = nav[nav.date < d]
            if len(pn):
                p = pn.iloc[-1]
                ii = index_px[index_px.index <= p.date]
                if len(ii) and np.isfinite(p.nav) and p.nav > 0:
                    dt_days = (d - pd.Timestamp(p.date)).days
                    k_nav = float(ii.iloc[-1]) / float(p.nav) * (1 + ter * dt_days / 365.0) * (1 - accrual_fraction(model, p.date, d)) * exdiv_factor(line_divs, line_px, p.date, d)
                    nav_date = str(pd.Timestamp(p.date).date())
        rows.append({"date": d.date(), "kappa_self": k_self, "n_self": len(ks), "kappa_nav": k_nav, "nav_date": nav_date,
                     "nav_vs_self_bp": 1e4 * (k_self / k_nav - 1) if np.isfinite(k_nav) and np.isfinite(k_self) else np.nan})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- the line's minute frame
def build_frame(line: str, cfg: dict, bars: pd.DataFrame, es_i: pd.DataFrame, rich_by_contract: dict, model: dict, params: dict,
                nav: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One row per minute of the venue session (plus a 5-minute pad) for every trading day in the line's bars: the ETF bar
    (P = close, high, low, volume), the ES inputs as of the bar start (F, F_cont, I_fair, contract, age), FX (X, age), kappa
    (self and nav), the fair in USD and in the trading currency, the premium.  Returns the frame and the day table."""
    fvp = params["fair_value"]
    sym, venue, ccy = cfg["yahoo"], cfg["venue"], cfg["currency"]
    etf = bars[bars.symbol == sym].copy()
    fx = None if ccy == "USD" else bars[bars.symbol == {"GBP": "GBPUSD=X", "EUR": "EURUSD=X"}[ccy]]
    tz = CAL.SESSIONS[venue]["tz"]
    etf["date"] = etf.ts.dt.tz_convert(tz).dt.date
    days = sorted(etf.loc[etf.close.notna(), "date"].unique())
    e = es_i.copy()
    e["I_fair"] = e.I_impl * (1 - e.expiry.map(lambda x: rich_by_contract.get(str(pd.Timestamp(x).date()), 0.0)) / 1e4)
    e["expiry_s"] = e.expiry.astype(str).str[:10]
    frames = []
    for d in days:
        grid = day_grid(d, venue)
        g = pd.DataFrame({"ts": grid})
        g = g.merge(etf[["ts", "open", "high", "low", "close", "volume"]].rename(columns={"close": "P"}), on="ts", how="left")
        g = g.merge(_asof_input(grid, e, {"close": "F", "F_cont": "F_cont", "I_fair": "I_fair", "I_impl": "I_impl", "expiry_s": "expiry"}), on="ts", how="left")
        # the ES bar concurrent with the ETF bar: its high and low say how far the fair moved WITHIN the minute (back-adjusted)
        same = e[["ts", "high", "low", "close", "F_cont"]].copy()
        adj = same.F_cont / same.close
        same = pd.DataFrame({"ts": same.ts.astype(g.ts.dtype), "F_bar_high": same.high * adj, "F_bar_low": same.low * adj})
        g = g.merge(same, on="ts", how="left")
        if fx is not None:
            g = g.merge(_asof_input(grid, fx, {"close": "X"}), on="ts", how="left")
        else:
            g["X"], g["X_age_min"] = 1.0, 0.0
        g["date"] = d
        g["minute"] = CAL.minutes_from_open(g.ts, venue)
        g["continuous"] = CAL.is_continuous(g.ts, venue)
        g["us_open"] = CAL.us_cash_open(g.ts)
        frames.append(g)
    frame = pd.concat(frames, ignore_index=True)
    frame["es_switch"] = frame.expiry.ne(frame.expiry.shift()) & frame.expiry.notna() & frame.expiry.shift().notna()
    # kappa: self-calibrated from the closes, nav where the issuer file exists
    self_k = self_kappa_by_day(frame)
    index_px = model["px"][model["index"]]
    line_px = D.closes([sym])[sym]
    line_divs = D.dividends(sym) if cfg.get("distributing") else None
    kap = kappa_table(days, self_k, cfg, model, index_px, line_px, line_divs, nav, fvp["kappa_window_days"])
    frame = frame.merge(kap[["date", "kappa_self", "kappa_nav"]], on="date", how="left")
    frame["fair_usd"] = frame.I_fair / frame.kappa_self
    frame["fair"] = frame.fair_usd / frame.X
    frame["nav_fair_usd"] = frame.I_fair / frame.kappa_nav
    frame["nav_fair"] = frame.nav_fair_usd / frame.X
    frame["prem_bp"] = 1e4 * (frame.P - frame.fair) / frame.fair
    frame["prem_nav_bp"] = 1e4 * (frame.P - frame.nav_fair) / frame.nav_fair
    frame["line"] = line
    # day table
    cont = frame[frame.continuous & frame.P.notna()]
    n_last = cont.groupby("date").minute.transform("max")
    last30 = cont[cont.minute > n_last - 30]
    daytab = kap.merge(pd.DataFrame({"date": list(self_k.index), "self_kappa_at_close": self_k.values}), on="date", how="left")
    daytab["n_prints"] = daytab.date.map(cont.groupby("date").size())
    daytab["volume"] = daytab.date.map(cont.groupby("date").volume.sum())
    daytab["prem_median_bp"] = daytab.date.map(cont.groupby("date").prem_bp.median())
    daytab["prem_sd_bp"] = daytab.date.map(cont.groupby("date").prem_bp.std())
    daytab["prem_close_bp"] = daytab.date.map(last30.groupby("date").prem_bp.median())
    daytab["prem_nav_close_bp"] = daytab.date.map(last30.groupby("date").prem_nav_bp.median())
    daytab["expiry"] = daytab.date.map(frame.groupby("date").expiry.agg(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None))
    daytab["es_switch"] = daytab.date.map(frame.groupby("date").es_switch.any())
    daytab["F_close"] = daytab.date.map(cont.groupby("date").F.last())
    daytab["X_close"] = daytab.date.map(cont.groupby("date").X.last())
    daytab["fair_close_usd"] = daytab.date.map(cont.groupby("date").fair_usd.last())
    daytab["line"] = line
    return frame, daytab
