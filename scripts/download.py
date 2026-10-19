#!/usr/bin/env python3
"""Every download.   python scripts/download.py [--only yahoo_daily|yahoo_1m|rates|issuer] [--since 2019-01-01]

Yahoo chart API   daily bars since 2019 with dividends for the four ETF lines, SPY, ^GSPC, ES=F, GBPUSD=X, EURUSD=X
                  -> data/reference/daily.parquet, dividends.parquet, symbols.json (currency, exchange, tz from Yahoo's meta);
                  1-minute bars over the trailing 30 days (Yahoo's limit) in 7-day windows -> data/intraday/bars_1m.parquet,
                  appended on each run so the archive grows beyond 30 days (keyed on symbol, ts).
Rates             US Treasury daily par curve (1m..1y), NY Fed SOFR and EFFR, ECB EUR short-term rate, Bank of England SONIA
                  -> data/reference/rates.parquet (percent).
Issuer files      iShares Core S&P 500 UCITS ETF (CSPX / SXR8 are one fund, IE00B5BMR087): daily NAV history and key facts from
                  the product-data API behind the product page -> data/reference/issuer/CSPX_nav.parquet, CSPX_keyfacts.json.
                  Vanguard S&P 500 UCITS ETF (VUSA IE00B3XXRP09, VUAA IE00BFMXXD54): the latest NAV and the short price table of
                  the server-rendered professional product pages -> issuer/VUSA_page_nav.parquet, VUAA_page_nav.parquet.
                  Each attempt and its outcome is written to data/reference/issuer_status.json; where a NAV history is missing
                  the pipeline strikes the fund/index ratio from the line's own closing prints (stated per line in docs/method.md).
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from etfmm import data as D  # noqa: E402
from etfmm.vendor import yahoo as Y  # noqa: E402

LOG = None


def log(*a):
    global LOG
    if LOG is None:
        os.makedirs(D.DATA, exist_ok=True)
        LOG = open(os.path.join(D.DATA, "download.log"), "a", encoding="utf-8")
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(f"{dt.datetime.now(dt.UTC).isoformat()} {s}\n")
    LOG.flush()


def symbols() -> list[str]:
    cfg = D.lines()
    syms = [v["yahoo"] for v in cfg.values()]
    return syms + ["SPY", "^GSPC", "ES=F", "GBPUSD=X", "EURUSD=X"]


# ----------------------------------------------------------------------------- yahoo
def do_yahoo_daily(since: str):
    frames, divs, meta = [], [], {}
    for s in symbols():
        df, dv, m = Y.yahoo_daily(s, since)
        if df.empty:
            log("daily: no data", s)
            continue
        frames.append(df)
        if not dv.empty:
            divs.append(dv)
        meta[s] = m
        log("daily", s, len(df), df.date.min().date(), df.date.max().date(), m.get("currency"), m.get("fullExchangeName"))
        time.sleep(0.3)
    os.makedirs(D.REF, exist_ok=True)
    pd.concat(frames).to_parquet(os.path.join(D.REF, "daily.parquet"), index=False, compression="zstd")
    if divs:
        pd.concat(divs).sort_values(["symbol", "ex_date"]).to_parquet(os.path.join(D.REF, "dividends.parquet"), index=False)
    json.dump(meta, open(os.path.join(D.REF, "symbols.json"), "w"), indent=1)


def do_yahoo_1m():
    os.makedirs(D.INTRA, exist_ok=True)
    frames = []
    for s in symbols():
        df = Y.yahoo_intraday_1m(s)
        if df.empty:
            log("1m: no data", s)
            continue
        frames.append(df)
        log("1m", s, len(df), int(df.close.notna().sum()), "with a trade;", df.ts.min(), "..", df.ts.max())
        time.sleep(0.3)
    if not frames:
        return
    new = pd.concat(frames)
    path = os.path.join(D.INTRA, "bars_1m.parquet")
    if os.path.exists(path):
        old = pd.read_parquet(path)
        new = pd.concat([old, new])
    new = new.drop_duplicates(["symbol", "ts"], keep="last").sort_values(["symbol", "ts"]).reset_index(drop=True)
    new.to_parquet(path, index=False, compression="zstd")
    log("1m archive", len(new), new.ts.min(), "..", new.ts.max())


# ----------------------------------------------------------------------------- rates
def nyfed(kind: str, name: str, since_year: int) -> pd.DataFrame:
    out = []
    for y in range(since_year, dt.date.today().year + 1):
        url = f"https://markets.newyorkfed.org/api/rates/{kind}/{name.lower()}/search.json?startDate={y}-01-01&endDate={y}-12-31"
        try:
            d = json.loads(Y.get(url))
        except Exception as e:  # noqa: BLE001
            log("nyfed fail", name, y, str(e)[:60])
            continue
        out += [{"date": pd.Timestamp(r["effectiveDate"]), name: float(r["percentRate"])} for r in d.get("refRates", [])]
        time.sleep(0.2)
    return pd.DataFrame(out).drop_duplicates("date") if out else pd.DataFrame(columns=["date", name])


def ecb_estr() -> pd.DataFrame:
    url = "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT?format=csvdata"
    try:
        df = pd.read_csv(io.BytesIO(Y.get(url)))
    except Exception as e:  # noqa: BLE001
        log("ecb fail", str(e)[:60])
        return pd.DataFrame(columns=["date", "ESTR"])
    return pd.DataFrame({"date": pd.to_datetime(df["TIME_PERIOD"]), "ESTR": df["OBS_VALUE"].astype(float)})


def boe_sonia(since: str) -> pd.DataFrame:
    d0 = pd.Timestamp(since).strftime("%d/%b/%Y")
    url = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=" + d0 +
           "&Dateto=now&SeriesCodes=IUDSOIA&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    try:
        raw = Y.get(url)
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        log("boe fail", str(e)[:60])
        return pd.DataFrame(columns=["date", "SONIA"])
    cols = list(df.columns)
    out = pd.DataFrame({"date": pd.to_datetime(df[cols[0]], format="%d %b %Y", errors="coerce"), "SONIA": pd.to_numeric(df[cols[1]], errors="coerce")})
    return out.dropna()


def treasury_par(since_year: int) -> pd.DataFrame:
    frames = []
    for y in range(since_year, dt.date.today().year + 1):
        url = (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
               f"?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
        try:
            df = pd.read_csv(io.BytesIO(Y.get(url)))
        except Exception as e:  # noqa: BLE001
            log("treasury fail", y, str(e)[:60])
            continue
        df.columns = [c.strip() for c in df.columns]
        df["date"] = pd.to_datetime(df["Date"])
        keep = {"1 Mo": "tbill_1m", "2 Mo": "tbill_2m", "3 Mo": "tbill_3m", "6 Mo": "tbill_6m", "1 Yr": "tsy_1y"}
        cols = {k: v for k, v in keep.items() if k in df.columns}
        frames.append(df[["date"] + list(cols)].rename(columns=cols))
        time.sleep(0.3)
    return pd.concat(frames).sort_values("date") if frames else pd.DataFrame(columns=["date"])


def do_rates(since: str):
    y0 = int(since[:4])
    r = treasury_par(y0)
    for kind, name in (("secured", "SOFR"), ("unsecured", "EFFR")):
        x = nyfed(kind, name, y0)
        r = r.merge(x, on="date", how="outer") if not x.empty else r
    for x in (ecb_estr(), boe_sonia(since)):
        if not x.empty:
            x = x[x.date >= pd.Timestamp(since)]
            r = r.merge(x, on="date", how="outer")
    r = r.sort_values("date").reset_index(drop=True)
    for c in r.columns:
        if c != "date":
            r[c] = pd.to_numeric(r[c], errors="coerce")
    os.makedirs(D.REF, exist_ok=True)
    r.to_parquet(os.path.join(D.REF, "rates.parquet"), index=False)
    log("rates", len(r), r.date.min().date(), r.date.max().date(), list(r.columns))


# ----------------------------------------------------------------------------- issuer files
ISHARES_PAGE = "https://www.ishares.com/uk/professional/en/products/253743/ishares-sp-500-b-ucits-etf-acc-fund"
ISHARES_API = "https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/get-product-data"
ISHARES_HDR = {"Accept": "application/json", "Referer": ISHARES_PAGE, "Accept-Language": "en-GB,en;q=0.9"}
VANGUARD_PAGES = {"VUSA": "https://www.vanguard.co.uk/professional/product/etf/equity/9503/sp-500-ucits-etf-usd-distributing",
                  "VUAA": "https://www.vanguard.co.uk/professional/product/etf/equity/9694/sp-500-ucits-etf"}


def _try(url: str, headers: dict | None = None) -> tuple[bytes | None, str]:
    try:
        raw = Y.get(url, retries=2, timeout=60, headers=headers)
        return raw, f"ok {len(raw)} bytes"
    except Exception as e:  # noqa: BLE001
        return None, f"fail: {str(e)[:80]}"


def ishares_component(component: str) -> dict | None:
    url = (f"{ISHARES_API}?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=ishares-uk&locale=en_GB&portfolioId=253743"
           f"&component={component}&userType=institutional")
    raw, msg = _try(url, ISHARES_HDR)
    if raw is None or b"<html" in raw[:400].lower():
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def _datapoints(d: dict, component: str, container: str) -> dict:
    c = d["componentsByNameMap"][component]["containersByNameMap"][container]["dataPointsByNameMap"]
    return {k: (v.get("formattedValue", v.get("value")), v.get("formattedAsOfDate")) for k, v in c.items() if isinstance(v, dict)}


def ishares_nav_history() -> pd.DataFrame:
    """The product page's NAV chart series (daily NAV per share in USD since 2010)."""
    d = ishares_component("performance")
    if d is None:
        raise RuntimeError("iShares product-data API: html or no data")
    nav = d["componentsByNameMap"]["performance"]["containersByNameMap"]["chart"]["dataPointsByNameMap"]["navData"]
    dates = pd.to_datetime([str(x) for x in nav["asOfDate"]], format="%Y%m%d")
    vals = pd.to_numeric(pd.Series(nav["value"]), errors="coerce").to_numpy()
    return pd.DataFrame({"date": dates, "nav": vals, "currency": "USD"}).dropna().sort_values("date").reset_index(drop=True)


