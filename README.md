# etf-mm-europe

A two-way quote on four UCITS S&P 500 ETF lines, priced from the E-mini and hedged in it, replayed on 1-minute bars in a Python package (`etfmm`): a fair value from ES, the creation/redemption bound, the quoter with a P&L attribution, and a positions monitor. The lines are CSPX, VUAA and VUSA on the LSE and SXR8 on Xetra. All data is free and checked in.

The question: how wide must the quote be to clear the creation bound and the hedge, and what does a fill earn?

## Results

- **Fair value.** Over 20 days of 1-minute bars (2026-09-09 to 2026-10-07) the lines trade 3.0–3.3 bp (sd) around the fair value implied by ES. They close 2.1–6.0 bp above their NAV-implied fair, so the quoter centres on each line's own closes.
- **Break-even.** With quotes fixed for the minute, and a fill only when a bar trades through the quote, the break-even half-spread is 3.9 to 6.7 bp (SXR8 never breaks even). The one-unit creation bound is 3.1 to 5.0 bp, so only VUSA clears it.
- **Adverse selection.** At a 3 bp half-spread the book loses 0.8 to 2.3 bp per fill: it captures 2.7–3.2 bp and gives 1.8–4.7 bp back before the hedge a minute later, because a bar that trades through a quote is mostly a bar in which the index moved. If the quotes follow ES inside the minute, the break-even drops to 0.5 bp on CSPX, VUAA and VUSA. A quoter re-pricing on every ES tick sits between the two.
- **FX.** Converting local cash once a day costs VUSA 1.0 bp and SXR8 1.9 bp per fill, since the quoter's flow runs against the day's spot move. Converting every fill instead moves VUSA's break-even from 3.9 to 5.2 bp but gives SXR8 a break-even of 4.9 bp: the FX policy is a per-line choice.
- **Monitor.** The positions monitor catches 91% of planted faults (9 kinds) within 15 minutes, with 0.26 false alerts per clean line-day.

| line | venue | break-even, fixed quotes (bp) | break-even, quotes follow ES (bp) | one-unit bound (bp) | P&L per fill at 3 bp (bp) |
|---|---|---|---|---|---|
| CSPX | LSE, USD | 5.8 [3.5, 8.1] | 0.5 | 3.1 | -1.0 |
| VUAA | LSE, USD | 6.7 [2.5, 10.6] | 0.5 | 4.4 | -1.3 |
| VUSA | LSE, GBP | 3.9 [3.2, 8.3] | 0.5 | 5.0 | -0.8 |
| SXR8 | Xetra, EUR | none on the grid [4.3, 11.5] | 3.7 | 3.6 | -2.3 |

![pnl](figures/pnl_curve.png)
![replay](figures/replay_day.png)

All numbers are in `results/summary.md`; the detail is in [docs/method.md](docs/method.md).

## How it works

$$E^* = \frac{I_{\mathrm{fair}}}{\kappa X}, \qquad I_{\mathrm{fair}} = \frac{F + D}{1 + r\tau}\,(1 - \rho_c)$$

$$\mathrm{bid},\ \mathrm{ask} = E^*\,(1 - s\,q)\,(1 \mp h)$$

- **Data.** Yahoo 1-minute bars for the lines, ES and FX over the trailing 30 days (archived on each run), daily bars since 2019, Treasury, SOFR, €STR and SONIA rates, and the issuers' NAVs and prospectuses.
- **Fair value.** $E^*$ is a line's fair price: the index implied by the E-mini $F$ with bill financing $r$ and dividends $D$ (from [delta-one-basis](https://github.com/m-ichaels/delta-one-basis)), less the contract's richness $\rho_c$ to the cash index, over the fund/index ratio $\kappa$ and the spot rate $X$.
- **Quoter.** Quotes skew by $s$ = 1 bp per clip of inventory $q$ and are pulled on stale inputs or fast markets. A quote fills when a bar trades a tick through it, and each fill is hedged in whole E-minis at the next bar. P&L splits exactly into capture, hedge slippage, FX, inventory and fees.
- **Bound and break-even.** The bound adds the creation fee per unit, the basket half-spread, the hedge, an FX conversion and a day of T+2/T+1 settlement financing. The break-even is where P&L per fill crosses zero, with a block bootstrap over days.
- **Monitor.** Position, delta, FX exposure and P&L by minute, with rules scored against faults planted in real days.

## Limitations

- One-minute bars are not a tick book: queue position is unknown, so the result is a bracket, not a point.
- 20 quoting days: wide intervals, one contract roll and no stress day.
- The creation fee and the iShares unit size are not published, and the basket cost is assumed; `docs/method.md` shows how far they move the bound.
- The faulted monitor days are simulated.

## Run

```
pip install -e .[test]
python -m pytest                      # 19 tests
scripts/run_all.sh --skip-download    # the pipeline on the checked-in data
```

The README and `docs/method.md` are written by `scripts/readme.py` from `results/`. CI runs the pipeline on the checked-in data and checks both against the results.
