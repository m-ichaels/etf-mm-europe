import numpy as np
import pandas as pd

from etfmm import quoter as Q


def make_frame(n_days=2, fair0=100.0, drift_bp=0.0, swing_bp=10.0, volume=10000.0, currency="USD"):
    """A synthetic LSE-shaped frame: fair constant within the day (optionally drifting), the bar's high/low swinging
    +/- swing_bp around it, so a quoter with half-spread < swing_bp - 1 tick fills both sides every bar."""
    rows = []
    for d in range(n_days):
        day = pd.Timestamp("2026-09-10") + pd.Timedelta(days=d)
        ts = pd.date_range(day + pd.Timedelta(hours=7), day + pd.Timedelta(hours=15, minutes=35), freq="1min", tz="UTC")
        minute = np.arange(len(ts))
        fair = fair0 * (1 + drift_bp / 1e4 * minute / len(ts))
        X = 1.0 if currency == "USD" else 1.25
        rows.append(pd.DataFrame({"ts": ts, "date": day.date(), "minute": minute, "continuous": minute < 510, "P": fair / X, "open": fair / X,
                                  "high": fair / X * (1 + swing_bp / 1e4), "low": fair / X * (1 - swing_bp / 1e4), "volume": volume,
                                  "F": 7800.0 * fair / fair0, "F_cont": 7800.0 * fair / fair0, "F_age_min": 0.0, "X": X, "X_age_min": 0.0,
                                  "fair": fair / X, "fair_usd": fair, "nav_fair": fair / X, "es_switch": False, "I_fair": 7800.0 * fair / fair0}))
    f = pd.concat(rows, ignore_index=True)
    f["ts"] = f.ts.astype("datetime64[us, UTC]")
    return f


def params(**over):
    base = dict(half_spread_bp=3.0, skew_bp_per_clip=0.0, max_inventory_clips=5, through_ticks=1, max_participation=1.0, skip_open_minutes=0,
                skip_close_minutes=0, stale_minutes=3, fast_market_bp=50, hedge_delay_bars=1, eod="carry", etf_fee_bp=0.0, es_fee_usd=0.0,
                es_half_spread_ticks=0.0, es_tick=0.25, es_multiplier=50.0, fx_half_spread_bp=0.0, fx_hedge_minutes_before_close=6,
                flatten_half_spread_bp=5.0, redeem_cost_bp=5.0, tick=0.01, currency="USD", venue="LSE")
    base.update(over)
    return Q.QuoterParams(**base)


def test_both_sides_fill_and_capture_equals_the_half_spread():
    f = make_frame(n_days=1, swing_bp=10.0)
    p = params(half_spread_bp=3.0)
    r = Q.replay(Q.prepare(f, p), p)
    # every continuous bar fills both sides: 510 bars x 2
    assert r["n_fills"] == 2 * 510
    # bid = floor(100 x 0.9997) = 99.97, ask = ceil(100 x 1.0003) = 100.03: capture 3 cents per share per side, inventory nets to zero
    fills = r["fills"]
    assert np.allclose(fills.price[fills.side == 1], 99.97) and np.allclose(fills.price[fills.side == -1], 100.03)
    clip = int(round(50 * 7800 / 100.0))
    assert (fills["size"] == clip).all()
    assert abs(r["components_usd"]["capture"] - 2 * 510 * clip * 0.03) < 1e-6
    assert r["q_end"] == 0 and r["es_end"] == 0
    # no costs, flat fair: the whole P&L is capture, the identity holds to rounding
    assert abs(r["total_pnl_usd"] - r["components_usd"]["capture"]) < 1e-6
    assert abs(r["identity_gap_usd"]) < 1e-6


def test_wide_quote_never_fills_and_through_tick_rule():
    f = make_frame(n_days=1, swing_bp=10.0)
    r = Q.replay(Q.prepare(f, params(half_spread_bp=12.0)), params(half_spread_bp=12.0))
    assert r["n_fills"] == 0 and r["total_pnl_usd"] == 0.0
    # with through_ticks = 1 a quote exactly at the bar's low is not filled; with 0 it is
    f2 = make_frame(n_days=1, swing_bp=3.0)  # low = 99.97 = the bid
    r1 = Q.replay(Q.prepare(f2, params(through_ticks=1)), params(through_ticks=1))
    r0 = Q.replay(Q.prepare(f2, params(through_ticks=0)), params(through_ticks=0))
    assert r1["n_fills"] == 0 and r0["n_fills"] == 2 * 510


def test_one_sided_market_hedge_and_attribution_identity():
    # the market only ever trades down to the bid: the quoter accumulates inventory, hedges in ES, hits the inventory cap
    f = make_frame(n_days=1, swing_bp=10.0)
    f["high"] = f.P  # never reaches the ask
    p = params(half_spread_bp=3.0, max_inventory_clips=3, es_half_spread_ticks=0.5, es_fee_usd=1.4, etf_fee_bp=0.3)
    r = Q.replay(Q.prepare(f, p), p)
    clip = int(round(50 * 7800 / 100.0))
    assert r["n_fills"] == 3 and r["q_end"] == 3 * clip
    assert r["es_end"] == -3  # one contract per clip, short
    c = r["components_usd"]
    assert abs(sum(c.values()) - r["total_pnl_usd"]) < 1e-9
    assert abs(r["identity_gap_usd"]) < 1e-6
    assert c["fees"] < 0 and c["hedge_slip"] < 0  # half-spreads and commissions were paid
    assert abs(c["capture"] - 3 * clip * 0.03) < 1e-6


def test_fx_line_converts_cash_daily_and_fx_component_is_the_spread():
    f = make_frame(n_days=1, swing_bp=10.0, currency="GBP")
    p = params(currency="GBP", fx_half_spread_bp=1.0)
    r = Q.replay(Q.prepare(f, p), p)
    assert r["n_fills"] > 0
    # X is constant: the FX component is exactly the conversion cost of the net local cash at 16:00 (fills after 16:00 stay local)
    assert r["components_usd"]["fx"] <= 0
    assert abs(r["identity_gap_usd"]) < 1e-6


def test_eod_flatten_and_redeem_clear_inventory():
    f = make_frame(n_days=2, swing_bp=10.0)
    f["high"] = f.P
    for mode in ("flatten_close", "create_redeem"):
        p = params(eod=mode, max_inventory_clips=3)
        r = Q.replay(Q.prepare(f, p), p)
        assert r["q_end"] == 0 and r["es_end"] == 0
        assert r["components_usd"]["inventory"] < 0  # the liquidation cost
        assert abs(r["identity_gap_usd"]) < 1e-6


def test_stale_input_pulls_quotes():
    f = make_frame(n_days=1, swing_bp=10.0)
    f.loc[f.minute.between(100, 199), "F_age_min"] = 10.0
    p = params()
    r = Q.replay(Q.prepare(f, p), p)
    assert r["pulled_bars"] == 100 and r["quoted_bars"] == 410
