"""Venue sessions.  The bars carry the trading days; this module says which minutes of a day are continuous trading
and which belong to the auctions, in the venue's local time (configs/lines.json, with the sources in configs/sources.json).

LSE (SETS / ETF order book): opening auction 07:50-08:00, continuous trading 08:00-16:30, closing auction 16:30-16:35.
Xetra: opening auction 08:50-09:00, continuous trading 09:00-17:30, closing auction 17:30-17:35 (CET/CEST).
Yahoo's 1-minute grid for the LSE lines runs 08:00-16:30 London (the 16:30 bar is the closing-auction print);
the Xetra grid runs 09:00-17:30 Berlin, which is the same UTC window as London's while both are on summer time.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SESSIONS = {
    "LSE": {"tz": "Europe/London", "open": "08:00", "close": "16:30", "close_auction_end": "16:35"},
    "Xetra": {"tz": "Europe/Berlin", "open": "09:00", "close": "17:30", "close_auction_end": "17:35"},
    "CME": {"tz": "America/New_York", "open": "18:00", "close": "17:00", "maintenance": ("17:00", "18:00")},
}


def local(ts: pd.Series, tz: str) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.tz_convert(ZoneInfo(tz))


def minutes_from_open(ts: pd.Series, venue: str) -> np.ndarray:
    """Minutes since the venue's continuous-trading open for each (UTC) bar start."""
    s = SESSIONS[venue]
    lt = local(ts, s["tz"])
    h, m = map(int, s["open"].split(":"))
    return ((lt.dt.hour - h) * 60 + (lt.dt.minute - m)).to_numpy()


def session_length_minutes(venue: str) -> int:
    s = SESSIONS[venue]
    h0, m0 = map(int, s["open"].split(":"))
    h1, m1 = map(int, s["close"].split(":"))
    return (h1 - h0) * 60 + (m1 - m0)


def is_continuous(ts: pd.Series, venue: str, skip_open: int = 0, skip_close: int = 0) -> np.ndarray:
    """True for bars inside continuous trading, excluding the first `skip_open` minutes after the open and the last
    `skip_close` minutes before the close (the closing-auction bar is never continuous)."""
    k = minutes_from_open(ts, venue)
    n = session_length_minutes(venue)
    return (k >= skip_open) & (k < n - skip_close)


def trading_date(ts: pd.Series, venue: str) -> pd.Series:
    return local(ts, venue if venue in ("Europe/London", "Europe/Berlin", "America/New_York") else SESSIONS[venue]["tz"]).dt.date


def us_cash_open(ts: pd.Series) -> np.ndarray:
    """True when the US cash session is open (09:30-16:00 New York) at the bar start."""
    lt = local(ts, "America/New_York")
    mins = lt.dt.hour * 60 + lt.dt.minute
    return ((mins >= 9 * 60 + 30) & (mins < 16 * 60)).to_numpy()
