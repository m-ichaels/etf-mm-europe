# etf-mm-europe — run summary (2026-10-07; quoter grid [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15], base h 3 bp, 1000 bootstrap draws, 142.9 s)

Data: 1-minute bars 2026-09-08 .. 2026-10-07 (155307 rows, 9 symbols); 20 quoting days per line (the first day strikes kappa). ES contract switch in Yahoo's continuous series: 2026-09-18 -> 2026-12-18 at 2026-09-14 15:30 UTC (90 bp jump, cash index confirms: True). Richness of the implied index to the cash index (bp, median over the US session, removed from the fair): 2026-09-18: -1.6, 2026-12-18: +8.5.

## Break-even half-spread against the creation/redemption bound (bp)

| line | break-even h* (fixed quotes) | 95% CI | h* (quotes track ES within the bar) | bound, 1 unit | bound, 10 units | hedge cost | P&L/fill at h=3 (bp) | clears bound |
|---|---|---|---|---|---|---|---|---|
| CSPX | 5.84 | [3.52, 8.10] | 0.50 | 3.13 | 2.81 | 0.20 | -0.96 [-1.43, -0.35] | no |
| VUAA | 6.68 | [2.51, 10.58] | 0.50 | 4.43 | 2.94 | 0.20 | -1.34 [-3.76, 1.18] | no |
| VUSA | 3.85 | [3.21, 8.25] | 0.50 | 4.97 | 3.45 | 0.20 | -0.81 [-1.61, -0.14] | yes |
| SXR8 | none | [4.34, 11.53] | 3.70 | 3.63 | 3.31 | 0.20 | -2.33 [-4.06, -0.44] | no |

## Premium / discount to the ES-implied fair (1-minute closes, continuous trading)

| line | venue | currency | days | minutes | mean | sd | within-day sd | q05 | median | q95 | share |prem|>5bp | mean vs NAV-fair | NAV days | median shares/day |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CSPX | LSE | USD | 20 | 9851 | -0.13 | 3.09 | 2.03 | -4.88 | -0.23 | 5.19 | 0.10 | 1.40 | 21 | 256483.00 |
| VUAA | LSE | USD | 20 | 9204 | 0.11 | 3.01 | 2.05 | -4.75 | 0.22 | 5.06 | 0.09 | 5.44 | 4 | 777157.00 |
| VUSA | LSE | GBP | 20 | 10163 | 0.06 | 3.25 | 2.26 | -5.08 | -0.07 | 5.54 | 0.12 | 5.50 | 4 | 742623.00 |
| SXR8 | Xetra | EUR | 20 | 7064 | 0.05 | 3.01 | 1.99 | -4.84 | -0.02 | 5.16 | 0.10 | 4.13 | 21 | 24107.00 |

## The quoter at the base half-spread: attribution per fill (bp of fill notional)

| line | fills | fills/day | notional (USD m) | median fill (shares) | clip (shares) | capture | hedge slip | FX | inventory | fees | total | USD/fill | total USD | identity gap USD | max |inv| (clips) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CSPX | 1266 | 63.30 | 172.86 | 68.00 | 467.00 | 2.70 | -3.18 | 0.00 | -0.15 | -0.33 | -0.96 | -13.17 | -16676.27 | 0.00 | 5.74 |
| VUAA | 471 | 23.60 | 37.52 | 57.00 | 2606.00 | 3.20 | -4.73 | 0.00 | 0.53 | -0.33 | -1.34 | -10.65 | -5015.58 | 0.00 | 5.22 |
| VUSA | 1901 | 95.00 | 231.50 | 272.00 | 2659.00 | 2.73 | -1.82 | -0.99 | -0.39 | -0.33 | -0.81 | -9.82 | -18676.83 | 0.00 | 5.70 |
| SXR8 | 820 | 41.00 | 40.70 | 18.00 | 467.00 | 2.88 | -3.23 | -1.85 | 0.21 | -0.33 | -2.33 | -11.56 | -9477.13 | -0.00 | 5.37 |

