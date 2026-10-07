"""Cost-of-carry fair value, dividend accrual and the AR(1) half-life.  Vendored from m-ichaels/delta-one-basis
(d1basis/fairvalue.py and d1basis/calendar.py; see NOTICE).  Data access adapted to take DataFrames.

Notation.  I index level, E fund price, F futures price, tau = years to the contract's last trading day (act/360),
r(t, tau) the financing rate, D(t, T) the index dividend points going ex in (t, T].
    F* = (I - PV D)(1 + r tau)                       fair futures price
    I_impl = (F + D) / (1 + r tau)                   the index level the future implies (the inverse of F*, used here)
    E* = I / kappa_q + A(t) - fee(t)                 fair fund price inside dividend quarter q; kappa_q = I/E at the
                                                     previous ex-date, A the dividends per share accrued since it
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import numpy as np
import pandas as pd

QUARTER_MONTHS = (3, 6, 9, 12)
MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}
TENORS = {"tbill_1m": 30, "tbill_2m": 61, "tbill_3m": 91, "tbill_6m": 182, "tsy_1y": 365}


# ----------------------------------------------------------------------------- calendar (NYSE / CME equity index)
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    off = (weekday - d.weekday()) % 7
    return d + dt.timedelta(days=off + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    d = dt.date(year + (month == 12), (month % 12) + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def easter(year: int) -> dt.date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def _observed(d: dt.date) -> dt.date:
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset:
    h = {_observed(dt.date(year, 1, 1)), _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), easter(year) - dt.timedelta(days=2),
         _last_weekday(year, 5, 0), _observed(dt.date(year, 7, 4)), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4), _observed(dt.date(year, 12, 25))}
    if year >= 2022:
        h.add(_observed(dt.date(year, 6, 19)))
    if dt.date(year, 1, 1).weekday() == 5:
        h.discard(dt.date(year - 1, 12, 31))
    for d in ((2012, 10, 29), (2012, 10, 30), (2018, 12, 5), (2025, 1, 9)):
        if d[0] == year:
            h.add(dt.date(*d))
    return frozenset(h)


def is_trading_day(d) -> bool:
    d = pd.Timestamp(d).date()
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def trading_days(start, end) -> pd.DatetimeIndex:
    days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    return pd.DatetimeIndex([d for d in days if is_trading_day(d)])


@lru_cache(maxsize=None)
def third_friday(year: int, month: int) -> pd.Timestamp:
    """Last trading day of the equity-index contract: the third Friday, or the Thursday before when the Friday is closed."""
    d = _nth_weekday(year, month, 4, 3)
    while d in nyse_holidays(d.year):
        d -= dt.timedelta(days=1)
    return pd.Timestamp(d)


def expiries(start, end) -> pd.DatetimeIndex:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out = []
    for y in range(s.year - 1, e.year + 2):
        for m in QUARTER_MONTHS:
            x = third_friday(y, m)
            if s <= x <= e:
                out.append(x)
    return pd.DatetimeIndex(out)


def front_expiry(date) -> pd.Timestamp:
    """The expiry of the contract still trading on `date` (the contract expires at the open of its last day, so on the
    expiry date itself the front is the next one for the purposes of a European-morning fair value)."""
    d = pd.Timestamp(date).normalize()
    for y in (d.year, d.year + 1):
        for m in QUARTER_MONTHS:
            x = third_friday(y, m)
            if d < x:
                return x
    raise ValueError(date)


def next_expiry(after) -> pd.Timestamp:
    x = front_expiry(after)
    return expiries(x + pd.Timedelta(days=1), x + pd.Timedelta(days=120))[0]


def contract_symbol(root: str, expiry: pd.Timestamp) -> str:
    return f"{root}{MONTH_CODE[expiry.month]}{expiry.year % 100:02d}"


@lru_cache(maxsize=20000)
def quarter_bounds(date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(previous expiry, next expiry] - the dividend quarter of the index funds, whose ex-dates are the expiry Fridays."""
    d = pd.Timestamp(date).normalize()
    nxt = front_expiry(d)
    prev = expiries(nxt - pd.Timedelta(days=120), nxt - pd.Timedelta(days=1))[-1]
    return prev, nxt