def vanguard_page_nav(html: str) -> pd.DataFrame:
    """The professional product page is server-rendered; its price table carries (GBP market price, date, USD NAV) rows and
    the header the latest NAV.  Returns the rows found (date, nav_usd, price_gbp)."""
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"\s+", " ", txt)
    rows = []
    for m in re.finditer(r"(?:\u00a3|&pound;)\s?([0-9]+\.[0-9]+)\s+(\d{2} [A-Z][a-z]{2} \d{4})\s+US\$\s?([0-9]+\.[0-9]+)", txt):
        rows.append({"date": pd.Timestamp(m.group(2)), "price_gbp": float(m.group(1)), "nav_usd": float(m.group(3))})
    hdr = re.search(r"NAV Price \(USD\)\s*US\$\s?([0-9]+\.[0-9]+).{0,200}?At closure (\d{2} [A-Z][a-z]{2} \d{4})", txt)
    if hdr:
        rows.append({"date": pd.Timestamp(hdr.group(2)), "price_gbp": np.nan, "nav_usd": float(hdr.group(1))})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.groupby("date", as_index=False).agg(nav_usd=("nav_usd", "last"), price_gbp=("price_gbp", "max")).sort_values("date")


def do_issuer():
    out_dir = os.path.join(D.REF, "issuer")
    os.makedirs(out_dir, exist_ok=True)
    status = {"checked": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "attempts": []}
    # iShares Core S&P 500 UCITS ETF (IE00B5BMR087; CSPX on LSE and SXR8 on Xetra are lines of this fund): the product-data API
    # behind the product page.  The older .ajax file endpoints return the page's html (recorded in the first run's status).
    rec = {"source": "iShares", "name": "CSPX_nav", "url": ISHARES_API + "?...&portfolioId=253743&component=performance"}
    try:
        nav = ishares_nav_history()
        p = os.path.join(out_dir, "CSPX_nav.parquet")
        nav.to_parquet(p, index=False)
        rec.update({"result": f"ok {len(nav)} rows", "file": os.path.relpath(p, ROOT).replace("\\", "/"), "first": str(nav.date.iloc[0].date()),
                    "last": str(nav.date.iloc[-1].date()), "last_nav": float(nav.nav.iloc[-1])})
    except Exception as e:  # noqa: BLE001
        rec["result"] = f"fail: {str(e)[:80]}"
    status["attempts"].append(rec)
    log("issuer", rec["name"], rec["result"])
    rec = {"source": "iShares", "name": "CSPX_keyfacts", "url": ISHARES_API + "?...&portfolioId=253743&component=keyFundFacts"}
    try:
        kf = ishares_component("keyFundFacts")
        ls = ishares_component("listings")
        facts = {k: v for k, v in _datapoints(kf, "keyFundFacts", "default").items()}
        facts["_listings"] = {k: v[0] for k, v in _datapoints(ls, "listings", "default").items()} if ls else {}
        p = os.path.join(out_dir, "CSPX_keyfacts.json")
        json.dump(facts, open(p, "w", encoding="utf-8"), indent=1, default=str)
        rec.update({"result": "ok", "file": os.path.relpath(p, ROOT).replace("\\", "/"),
                    "ter": facts.get("emeaMgt", [None])[0], "shares_outstanding": facts.get("sharesOutstanding", [None])[0]})
    except Exception as e:  # noqa: BLE001
        rec["result"] = f"fail: {str(e)[:80]}"
    status["attempts"].append(rec)
    log("issuer", rec["name"], rec["result"])
    # Vanguard S&P 500 UCITS ETF (VUSA IE00B3XXRP09 distributing, VUAA IE00BFMXXD54 accumulating): the professional product
    # pages are server-rendered with the latest NAV and a short price table; the investor-site json endpoints return html.
    for line, url in VANGUARD_PAGES.items():
        rec = {"source": "Vanguard", "name": f"{line}_page_nav", "url": url}
        raw, msg = _try(url, {"Accept": "text/html", "Accept-Language": "en-GB,en;q=0.9"})
        if raw is None:
            rec["result"] = msg
        else:
            try:
                df = vanguard_page_nav(raw.decode("utf-8", "ignore"))
                if df.empty:
                    rec["result"] = "fail: no NAV rows found in the page"
                else:
                    p = os.path.join(out_dir, f"{line}_page_nav.parquet")
                    df.to_parquet(p, index=False)
                    rec.update({"result": f"ok {len(df)} rows", "file": os.path.relpath(p, ROOT).replace("\\", "/"),
                                "last": str(df.date.iloc[-1].date()), "last_nav_usd": float(df.nav_usd.iloc[-1])})
            except Exception as e:  # noqa: BLE001
                rec["result"] = f"fail: {str(e)[:80]}"
        status["attempts"].append(rec)
        log("issuer", rec["name"], rec["result"])
        time.sleep(1)
    json.dump(status, open(os.path.join(D.REF, "issuer_status.json"), "w"), indent=1)


def main(argv):
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    since = argv[argv.index("--since") + 1] if "--since" in argv else "2019-01-01"
    steps = {"yahoo_daily": lambda: do_yahoo_daily(since), "yahoo_1m": do_yahoo_1m, "rates": lambda: do_rates(since), "issuer": do_issuer}
    for name, fn in steps.items():
        if only is None or only == name:
            log("==", name)
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                log("STEP FAILED", name, repr(e)[:200])
    log("done")


if __name__ == "__main__":
    main(sys.argv[1:])
