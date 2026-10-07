import numpy as np
import pandas as pd

from etfmm import bound as B
from etfmm import reference as R
from etfmm import stats as S
from etfmm import calendar as CAL


def test_bound_arithmetic():
    r = B.bound_bp(n_units=1, unit_shares=60000, nav_usd=150.0, fixed_fee_usd=1500.0, basket_half_spread_bp=1.5, es_price=7800.0, es_tick=0.25,
                   es_multiplier=50.0, es_fee_usd=1.40, es_half_spread_ticks=0.5, fx_half_spread_bp=0.5, overnight_rate=0.036, settlement_days=1)
    notional = 60000 * 150.0
    assert abs(r["notional_usd"] - notional) < 1e-9
    assert abs(r["fixed_fee_bp"] - 1500.0 / notional * 1e4) < 1e-12
    contracts = notional / (50 * 7800.0)
    assert abs(r["hedge_bp"] - contracts * (0.125 * 50 + 1.40) / notional * 1e4) < 1e-12
    assert abs(r["settlement_bp"] - 0.036 / 360 * 1e4) < 1e-12
    assert abs(r["bound_bp"] - (r["fixed_fee_bp"] + 1.5 + r["hedge_bp"] + 0.5 + r["settlement_bp"])) < 1e-12
    # more units amortise the fixed fee and nothing else
    r2 = B.bound_bp(n_units=2, unit_shares=60000, nav_usd=150.0, fixed_fee_usd=1500.0, basket_half_spread_bp=1.5, es_price=7800.0, es_tick=0.25,
                    es_multiplier=50.0, es_fee_usd=1.40, es_half_spread_ticks=0.5, fx_half_spread_bp=0.5, overnight_rate=0.036, settlement_days=1)
    assert abs((r["bound_bp"] - r2["bound_bp"]) - r["fixed_fee_bp"] / 2) < 1e-12


def test_breakeven_interpolation():
    h = np.array([1.0, 2.0, 3.0, 4.0])
    assert S.breakeven(h, np.array([-2.0, -1.0, 1.0, 2.0])) == 2.5
    assert S.breakeven(h, np.array([1.0, 2.0, 3.0, 4.0])) == 1.0
    assert S.breakeven(h, np.array([-1.0, -1.0, -1.0, -1.0])) == float("inf")


def test_bootstrap_curve_recovers_the_point_estimate_and_is_reproducible():
    rng = np.random.default_rng(1)
    rows = []
    for d in range(20):
        for h in (1.0, 2.0, 3.0, 4.0):
            notional = 1e6
            rows.append({"date": f"d{d:02d}", "h": h, "pnl_usd": notional * (h - 2.5) / 1e4 + rng.normal(0, 20), "notional_usd": notional})
    daily = pd.DataFrame(rows)
    r1 = S.bootstrap_curve(daily, [1.0, 2.0, 3.0, 4.0], n_boot=200, block=3, seed=0, base_h=3.0)
    r2 = S.bootstrap_curve(daily, [1.0, 2.0, 3.0, 4.0], n_boot=200, block=3, seed=0, base_h=3.0)
    assert r1 == r2
    assert abs(r1["breakeven_bp"] - 2.5) < 0.1
    assert r1["breakeven_lo"] <= r1["breakeven_bp"] <= r1["breakeven_hi"]
    assert abs(r1["base_pnl_bp"] - 0.5) < 0.1


def test_tick_inference_on_noisy_float32_prices():
    rng = np.random.default_rng(0)
    px = (np.round(rng.uniform(800, 850, 5000) / 0.02) * 0.02).astype(np.float32).astype(float)
    r = R.infer_tick(px)
    assert r["tick"] == 0.02 and r["share"] > 0.99
    px2 = (np.round(rng.uniform(100, 112, 5000) / 0.0025) * 0.0025).astype(np.float32).astype(float)
    assert R.infer_tick(px2)["tick"] == 0.0025
    # five percent of off-grid prints (midpoint or off-book trades) do not change the answer
    mixed = np.concatenate([px, px[:250] + 0.01])
    assert R.infer_tick(mixed)["tick"] == 0.02


def test_session_minutes():
    ts = pd.to_datetime(["2026-09-10 07:00", "2026-09-10 07:05", "2026-09-10 15:29", "2026-09-10 15:30"], utc=True).to_series()
    k = CAL.minutes_from_open(ts, "LSE")
    assert k.tolist() == [0, 5, 509, 510]
    c = CAL.is_continuous(ts, "LSE", skip_open=5, skip_close=5)
    assert c.tolist() == [False, True, False, False]
    assert CAL.session_length_minutes("Xetra") == 510
    assert CAL.us_cash_open(pd.to_datetime(["2026-09-10 13:29", "2026-09-10 13:30"], utc=True).to_series()).tolist() == [False, True]