## P&L per fill by half-spread (bp), base case

- **CSPX**: h 0.5: -1.03 (8340 fills; capture +0.30, slip -1.02, fx +0.00, inv +0.03, fees -0.32); h 1: -0.94 (5937 fills; capture +0.74, slip -1.38, fx +0.00, inv +0.02, fees -0.33); h 1.5: -0.83 (4000 fills; capture +1.23, slip -1.89, fx +0.00, inv +0.16, fees -0.33); h 2: -0.90 (2667 fills; capture +1.70, slip -2.38, fx +0.00, inv +0.11, fees -0.33); h 2.5: -0.94 (1855 fills; capture +2.20, slip -2.76, fx +0.00, inv -0.05, fees -0.33); h 3: -0.96 (1266 fills; capture +2.70, slip -3.18, fx +0.00, inv -0.15, fees -0.33); h 4: -0.17 (685 fills; capture +3.68, slip -3.69, fx +0.00, inv +0.17, fees -0.33); h 5: -0.69 (413 fills; capture +4.68, slip -4.22, fx +0.00, inv -0.82, fees -0.33); h 6: +0.13 (276 fills; capture +5.69, slip -4.40, fx +0.00, inv -0.82, fees -0.33); h 8: +0.92 (127 fills; capture +7.67, slip -5.92, fx +0.00, inv -0.50, fees -0.33); h 10: +0.91 (60 fills; capture +9.70, slip -8.28, fx +0.00, inv -0.17, fees -0.34); h 12: -4.15 (33 fills; capture +11.77, slip -10.55, fx +0.00, inv -5.03, fees -0.34); h 15: +5.15 (16 fills; capture +14.75, slip -11.13, fx +0.00, inv +1.87, fees -0.34)
- **VUAA**: h 0.5: -1.80 (2644 fills; capture +0.72, slip -1.94, fx +0.00, inv -0.24, fees -0.33); h 1: -1.64 (1751 fills; capture +1.18, slip -2.46, fx +0.00, inv -0.03, fees -0.33); h 1.5: -2.59 (1219 fills; capture +1.67, slip -3.22, fx +0.00, inv -0.71, fees -0.34); h 2: -2.48 (846 fills; capture +2.18, slip -3.77, fx +0.00, inv -0.55, fees -0.34); h 2.5: -1.99 (622 fills; capture +2.69, slip -4.34, fx +0.00, inv -0.00, fees -0.34); h 3: -1.34 (471 fills; capture +3.20, slip -4.73, fx +0.00, inv +0.53, fees -0.33); h 4: -0.50 (278 fills; capture +4.12, slip -5.52, fx +0.00, inv +1.24, fees -0.34); h 5: -1.79 (170 fills; capture +5.19, slip -5.96, fx +0.00, inv -0.69, fees -0.34); h 6: -2.85 (102 fills; capture +6.26, slip -7.50, fx +0.00, inv -1.28, fees -0.33); h 8: +5.50 (52 fills; capture +8.42, slip -9.45, fx +0.00, inv +6.86, fees -0.33); h 10: -0.43 (26 fills; capture +10.48, slip -11.18, fx +0.00, inv +0.60, fees -0.34); h 12: -3.82 (19 fills; capture +12.56, slip -13.05, fx +0.00, inv -2.99, fees -0.34); h 15: -7.25 (11 fills; capture +15.14, slip -15.73, fx +0.00, inv -6.31, fees -0.35)
- **VUSA**: h 0.5: -1.08 (9309 fills; capture +0.37, slip -0.56, fx -0.45, inv -0.11, fees -0.32); h 1: -0.87 (7331 fills; capture +0.79, slip -0.74, fx -0.52, inv -0.07, fees -0.33); h 1.5: -0.63 (5395 fills; capture +1.25, slip -0.91, fx -0.65, inv -0.00, fees -0.33); h 2: -0.61 (3875 fills; capture +1.74, slip -1.13, fx -0.74, inv -0.15, fees -0.33); h 2.5: -0.43 (2743 fills; capture +2.23, slip -1.42, fx -0.83, inv -0.08, fees -0.33); h 3: -0.81 (1901 fills; capture +2.73, slip -1.82, fx -0.99, inv -0.39, fees -0.33); h 4: +0.14 (995 fills; capture +3.73, slip -2.25, fx -0.79, inv -0.22, fees -0.33); h 5: +0.57 (597 fills; capture +4.73, slip -2.63, fx -0.30, inv -0.89, fees -0.34); h 6: +1.36 (397 fills; capture +5.74, slip -2.91, fx -0.39, inv -0.73, fees -0.34); h 8: +3.41 (197 fills; capture +7.74, slip -3.13, fx +0.62, inv -1.49, fees -0.33); h 10: +5.21 (97 fills; capture +9.80, slip -2.76, fx +0.85, inv -2.35, fees -0.33); h 12: +3.56 (60 fills; capture +11.74, slip -3.35, fx -1.04, inv -3.45, fees -0.34); h 15: +7.33 (32 fills; capture +14.91, slip -1.25, fx -2.15, inv -3.85, fees -0.33)
- **SXR8**: h 0.5: -2.29 (4459 fills; capture +0.45, slip -1.31, fx -0.91, inv -0.19, fees -0.33); h 1: -1.71 (3188 fills; capture +0.93, slip -1.59, fx -0.80, inv +0.08, fees -0.33); h 1.5: -1.44 (2194 fills; capture +1.42, slip -1.96, fx -0.80, inv +0.23, fees -0.33); h 2: -2.11 (1553 fills; capture +1.91, slip -2.52, fx -0.89, inv -0.27, fees -0.33); h 2.5: -2.99 (1121 fills; capture +2.40, slip -2.87, fx -1.36, inv -0.83, fees -0.33); h 3: -2.33 (820 fills; capture +2.88, slip -3.23, fx -1.85, inv +0.21, fees -0.33); h 4: -3.52 (484 fills; capture +3.86, slip -3.67, fx -3.01, inv -0.37, fees -0.33); h 5: -0.53 (315 fills; capture +4.83, slip -4.30, fx -1.31, inv +0.58, fees -0.33); h 6: -1.61 (206 fills; capture +5.82, slip -5.44, fx +0.29, inv -1.94, fees -0.33); h 8: -1.17 (64 fills; capture +7.85, slip -8.70, fx +0.15, inv -0.13, fees -0.34); h 10: -7.02 (22 fills; capture +10.01, slip -14.20, fx +1.47, inv -3.97, fees -0.34); h 12: -8.83 (11 fills; capture +11.97, slip -18.00, fx +4.32, inv -6.78, fees -0.34); h 15: +0.16 (5 fills; capture +14.81, slip -19.15, fx -0.33, inv +5.21, fees -0.38)

