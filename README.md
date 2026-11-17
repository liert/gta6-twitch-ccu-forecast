[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/c/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/liert/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/c/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/liert/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/c/gta6-twitch-ccu-forecast-01)

# GTA VI launch-day Twitch viewers, hour by hour

Entry for [make.fun's gta6-twitch-ccu-forecast-01](https://make.fun/c/gta6-twitch-ccu-forecast-01):
forecast how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day, 2026-11-19 (UTC), from everything recorded up to
the end of the day's first hour — as five quantiles (0.05 / 0.25 / 0.5 /
0.75 / 0.95) per hour, hours 2–24.

## What the program does

`main.py` (Python 3.13, standard library only, no network) reads every
`<id>.in` case in `$MAKEFUN_INPUT_DIR` (else `/input`) and writes one
`<id>.out` forecast per case to `$MAKEFUN_OUTPUT_DIR` (else `/output`).

The forecast is built from the past big launches in the case's
`comparables`, in two parts:

1. **Shape by first-hour size.** Launches whose hour-1 print is already
   large (New Zealand, central Europe and the UK unlocked by 00:00 UTC)
   stay roughly flat, then rise into the evening as the Americas wake and
   play. Launches whose hour-1 print is tiny (their real unlock is still
   hours away in UTC terms) explode by two to three orders of magnitude
   once they unlock. The log-ratio curve `log(v_h / v_1)` is strongly
   related to `log(p1)`, so each hour's quantiles are kernel-weighted
   empirical quantiles of the comparables' log-ratios, with a Gaussian
   kernel on `log(p1)` (bandwidth 1.1) — a case borrows its shape mostly
   from launches that looked the same size after one hour.
2. **Absolute levels for tiny prints.** A tiny hour-1 print says almost
   nothing about the eventual level: still-locked launches peak in a much
   narrower absolute band than their hour-1 prints span. So the forecast
   blends the ratio-based quantiles with quantiles of the comparables'
   *absolute* hourly levels. The blend weight on the ratio side grows
   smoothly with `p1` (logistic in `log(p1)`, centred at 6,000 viewers,
   from 0.40 to 0.85).

The game's own pre-release history curve (months of points, not a launch
curve) is excluded by a span check — a genuine comparable covers roughly
17 days around its release day. With no usable comparable at all, the
program falls back to persistence with a widening log spread. Output is
clamped to `(0, 1e9]`, non-decreasing, rounded to 2 decimals, and fully
deterministic (no randomness), so two runs are byte-identical.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Local validation (practice cases p00–p03)

- Format: all 4 outputs valid — 23 rows, hours 2–24, monotone quantiles
  in `(0, 1e9]`, files ~1.5 KB (limit 65,536).
- Determinism: two runs produce byte-identical outputs (same sha256).
- Timing: ~0.5 s for all 4 cases together (limit 8 s per case).
- Leave-one-out over the 37 usable comparable launch curves (each curve
  forecast from its hour-1 print and the other curves, scored by log-scale
  pinball loss): **loss 0.385, typical miss 79.7%, 90% coverage 0.897**,
  versus the house persistence baseline under the same protocol:
  loss 0.930, typical miss 213.3%, coverage 0.624. On already-unlocked
  launches (hour-1 print ≥ 5,000) the loss is 0.269 vs the baseline's
  0.360.

## License

MIT — see [LICENSE](LICENSE).