def days_to(t0, t1) -> int:
    return int((pd.Timestamp(t1).normalize() - pd.Timestamp(t0).normalize()).days)


# ----------------------------------------------------------------------------- financing
def rate_at(r: pd.DataFrame, date, days: int, which: str = "bill") -> float:
    """Simple annual rate (decimal) for `days` ahead from the curve row on `date`.  which: 'bill' (Treasury par curve
    interpolated in tenor) or a column name (SOFR, EFFR, ESTR, SONIA: flat overnight rate)."""
    d = pd.Timestamp(date).normalize()
    if d not in r.index:
        d = r.index[r.index.searchsorted(d) - 1] if d > r.index[0] else r.index[0]
    row = r.loc[d]
    if which != "bill":
        v = row.get(which, np.nan)
        return float(v) / 100.0 if pd.notna(v) else np.nan
    xs, ys = [], []
    for c, n in TENORS.items():
        v = row.get(c, np.nan)
        if pd.notna(v):
            xs.append(n)
            ys.append(float(v))
    if not xs:
        v = row.get("SOFR", np.nan)
        return float(v) / 100.0 if pd.notna(v) else np.nan
    return float(np.interp(max(days, 1), xs, ys)) / 100.0


# ----------------------------------------------------------------------------- dividends
def quarterly_distributions(dv: pd.DataFrame) -> pd.DataFrame:
    """One row per dividend quarter from a (ex_date, amount) table: ex_date, amount (per fund share), the expiry that
    closes the quarter."""
    if dv.empty:
        return pd.DataFrame(columns=["ex_date", "amount", "quarter_end"])
    dv = dv.copy()
    dv["quarter_end"] = [quarter_bounds(x - pd.Timedelta(days=1))[1] for x in dv.ex_date]
    q = dv.groupby("quarter_end").agg(ex_date=("ex_date", "last"), amount=("amount", "sum")).reset_index()
    return q[["ex_date", "amount", "quarter_end"]]


_FQ_CACHE: dict = {}


def forecast_quarter(q: pd.DataFrame, asof, quarter_end) -> float:
    """Point-in-time forecast of the fund's distribution for the quarter ending at `quarter_end`, using only
    distributions that went ex before `asof`."""
    n_known = int(np.searchsorted(q.ex_date.values, np.datetime64(pd.Timestamp(asof)), side="left"))
    key = (id(q), n_known, pd.Timestamp(quarter_end))
    if key in _FQ_CACHE:
        return _FQ_CACHE[key]
    v = _forecast_quarter(q.iloc[:n_known], quarter_end)
    _FQ_CACHE[key] = v
    return v


def _forecast_quarter(known: pd.DataFrame, quarter_end) -> float:
    """Half the seasonal forecast (same quarter a year earlier times the trailing four-quarter growth, clipped to
    [0.5, 2]) and half the median of the last four distributions."""
    if len(known) < 4:
        return float(known.amount.iloc[-1]) if len(known) else np.nan
    a = known.set_index("quarter_end").amount
    same = a[a.index <= pd.Timestamp(quarter_end) - pd.Timedelta(days=360)]
    base = float(same.iloc[-1]) if len(same) else float(a.iloc[-4])
    g = a.iloc[-4:].sum() / a.iloc[-8:-4].sum() if len(a) >= 8 else 1.0
    seasonal = base * float(np.clip(g, 0.5, 2.0))
    return 0.5 * seasonal + 0.5 * float(np.median(a.iloc[-4:]))


