import numpy as np
import pandas as pd

from etfmm import fairvalue as FVL
from etfmm.vendor import d1_fairvalue as FV


def test_implied_index_inverts_fair_futures():
    I, r, tau, D = 7800.0, 0.04, 0.25, 18.0
    F = FV.fair_futures(I, r, tau, D)
    assert abs(FV.implied_index(F, r, tau, D) - I) < 1e-9
    # the carry removed: with no dividends and no rate the future is the index
    assert FV.fair_futures(I, 0.0, tau, 0.0) == I


def test_contract_by_bar_detects_the_switch():
    # a flat series on the September contract that jumps 90 bp on the Monday of expiry week and stays there
    ts = pd.date_range("2026-09-10 13:30", "2026-09-16 20:00", freq="1min", tz="UTC")
    close = np.full(len(ts), 7600.0)
    jump_at = np.searchsorted(ts, pd.Timestamp("2026-09-14 15:30", tz="UTC"))
    close[jump_at:] *= 1.009
    es = pd.DataFrame({"ts": ts, "close": close})
    e, sw = FVL.contract_by_bar(es, idx=None)
    assert len(sw) == 1
    assert sw[0]["from_expiry"] == "2026-09-18" and sw[0]["to_expiry"] == "2026-12-18"
    assert str(e.ts.iloc[sw[0]["n_bars_before"]]) == str(ts[jump_at])
    assert (e.expiry.iloc[:jump_at] == pd.Timestamp("2026-09-18")).all()
    assert (e.expiry.iloc[jump_at:] == pd.Timestamp("2026-12-18")).all()
    # the back-adjusted series is continuous across the switch
    assert abs(e.F_cont.iloc[jump_at] - e.F_cont.iloc[jump_at - 1]) < 1e-6
    # an ordinary 20 bp move in expiry week is not a switch
    close2 = np.full(len(ts), 7600.0)
    close2[jump_at:] *= 1.002
    e2, sw2 = FVL.contract_by_bar(pd.DataFrame({"ts": ts, "close": close2}), idx=None)
    assert sw2 == []


def test_exdiv_factor_raises_kappa_by_the_dividend():
    px = pd.Series([100.0, 100.0, 99.5], index=pd.to_datetime(["2026-09-15", "2026-09-16", "2026-09-17"]))
    divs = pd.DataFrame({"ex_date": [pd.Timestamp("2026-09-17")], "amount": [0.5]})
    f = FVL.exdiv_factor(divs, px, "2026-09-16", "2026-09-18")
    assert abs(f - 1 / (1 - 0.5 / 100.0)) < 1e-12
    assert FVL.exdiv_factor(divs, px, "2026-09-17", "2026-09-18") == 1.0  # the ex-date itself is not inside (t0, t1]
    assert FVL.exdiv_factor(None, px, "2026-09-10", "2026-09-20") == 1.0


def test_asof_input_uses_only_bars_closed_by_the_grid_time():
    grid = pd.date_range("2026-09-10 08:00", "2026-09-10 08:05", freq="1min", tz="UTC").astype("datetime64[us, UTC]")
    bars = pd.DataFrame({"ts": pd.to_datetime(["2026-09-10 07:58", "2026-09-10 07:59", "2026-09-10 08:02"], utc=True), "close": [1.0, 2.0, 3.0]})
    m = FVL._asof_input(grid, bars, {"close": "F"})
    # at 08:00 the last bar that closed is the one starting 07:59 (age 0); at 08:02 the bar starting 08:02 has not closed
    assert m.F.tolist() == [2.0, 2.0, 2.0, 3.0, 3.0, 3.0]
    assert m.F_age_min.tolist() == [0.0, 1.0, 2.0, 0.0, 1.0, 2.0]


def test_day_grid_covers_the_session_plus_pad():
    g = FVL.day_grid(pd.Timestamp("2026-09-10"), "LSE", pad_minutes=5)
    assert len(g) == 8 * 60 + 30 + 5 + 1
    assert str(g[0]) == "2026-09-10 07:00:00+00:00"  # 08:00 London in summer time
    gx = FVL.day_grid(pd.Timestamp("2026-09-10"), "Xetra", pad_minutes=0)
    assert str(gx[0]) == "2026-09-10 07:00:00+00:00" and str(gx[-1]) == "2026-09-10 15:30:00+00:00"