## Sensitivity: break-even half-spread (bp) by case

| case | CSPX h* | VUAA h* | VUSA h* | SXR8 h* | CSPX P&L/fill at base h | VUAA P&L/fill at base h | VUSA P&L/fill at base h | SXR8 P&L/fill at base h |
|---|---|---|---|---|---|---|---|---|
| base | 5.84 | 6.68 | 3.85 | none | -0.96 | -1.34 | -0.81 | -2.33 |
| eod=create_redeem | 6.60 | none | 3.30 | none | -0.90 | -2.39 | -0.21 | -3.00 |
| eod=flatten_close | 12.36 | none | 3.61 | none | -1.23 | -3.35 | -0.34 | -4.07 |
| fx_hedge=fill | nan | nan | 5.24 | 4.91 | nan | nan | -0.98 | -1.60 |
| hedge_delay=2 | 6.06 | 6.85 | 4.41 | none | -0.90 | -1.05 | -0.88 | -2.49 |
| hedge_delay=5 | 7.94 | 6.61 | 4.19 | none | -0.99 | -1.30 | -0.74 | -2.85 |
| kappa=nav | 4.92 | nan | nan | none | -0.73 | nan | nan | -5.50 |
| participation=0.25 | 3.70 | 5.94 | 3.89 | 3.77 | -0.81 | -0.86 | -0.87 | -3.79 |
| participation=1.0 | 4.93 | 10.34 | 3.66 | 11.56 | -0.89 | -1.75 | -0.35 | -2.09 |
| quotes_track_es | 0.50 | 0.50 | 0.50 | 3.70 | 3.03 | 2.79 | 1.27 | -8.78 |
| quotes_track_es+recentre | 0.50 | 0.50 | 0.50 | 2.09 | 4.85 | 12.57 | 3.59 | 10.83 |
| recentre=30min | 3.94 | none | 3.21 | 5.09 | -1.09 | -2.58 | -0.13 | -1.85 |
| skew=0 | 4.27 | 5.49 | 4.19 | 5.55 | -0.43 | -2.61 | -0.51 | -4.24 |
| through_ticks=0 | 4.64 | 8.75 | 3.54 | 5.97 | -0.59 | -0.88 | -0.30 | -2.53 |
| through_ticks=2 | 7.38 | 7.81 | 4.48 | 4.93 | -0.82 | -5.33 | -0.70 | -2.86 |