def accrual_profile(px: pd.DataFrame, index_sym: str, etf: str, q: pd.DataFrame, fee_bp: float, n_bins: int = 20) -> pd.DataFrame:
    """Within-quarter dividend accrual measured from the fund: A(t) = E_t - I_t / kappa_q + fee accrual, as a share of
    the quarter's distribution, by fraction of the quarter elapsed; median and quartiles across quarters.
    px: wide daily closes with columns index_sym and etf."""
    px = px[[index_sym, etf]].dropna()
    rows = []
    for k in range(1, len(q)):
        t0, t1, amt = q.ex_date.iloc[k - 1], q.ex_date.iloc[k], q.amount.iloc[k]
        w = px[(px.index >= t0) & (px.index < t1)]
        if len(w) < 30 or amt <= 0:
            continue
        kappa = w[index_sym].iloc[0] / w[etf].iloc[0]
        span = (t1 - t0).days
        frac = np.array([(d - t0).days / span for d in w.index])
        fee = w[etf].values * fee_bp / 1e4 * frac * span / 365.0
        A = (w[etf].values - w[index_sym].values / kappa + fee) / amt
        for f, a in zip(frac, A):
            rows.append({"quarter_end": q.quarter_end.iloc[k], "frac": f, "share": a})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame({"frac": np.linspace(0, 1, n_bins + 1), "share": np.linspace(0, 1, n_bins + 1), "lo": np.nan, "hi": np.nan, "n": 0})
    df["bin"] = np.minimum((df.frac * n_bins).astype(int), n_bins - 1)
    g = df.groupby("bin").share
    prof = pd.DataFrame({"frac": (np.arange(n_bins) + 0.5) / n_bins, "share": g.median(), "lo": g.quantile(0.25), "hi": g.quantile(0.75), "n": g.size()}).reset_index(drop=True)
    prof["share"] = np.clip(prof.share.cummax(), 0, 1)
    return prof


def profile_fn(prof: pd.DataFrame | None):
    """Cumulative share of the quarter's dividends gone ex by fraction f of the quarter; None -> uniform accrual."""
    if prof is None or prof.empty or prof["n"].sum() == 0:
        return lambda f: np.clip(f, 0, 1)
    xs = np.concatenate([[0.0], prof.frac.values, [1.0]])
    ys = np.concatenate([[0.0], prof.share.values, [1.0]])
    return lambda f: np.interp(np.clip(f, 0, 1), xs, ys)


def dividend_points(q: pd.DataFrame, kappa: float, asof, t_end, prof=None, fee_bp: float = 0.0, etf_price: float = np.nan) -> float:
    """Expected index dividend points going ex in [asof, t_end): for every dividend quarter touched, the point-in-time
    forecast of the fund's distribution (grossed up by the fund's fee), times kappa, times the share of that quarter's
    accrual that falls inside the window."""
    p = profile_fn(prof)
    t, T = pd.Timestamp(asof).normalize(), pd.Timestamp(t_end).normalize()
    if T <= t:
        return 0.0
    total, cur = 0.0, t
    while cur < T:
        q0, q1 = quarter_bounds(cur)
        amt = forecast_quarter(q, asof, q1)
        if np.isnan(amt):
            amt = 0.0
        if fee_bp and pd.notna(etf_price):
            amt += etf_price * fee_bp / 1e4 * (q1 - q0).days / 365.0
        f0 = (cur - q0).days / (q1 - q0).days
        f1 = min((T - q0).days / (q1 - q0).days, 1.0)
        total += amt * kappa * float(p(f1) - p(f0))
        cur = q1
    return total


def kappa_series(px: pd.DataFrame, index_sym: str, etf: str, q: pd.DataFrame) -> pd.Series:
    """I/E measured at each fund ex-date close (the cum-dividend baseline of the following quarter), stepped forward."""
    px = px[[index_sym, etf]].dropna()
    k = {}
    for x in q.ex_date:
        w = px[px.index >= x]
        if len(w):
            k[w.index[0]] = w[index_sym].iloc[0] / w[etf].iloc[0]
    if not k:
        return pd.Series(px[index_sym] / px[etf], index=px.index)
    s = pd.Series(k).sort_index()
    return s.reindex(px.index, method="ffill").bfill()


