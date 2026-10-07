import numpy as np
import pandas as pd

from etfmm import monitor as M

MP = {"position_limit_clips": 6, "delta_limit_clips": 0.75, "delta_persist_bars": 3, "fx_exposure_limit_usd": 2000000, "stale_minutes": 3, "stuck_quote_bp": 10,
      "hedge_slip_bp": 10, "premium_band_bp": 40, "fat_finger_clips": 3, "drawdown_usd": 25000, "detect_window_minutes": 15}


def clean_day(n=300, clip=3900.0):
    ts = pd.date_range("2026-09-10 07:05", periods=n, freq="1min", tz="UTC")
    fair = 100.0 + 0.01 * np.sin(np.arange(n) / 20)
    q = np.zeros(n)
    es = np.zeros(n)
    q[100:] = clip  # one buy at bar 100, hedged one bar later
    es[101:] = -1
    V = np.zeros(n)
    path = pd.DataFrame({"ts": ts, "date": "2026-09-10", "q": q, "es": es, "cash_loc": 0.0, "cash_usd": 0.0, "bid": fair - 0.03, "ask": fair + 0.03, "V": V, "clip": clip,
                         "fair": fair, "fair_usd": fair, "X": 1.0, "F": 7800.0 * fair / 100.0, "F_age": 0.0, "X_age": 0.0, "P": fair, "cont": True})
    fills = pd.DataFrame([{"ts": ts[100], "side": 1, "size": clip, "price": fair[100] - 0.03, "fair": fair[100], "X": 1.0, "clip": clip, "capture_usd": 0.03 * clip, "notional_usd": clip * 100}])
    hedges = pd.DataFrame([{"ts": ts[101], "d_es": -1, "F_exec": 7800.0 - 0.125, "F_mid": 7800.0, "cost_usd": 6.25, "fee_usd": 1.4, "es_after": -1, "q": clip}])
    return path, fills, hedges


def test_clean_day_raises_no_alerts():
    path, fills, hedges = clean_day()
    tab, alerts = M.day_table(path, fills, hedges, MP)
    assert alerts == []
    assert tab.position_clips.iloc[-1] == 1.0 and tab.bought.iloc[-1] == 3900.0 and tab.net_flow.iloc[-1] == 3900.0
    assert abs(tab.delta_clips.iloc[-1]) < 0.02  # one clip long, one contract short


def test_every_fault_is_caught_by_its_rule():
    path, fills, hedges = clean_day()
    for fault in M.FAULTS:
        Pf, ff, hf = M.inject(path, fills, hedges, fault, t0=150, usd_line=False)
        _, alerts = M.day_table(Pf, ff, hf, MP, usd_line=False)
        rules = {a.rule for a in alerts}
        assert rules & set(M.RULE_FOR_FAULT[fault]), (fault, rules)


def test_recon_catches_a_phantom_fill_only():
    path, fills, hedges = clean_day()
    Pf, ff, hf = M.inject(path, fills, hedges, "phantom_fill", t0=200)
    _, alerts = M.day_table(Pf, ff, hf, MP)
    assert any(a.rule == "RECON" for a in alerts)
    _, clean = M.day_table(path, fills, hedges, MP)
    assert not any(a.rule == "RECON" for a in clean)
