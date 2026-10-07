"""The creation/redemption arbitrage bound, in bp of the unit notional, by number of units.

An arbitrageur who sees the line trade above fair sells it, buys the hedge, and at the end of the day delivers the basket
(or cash) to the issuer for new shares.  The premium has to pay, per unit of notional N = n x unit_shares x NAV:

    fixed fee / N                 the issuer's per-order charge (custody/transaction fee), amortised over the n units
  + basket cost                   the half-spread paid to buy or sell the S&P 500 basket (the variable part of a cash creation's
                                  Duties and Charges / Cash Creation Fee, or the AP's own execution when dealing in kind)
  + hedge cost                    half a tick on the E-mini plus the exchange fee, per contract, in bp of notional
  + FX cost                       one conversion of the notional for a line that trades in GBP or EUR (0 for USD lines)
  + settlement financing          the overnight rate for the days between the ETF's T+2 settlement and the US basket's T+1

Below the bound, the premium cannot be arbitraged away through the primary market; a quoter whose half-spread is inside it is
the one who keeps the line near fair.  The same sum with the fixed fee spread over one unit is the per-share cost of
redeeming an end-of-day inventory, used by the quoter's create_redeem end-of-day mode.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def bound_bp(n_units: int, unit_shares: int, nav_usd: float, fixed_fee_usd: float, basket_half_spread_bp: float, es_price: float,
             es_tick: float, es_multiplier: float, es_fee_usd: float, es_half_spread_ticks: float, fx_half_spread_bp: float,
             overnight_rate: float, settlement_days: int) -> dict:
    notional = n_units * unit_shares * nav_usd
    fixed = fixed_fee_usd / notional * 1e4
    contracts = notional / (es_multiplier * es_price)
    hedge = (contracts * (es_half_spread_ticks * es_tick * es_multiplier + es_fee_usd)) / notional * 1e4
    settle = overnight_rate * settlement_days / 360.0 * 1e4
    total = fixed + basket_half_spread_bp + hedge + fx_half_spread_bp + settle
    return {"n_units": n_units, "notional_usd": notional, "fixed_fee_bp": fixed, "basket_bp": basket_half_spread_bp, "hedge_bp": hedge,
            "fx_bp": fx_half_spread_bp, "settlement_bp": settle, "bound_bp": total, "es_contracts": contracts}


def bound_table(lines: dict, navs: dict, es_price: float, overnight_rate: float, params: dict) -> pd.DataFrame:
    """One row per line and unit count; plus the sensitivity rows (fixed fee, basket cost, settlement days) at one unit."""
    b, q = params["bound"], params["quoter"]
    fv = params["fair_value"]
    rows = []
    for name, cfg in lines.items():
        fx = 0.0 if cfg["currency"] == "USD" else b["fx_half_spread_bp"]
        base = dict(unit_shares=cfg["creation_unit_shares"], nav_usd=navs[name], basket_half_spread_bp=b["basket_half_spread_bp"], es_price=es_price,
                    es_tick=fv["futures_tick"], es_multiplier=fv["futures_multiplier"], es_fee_usd=q["es_fee_usd_per_contract"],
                    es_half_spread_ticks=b["es_half_spread_ticks"], fx_half_spread_bp=fx, overnight_rate=overnight_rate)
        for n in b["units"]:
            r = bound_bp(n, fixed_fee_usd=b["fixed_fee_usd"], settlement_days=b["settlement_mismatch_days"], **base)
            rows.append({"line": name, "case": "base", **r, "fixed_fee_usd": b["fixed_fee_usd"], "settlement_days": b["settlement_mismatch_days"],
                         "unit_published": cfg.get("creation_unit_published", False)})
        for fee in b["fixed_fee_usd_grid"]:
            r = bound_bp(1, fixed_fee_usd=fee, settlement_days=b["settlement_mismatch_days"], **base)
            rows.append({"line": name, "case": "fixed_fee", **r, "fixed_fee_usd": fee, "settlement_days": b["settlement_mismatch_days"], "unit_published": cfg.get("creation_unit_published", False)})
        for d in b["settlement_mismatch_days_grid"]:
            r = bound_bp(1, fixed_fee_usd=b["fixed_fee_usd"], settlement_days=d, **base)
            rows.append({"line": name, "case": "settlement_days", **r, "fixed_fee_usd": b["fixed_fee_usd"], "settlement_days": d, "unit_published": cfg.get("creation_unit_published", False)})
        for bs in b["basket_half_spread_bp_grid"]:
            r = bound_bp(1, fixed_fee_usd=b["fixed_fee_usd"], settlement_days=b["settlement_mismatch_days"], **{**base, "basket_half_spread_bp": bs})
            rows.append({"line": name, "case": "basket_bp", **r, "fixed_fee_usd": b["fixed_fee_usd"], "settlement_days": b["settlement_mismatch_days"], "unit_published": cfg.get("creation_unit_published", False)})
    return pd.DataFrame(rows)


def per_share_redemption_bp(line_cfg: dict, nav_usd: float, es_price: float, overnight_rate: float, params: dict) -> float:
    """The one-unit bound: what redeeming end-of-day inventory costs per share, in bp, with the fixed fee spread over one unit."""
    b, q, fv = params["bound"], params["quoter"], params["fair_value"]
    fx = 0.0 if line_cfg["currency"] == "USD" else b["fx_half_spread_bp"]
    r = bound_bp(1, line_cfg["creation_unit_shares"], nav_usd, b["fixed_fee_usd"], b["basket_half_spread_bp"], es_price, fv["futures_tick"],
                 fv["futures_multiplier"], q["es_fee_usd_per_contract"], b["es_half_spread_ticks"], fx, overnight_rate, b["settlement_mismatch_days"])
    return float(r["bound_bp"])