def fair_futures(I: float, r: float, tau: float, D: float) -> float:
    """F* = (I - PV D)(1 + r tau) with PV D = D / (1 + r tau), i.e. F* = I (1 + r tau) - D."""
    return (I - D / (1 + r * tau)) * (1 + r * tau)


def implied_index(F: float, r: float, tau: float, D: float) -> float:
    """The inverse: the index level a futures price implies, (F + D) / (1 + r tau)."""
    return (F + D) / (1 + r * tau)


# ----------------------------------------------------------------------------- mean reversion
def ar1(x: np.ndarray) -> tuple[float, float, float]:
    """OLS x_{t+1} = c + phi x_t + e.  Returns phi, half-life in steps, residual sd."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 10:
        return np.nan, np.nan, np.nan
    a, b = x[:-1], x[1:]
    A = np.column_stack([np.ones_like(a), a])
    beta, *_ = np.linalg.lstsq(A, b, rcond=None)
    phi = float(beta[1])
    res = b - A @ beta
    hl = -np.log(2) / np.log(phi) if 0 < phi < 1 else np.inf if phi >= 1 else 0.0
    return phi, float(hl), float(res.std())


def half_life(x, block: int = 20, n_boot: int = 400, seed: int = 0) -> dict:
    """AR(1) half-life with a circular block-bootstrap interval (blocks of `block` steps)."""
    x = np.asarray(pd.Series(x).dropna(), float)
    phi, hl, sd = ar1(x)
    rng = np.random.default_rng(seed)
    n = len(x)
    hls, phis = [], []
    if n > 2 * block:
        nb = int(np.ceil(n / block))
        for _ in range(n_boot):
            starts = rng.integers(0, n, nb)
            idx = np.concatenate([(s + np.arange(block)) % n for s in starts])[:n]
            p, h, _ = ar1(x[idx])
            phis.append(p)
            hls.append(h)
    hls = np.array(hls)
    return {"n": int(n), "phi": phi, "half_life": hl, "resid_sd": sd, "mean": float(np.mean(x)) if n else np.nan, "sd": float(np.std(x)) if n else np.nan,
            "hl_lo": float(np.nanpercentile(hls, 2.5)) if len(hls) else np.nan, "hl_hi": float(np.nanpercentile(hls, 97.5)) if len(hls) else np.nan,
            "phi_lo": float(np.nanpercentile(phis, 2.5)) if len(phis) else np.nan, "phi_hi": float(np.nanpercentile(phis, 97.5)) if len(phis) else np.nan}


def half_life_segments(segs: list, n_boot: int = 300, seed: int = 0) -> dict:
    """AR(1) half-life pooled over independent segments (the within-day deviations of each day), with a segment bootstrap."""
    segs = [np.asarray(s, float) for s in segs if len(s) > 5]
    if not segs:
        return {"n_segments": 0, "n": 0, "phi": np.nan, "half_life": np.nan, "hl_lo": np.nan, "hl_hi": np.nan}

    def fit(idx):
        a = np.concatenate([segs[i][:-1] for i in idx])
        b = np.concatenate([segs[i][1:] for i in idx])
        ok = ~(np.isnan(a) | np.isnan(b))
        a, b = a[ok], b[ok]
        A = np.column_stack([np.ones_like(a), a])
        beta, *_ = np.linalg.lstsq(A, b, rcond=None)
        phi = float(beta[1])
        return phi, (-np.log(2) / np.log(phi) if 0 < phi < 1 else np.inf if phi >= 1 else 0.0)

    phi, hl = fit(range(len(segs)))
    rng = np.random.default_rng(seed)
    hls = [fit(rng.integers(0, len(segs), len(segs)))[1] for _ in range(n_boot)] if len(segs) > 1 else []
    return {"n_segments": len(segs), "n": int(sum(len(s) for s in segs)), "phi": phi, "half_life": float(hl),
            "hl_lo": float(np.nanpercentile(hls, 2.5)) if hls else np.nan, "hl_hi": float(np.nanpercentile(hls, 97.5)) if hls else np.nan}