## The creation/redemption bound (bp of unit notional)

| line | n_units | notional (USD m) | fixed_fee_bp | basket_bp | hedge_bp | fx_bp | settlement_bp | bound_bp | unit_published |
|---|---|---|---|---|---|---|---|---|---|
| CSPX | 1 | 42.18 | 0.36 | 1.50 | 0.20 | 0.00 | 1.08 | 3.13 | False |
| CSPX | 2 | 84.35 | 0.18 | 1.50 | 0.20 | 0.00 | 1.08 | 2.96 | False |
| CSPX | 5 | 210.89 | 0.07 | 1.50 | 0.20 | 0.00 | 1.08 | 2.85 | False |
| CSPX | 10 | 421.77 | 0.04 | 1.50 | 0.20 | 0.00 | 1.08 | 2.81 | False |
| VUAA | 1 | 9.06 | 1.66 | 1.50 | 0.20 | 0.00 | 1.08 | 4.43 | True |
| VUAA | 2 | 18.11 | 0.83 | 1.50 | 0.20 | 0.00 | 1.08 | 3.61 | True |
| VUAA | 5 | 45.28 | 0.33 | 1.50 | 0.20 | 0.00 | 1.08 | 3.11 | True |
| VUAA | 10 | 90.56 | 0.17 | 1.50 | 0.20 | 0.00 | 1.08 | 2.94 | True |
| VUSA | 1 | 8.89 | 1.69 | 1.50 | 0.20 | 0.50 | 1.08 | 4.97 | True |
| VUSA | 2 | 17.78 | 0.84 | 1.50 | 0.20 | 0.50 | 1.08 | 4.12 | True |
| VUSA | 5 | 44.44 | 0.34 | 1.50 | 0.20 | 0.50 | 1.08 | 3.62 | True |
| VUSA | 10 | 88.88 | 0.17 | 1.50 | 0.20 | 0.50 | 1.08 | 3.45 | True |
| SXR8 | 1 | 42.18 | 0.36 | 1.50 | 0.20 | 0.50 | 1.08 | 3.63 | False |
| SXR8 | 2 | 84.35 | 0.18 | 1.50 | 0.20 | 0.50 | 1.08 | 3.46 | False |
| SXR8 | 5 | 210.89 | 0.07 | 1.50 | 0.20 | 0.50 | 1.08 | 3.35 | False |
| SXR8 | 10 | 421.77 | 0.04 | 1.50 | 0.20 | 0.50 | 1.08 | 3.31 | False |

