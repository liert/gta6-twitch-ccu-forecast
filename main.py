"""Forecast GTA VI's launch-day Twitch viewers, hour by hour.

Reads every ``<id>.in`` case in the input directory (``$MAKEFUN_INPUT_DIR``,
else ``/input``) and writes one ``<id>.out`` forecast per case to the output
directory (``$MAKEFUN_OUTPUT_DIR``, else ``/output``).  Python 3.13,
standard library only, no network, fully deterministic.

Method
------
Each case gives the release day's first-hour viewer print ``p1`` plus the
hourly release-day curves of past big launches (``comparables``).  Two facts
drive the forecast:

1.  *Shape depends on how much of the launch had already happened by hour
    1.*  Launches whose hour-1 print is already large (New Zealand, central
    Europe and the UK already unlocked by 00:00 UTC) stay roughly flat and
    then rise into the evening as the Americas wake and play.  Launches
    whose hour-1 print is tiny (their real unlock is still hours away in
    UTC terms) explode by two to three orders of magnitude once they
    unlock.  The log-ratio curve ``log(v_h / v_1)`` is strongly related to
    ``log(p1)`` (correlation about -0.7 at hour 19 in the kit's
    comparables), so curves are weighted by a Gaussian kernel on
    ``log(p1)`` (bandwidth 1.1 in log units): a case borrows its shape
    mostly from launches that looked the same size after one hour.

2.  *A tiny hour-1 print carries almost no information about the eventual
    level.*  For the still-locked launches the peak audience sits in a
    much narrower absolute band (roughly 1.5e5-5.6e5 viewers) than their
    hour-1 prints do (1.6e2-4.9e3), so the forecast blends the
    ratio-based quantiles with quantiles of the comparables' *absolute*
    hourly levels.  The blend weight on the ratio side grows smoothly
    with ``p1`` (a logistic in ``log(p1)`` centred at 6000 viewers, from
    0.40 up to 0.85): small-print cases lean on absolute levels, large
    ones on their own scale.

Per hour ``h = 2..24`` the five quantiles are the kernel-weighted
empirical quantiles of the log-ratios and of the absolute log-levels,
blended in log space.  The pre-release history curve of the game's own
category (which spans months, not a release window) is excluded by a
span check: a genuine comparable covers roughly 17 days around its
release day.  If no usable comparable exists at all, the forecast falls
back to persistence with a widening log spread.

Quantiles are clamped to ``(0, 1e9]``, forced non-decreasing, and rounded
to 2 decimals.  No randomness anywhere, so two runs are byte-identical.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Gaussian kernel bandwidth on log(hour-1 print).
BANDWIDTH = 1.1
# A genuine comparable spans ~17 days (14 before + 3 after release day);
# anything much longer is a pre-release history curve, not a launch curve.
MAX_CURVE_SPAN_HOURS = 500.0
MIN_CURVE_HOURS = 20
# Blend weight on the ratio-based forecast, as a function of log(p1):
# 0.40 for a tiny hour-1 print, rising to 0.85 for a large one.
BLEND_LOW = 0.40
BLEND_HIGH = 0.85
BLEND_CENTER = math.log(6000.0)
BLEND_SLOPE = 0.7
# Fallback spread (log units per sqrt hour) when no comparables exist.
FALLBACK_SIGMA = 0.30


def _parse_time(text):
    """Parse an ISO-8601 UTC timestamp into epoch seconds (float)."""
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def extract_curves(case):
    """Release-day curves from comparables: list of (p1, {hour: viewers}).

    Sorted by name so the order is deterministic.  A curve is kept only
    when its hourly points cover the release day (hours 1..24 relative to
    its day_start) with at least MIN_CURVE_HOURS points, and when its
    total span looks like a release window rather than a months-long
    pre-release history.
    """
    curves = []
    for comp in sorted(case.get("comparables") or [], key=lambda c: str(c.get("name", ""))):
        try:
            hourly = comp.get("hourly") or []
            if len(hourly) < 100:
                continue
            first = _parse_time(hourly[0].get("from"))
            last = _parse_time(hourly[-1].get("from"))
            if first is None or last is None:
                continue
            if (last - first) / 3600.0 > MAX_CURVE_SPAN_HOURS:
                continue
            day_start = _parse_time(comp.get("day_start"))
            if day_start is None:
                continue
            by_hour = {}
            for row in hourly:
                try:
                    viewers = row.get("viewers")
                    if not viewers or viewers <= 0:
                        continue
                    at = _parse_time(row.get("from"))
                    if at is None:
                        continue
                    h = int((at - day_start) // 3600) + 1
                    if 1 <= h <= 24:
                        by_hour[h] = float(viewers)
                except Exception:
                    continue
            if 1 in by_hour and len(by_hour) >= MIN_CURVE_HOURS:
                curves.append((by_hour[1], by_hour))
        except Exception:
            continue
    return curves


def weighted_quantile(pairs, level):
    """Linearly interpolated weighted quantile of [(value, weight), ...]."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0 or not ordered:
        return ordered[len(ordered) // 2][0] if ordered else 0.0
    target = level * total
    acc = 0.0
    prev_value = ordered[0][0]
    for value, weight in ordered:
        if weight <= 0:
            continue
        acc += weight
        if acc >= target:
            if acc - weight < target:
                frac = (target - (acc - weight)) / weight
                return prev_value + frac * (value - prev_value)
            return value
        prev_value = value
    return ordered[-1][0]


def blend_weight(p1):
    """Weight on the ratio-based forecast (0.40 .. 0.85), smooth in log p1."""
    x = (math.log(max(p1, 1.0)) - BLEND_CENTER) / BLEND_SLOPE
    if x > 30:
        sig = 1.0
    elif x < -30:
        sig = 0.0
    else:
        sig = 1.0 / (1.0 + math.exp(-x))
    return BLEND_LOW + (BLEND_HIGH - BLEND_LOW) * sig


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as int."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if value == int(value) else value


def forecast_hours(p1, curves):
    """Return {hour: [q05, q25, q50, q75, q95]} for hours 2..24."""
    p1 = max(1.0, float(p1))
    log_p1 = math.log(p1)
    alpha = blend_weight(p1)
    out = {}
    for h in range(2, 25):
        ratio_pairs = []
        abs_pairs = []
        for cp1, by_hour in curves:
            if h not in by_hour:
                continue
            w = math.exp(-0.5 * ((math.log(cp1) - log_p1) / BANDWIDTH) ** 2)
            ratio_pairs.append((math.log(by_hour[h] / by_hour[1]), w))
            abs_pairs.append((math.log(by_hour[h]), w))
        if ratio_pairs:
            qs = []
            for level in LEVELS:
                log_ratio = weighted_quantile(ratio_pairs, level)
                log_abs = weighted_quantile(abs_pairs, level)
                log_q = alpha * (log_p1 + log_ratio) + (1.0 - alpha) * log_abs
                qs.append(math.exp(log_q))
        else:
            # No comparable covers this hour: persistence with wide spread.
            qs = [p1 * math.exp(z * FALLBACK_SIGMA * math.sqrt(h - 1)) for z in Z]
        qs = sorted(min(max(q, 1.0), 1e9) for q in qs)
        out[h] = [round2(q) for q in qs]
    return out


def hour1_print(case):
    """Hour-1 print from `known`, falling back to the history's last point."""
    for row in case.get("known") or []:
        if row.get("hour") == 1:
            try:
                v = float(row.get("viewers"))
                if v > 0:
                    return v
            except Exception:
                pass
    history = case.get("history_hourly") or case.get("history") or []
    if history:
        try:
            v = float(history[-1].get("viewers"))
            if v > 0:
                return v
        except Exception:
            pass
    return 1.0


def forecast_case(case):
    p1 = hour1_print(case)
    curves = extract_curves(case)
    hours = forecast_hours(p1, curves)
    rows = []
    for row in sorted(case.get("forecast") or [], key=lambda r: r.get("hour", 0)):
        h = int(row["hour"])
        if 2 <= h <= 24:
            rows.append({"hour": h, "q": hours[h]})
    if len(rows) != 23:  # forecast list missing/malformed: fill hours 2..24
        rows = [{"hour": h, "q": hours[h]} for h in range(2, 25)]
    return {"hours": rows}


def persistence_forecast(p1):
    """Valid fallback forecast: every hour at p1 with a widening spread."""
    p1 = max(1.0, float(p1))
    return {
        "hours": [
            {
                "hour": h,
                "q": [
                    round2(p1 * math.exp(z * FALLBACK_SIGMA * math.sqrt(h - 1)))
                    for z in Z
                ],
            }
            for h in range(2, 25)
        ]
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        forecast = None
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            forecast = forecast_case(case)
        except Exception:
            forecast = None
        if forecast is None:
            # Never crash on a malformed case: emit a valid persistence
            # forecast so the case stays valid.
            forecast = persistence_forecast(1.0)
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