Inputs: ES 7844.00 (2026-10-07), SOFR 3.90 %, NAVs CSPX 843.55 (issuer NAV 2026-10-06), VUAA 150.93 (issuer NAV 2026-10-07), VUSA 148.13 (issuer NAV 2026-10-06), SXR8 843.55 (issuer NAV 2026-10-06); assumptions {'fixed_fee_usd': 1500, 'basket_half_spread_bp': 1.5, 'es_half_spread_ticks': 0.5, 'fx_half_spread_bp': 0.5, 'settlement_mismatch_days': 1}. Sensitivity (one unit): fixed fee CSPX $500: 2.90; CSPX $1500: 3.13; CSPX $3000: 3.49; CSPX $5000: 3.96 ...; settlement days CSPX 0 d: 2.05; CSPX 1 d: 3.13; CSPX 2 d: 4.22 ... (results/bound.csv).

## Kappa and the premium to NAV

- **CSPX**: 21 days (2026-09-09 .. 2026-10-07); issuer NAV on 21 days from CSPX_nav; median (self kappa / NAV kappa - 1): -1.75 bp; median closing premium to the self fair 0.50 bp, to the NAV fair 2.07 bp.
- **VUAA**: 21 days (2026-09-09 .. 2026-10-07); issuer NAV on 4 days from VUAA_page_nav; median (self kappa / NAV kappa - 1): -4.84 bp; median closing premium to the self fair 0.42 bp, to the NAV fair 5.18 bp.
- **VUSA**: 21 days (2026-09-09 .. 2026-10-07); issuer NAV on 4 days from VUSA_page_nav; median (self kappa / NAV kappa - 1): -4.94 bp; median closing premium to the self fair 0.23 bp, to the NAV fair 5.96 bp.
- **SXR8**: 21 days (2026-09-09 .. 2026-10-07); issuer NAV on 21 days from CSPX_nav; median (self kappa / NAV kappa - 1): -4.70 bp; median closing premium to the self fair 0.19 bp, to the NAV fair 5.11 bp.

## Monitor: fault injection (256 injections on real days, detection within 15 min)

| fault | n | detection_rate | median_delay_min |
|---|---|---|---|
| bad_es_price | 32 | 0.91 | 0.00 |
| drawdown | 32 | 1.00 | 0.00 |
| fat_finger | 32 | 1.00 | 0.00 |
| fx_spike | 16 | 0.81 | 0.00 |
| fx_unhedged | 16 | 0.94 | 0.00 |
| hedge_dropped | 32 | 0.72 | 3.00 |
| phantom_fill | 32 | 1.00 | 3.00 |
| stale_feed | 32 | 1.00 | 2.00 |
| wrong_side_hedge | 32 | 0.78 | 3.00 |

Overall detection 91%; alerts on the 80 clean line-days: 21 (0.26 per day; by rule {'DELTA_UNHEDGED': 16, 'FX_EXPOSURE': 5}). Example day CSPX 2026-10-07: bought 4761, sold 4607 shares, max |position| 2.26 clips, max |net delta| 2.40 contracts, day P&L -1217 USD, alerts: none.

## Reference facts read from the data

| line | symbol | currency | tick_inferred | on_grid_share | tick_config | n_prices | median_price |
|---|---|---|---|---|---|---|---|
| CSPX | CSPX.L | USD | 0.0100 | 0.9832 | 0.0100 | 41392 | 828.8700 |
| VUAA | VUAA.L | USD | 0.0200 | 0.9683 | 0.0200 | 38708 | 148.6400 |
| VUSA | VUSA.L | GBP | 0.0025 | 0.9450 | 0.0025 | 42696 | 109.8100 |
| SXR8 | SXR8.DE | EUR | 0.0200 | 1.0000 | 0.0200 | 29780 | 730.2600 |

Session grids (local time, modal first/last print, median prints per day): CSPX: 08:00-16:29, 494; VUAA: 08:00-16:29, 460; VUSA: 08:00-16:29, 508; SXR8: 09:05-17:29, 352.

Issuer files: iShares CSPX_nav: ok 4170 rows; iShares CSPX_keyfacts: ok; Vanguard VUSA_page_nav: ok 4 rows; Vanguard VUAA_page_nav: ok 5 rows.
