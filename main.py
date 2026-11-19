"""GTA VI trophy rarity forecaster (make.fun gta6-trophy-rarity-forecast-01).

Reads every *.in case in the input directory and writes one <id>.out
forecast per case: five quantiles of each trophy's Exophase earn rate
(percent of tracked players) at the case's target time.

Model, in brief.  A rate is earners divided by tracked players, and the
two parts move differently over launch week: the tracked pool grows in
steps (Exophase refreshes) and dilutes every rate, while earners only
accumulate as players progress.  So the forecaster works with three
views of each trophy's history, all against x = ln(1 + hours since the
first read), a clock on which launch-week growth naturally decelerates:

  * a players view: a power-law fit of ln(players_tracked), extrapolated
    with a damped increment, giving the pool size at the target;
  * an earners view: per trophy, a power-law fit of ln(earners) with the
    slope clipped to be non-negative (earners do not un-earn) and shrunk
    toward the pool-wide earners slope, extrapolated damped, floored at
    the last observed earner count and capped at the forecast pool;
  * a rate view: a fit of the rate's logit against x, slope shrunk
    toward the pooled logit slope, with upward moves damped by the
    headroom left below 100%.

The median is the average of the earners view and the rate view on the
logit scale (the earners view is down-weighted when it saturates
against the pool cap, where the pool forecast dominates it).  The
spread around the median grows with the horizon, with the size of the
trend being extrapolated, and with the sampling noise of trophies only
a handful of players have earned.  Everything is deterministic:
no randomness, no network, standard library only.
"""

import glob
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

DEFAULT_LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
RATE_LO = 0.01
RATE_HI = 99.99

# Damping constants for trend extrapolation: an increment dx on the
# log-time axis is applied as dx * K / (dx + K), so a trend can move the
# forecast by only a bounded amount no matter how far out the target is.
K_LOGIT = 1.1
K_EARN = 1.35
K_POOL = 2.2


def clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


def logit(rate_percent):
    p = clamp(rate_percent, RATE_LO, RATE_HI) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(lam):
    return 100.0 / (1.0 + math.exp(-clamp(lam, -30.0, 30.0)))


def parse_time(text):
    """Parse an ISO 8601 timestamp; return an aware datetime or None."""
    if not text or not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def ols(xs, ys):
    """Least squares line; returns (intercept, slope) or None."""
    n = len(xs)
    if n == 0:
        return None
    if n == 1 or max(xs) == min(xs):
        return (ys[-1], 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    return (my - slope * mx, slope)


def fit_blend(xs, ys):
    """Fit a line and report (level at the last x, slope).

    The slope leans on the recent part of the series (the last 40% of
    the x range) blended with the full-series slope, because launch-week
    series bend: earners accelerate as the player base ages, and a
    whole-history average understates the current pace.  The level is
    then refit through all points with that blended slope.
    """
    full = ols(xs, ys)
    if full is None:
        return None
    x_last = xs[-1]
    span = x_last - xs[0]
    if len(xs) >= 4 and span > 0:
        cut = x_last - 0.4 * span
        rx = [x for x in xs if x >= cut]
        ry = [y for x, y in zip(xs, ys) if x >= cut]
        recent = ols(rx, ry)
        if recent is not None:
            slope = 0.6 * recent[1] + 0.4 * full[1]
            intercept = sum(y - slope * x for x, y in zip(xs, ys)) / len(xs)
            return (intercept + slope * x_last, slope)
    return (full[0] + full[1] * x_last, full[1])


def damp(dx, k):
    """Bounded trend increment: dx applied through dx * k / (dx + k)."""
    return dx * k / (dx + k) if dx > 0 else 0.0


def prepare_states(history):
    """Collapse the read history to distinct page states.

    Between Exophase refreshes every read shows the same page, so a run
    of identical reads (same players tracked, same rates) is one piece
    of evidence, not many; keeping duplicates would weight stale pages
    by how often the recorder happened to poll them.  Each state keeps
    the time it was first seen.  Reads whose timestamps do not parse
    are spaced half an hour after the previous state.
    """
    states = []
    last_key = None
    for read in history:
        if not isinstance(read, dict):
            continue
        rates = read.get("rates")
        if not isinstance(rates, list):
            continue
        players = read.get("players_tracked")
        if not isinstance(players, (int, float)) or players <= 0:
            players = None
        key = (players, tuple(rates))
        if key == last_key:
            continue
        last_key = key
        when = parse_time(read.get("at")) or parse_time(read.get("slot"))
        states.append({"at": when, "players": players, "rates": rates})
    fallback = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, state in enumerate(states):
        if state["at"] is None:
            base = states[i - 1]["at"] if i > 0 else fallback
            state["at"] = base + timedelta(minutes=30)
    return states


def shrink_weight(earners_last, n_points):
    """How much a trophy's own slope is trusted over the pooled slope.

    A trophy thousands of players have earned has a well-measured
    trajectory; one earned by a handful is mostly rounding noise (rates
    print to 2 decimals), so its slope is shrunk toward the pool's.
    """
    if earners_last <= 0:
        return 0.0
    return (earners_last / (earners_last + 30.0)) * (n_points / (n_points + 3.0))


def pooled_slope(series_list, kind):
    """Earner-weighted average slope across trophies, for shrinkage."""
    num = 0.0
    den = 0.0
    for pts in series_list:
        if len(pts) < 2:
            continue
        if kind == "earn":
            if any(not p[2] for p in pts):
                continue
            ys = [math.log(max(p[1] * p[2] / 100.0, 0.5)) for p in pts]
        else:
            ys = [logit(p[1]) for p in pts]
        fit = fit_blend([p[0] for p in pts], ys)
        if fit is None:
            continue
        last = pts[-1]
        earners = last[1] * (last[2] or 0) / 100.0
        weight = earners + 1.0
        num += weight * fit[1]
        den += weight
    return num / den if den else 0.0


def forecast_case(case):
    """Return one [q05, q25, q50, q75, q95]-style row per trophy."""
    trophies = case.get("trophies") or []
    n_trophies = len(trophies)
    levels = case.get("levels") or DEFAULT_LEVELS
    zs = [NormalDist().inv_cdf(tau) for tau in levels]
    horizon_min = case.get("horizon_minutes") or 0
    days = max(float(horizon_min), 0.0) / 1440.0

    history = case.get("history") or []
    states = prepare_states(history)
    if not states:
        return [[0.05, 0.2, 0.5, 1.2, 3.0] for _ in range(n_trophies)]

    t0 = states[0]["at"]

    def x_of(when):
        hours = max(0.0, (when - t0).total_seconds() / 3600.0)
        return math.log(1.0 + hours)

    xs = [x_of(s["at"]) for s in states]
    target = parse_time(case.get("target"))
    if target is None:
        start = parse_time(case.get("at")) or states[-1]["at"]
        target = start + timedelta(minutes=float(horizon_min or 0))
    x_tgt = x_of(target)
    dx = max(0.0, x_tgt - xs[-1])
    step_logit = damp(dx, K_LOGIT)
    step_earn = damp(dx, K_EARN)
    step_pool = damp(dx, K_POOL)

    # --- players view: where the tracked pool is heading -------------
    pool_pts = [(x, math.log(s["players"])) for x, s in zip(xs, states)
                if s["players"]]
    pool_last = float(states[-1]["players"] or (pool_pts[-1][1] and
                        math.exp(pool_pts[-1][1])) or 0)
    pool_fore = pool_last
    if len(pool_pts) >= 2:
        fit = fit_blend([p[0] for p in pool_pts], [p[1] for p in pool_pts])
        if fit is not None:
            level, slope = fit
            level = max(level, math.log(pool_last))
            pool_fore = math.exp(clamp(level + max(slope, 0.0) * step_pool,
                                       -30.0, 30.0))
    if pool_last:
        # The pool does not shrink, and no fit gets to claim it grows
        # by more than 25x over one forecast window.
        pool_fore = clamp(pool_fore, pool_last * 0.98, pool_last * 25.0)

    # --- per-trophy series -------------------------------------------
    series = []
    for i in range(n_trophies):
        pts = []
        for x, s in zip(xs, states):
            rate = s["rates"][i] if i < len(s["rates"]) else None
            if isinstance(rate, (int, float)):
                pts.append((x, float(rate), s["players"]))
        series.append(pts)

    pool_earn_slope = max(pooled_slope(series, "earn"), 0.0)
    pool_rate_slope = pooled_slope(series, "rate")

    # A trophy with no observed rate borrows the typical level of the
    # trophies that were observed, with a wide spread.
    observed_last = sorted(p[-1][1] for p in series if p)
    typical = observed_last[len(observed_last) // 2] if observed_last else 0.25

    rows = []
    for pts in series:
        if not pts:
            mu = logit(typical)
            rows.append(quantiles(mu, 1.2, levels, zs))
            continue
        _, rate_last, pool_at_last = pts[-1]
        earn_last = rate_last * pool_at_last / 100.0 if pool_at_last else 0.0
        w = shrink_weight(earn_last, len(pts))

        # Earners view: extrapolate the earner count, divide by the
        # forecast pool.  Earners cannot shrink, so the slope is
        # clipped at zero and the count floored at its last value.
        rate_earn = None
        if pool_fore and pool_at_last and all(p[2] for p in pts):
            ys = [math.log(max(p[1] * p[2] / 100.0, 0.5)) for p in pts]
            fit = fit_blend([p[0] for p in pts], ys)
            if fit is not None:
                level, slope = fit
                slope = clamp(w * clamp(slope, 0.0, 3.0)
                              + (1.0 - w) * pool_earn_slope, 0.0, 3.0)
                ln_earn = max(level, math.log(max(earn_last, 0.5)))
                earn_fore = min(math.exp(clamp(ln_earn + slope * step_earn,
                                               -30.0, 30.0)), pool_fore)
                rate_earn = clamp(100.0 * earn_fore / pool_fore,
                                  RATE_LO, RATE_HI)

        # Rate view: logit trend, shrunk to the pooled slope; an upward
        # move is damped by the headroom left below 100%.
        fit = fit_blend([p[0] for p in pts], [logit(p[1]) for p in pts])
        if fit is not None:
            level, slope_raw = fit
            slope = clamp(w * clamp(slope_raw, -3.0, 3.0)
                          + (1.0 - w) * pool_rate_slope, -3.0, 3.0)
        else:
            level, slope = logit(rate_last), 0.0
        move = slope * step_logit
        if move > 0:
            move *= 1.0 - clamp(rate_last, 0.0, 100.0) / 100.0
        mu_rate = level + move

        if rate_earn is not None:
            # When the earners view saturates against the pool cap its
            # value is mostly the pool forecast talking; trust it less.
            w_earn = 0.3 if rate_earn >= 95.0 else 0.5
            mu = w_earn * logit(rate_earn) + (1.0 - w_earn) * mu_rate
        else:
            mu = mu_rate

        sigma = math.sqrt(
            (0.62 * math.sqrt(days)) ** 2
            + 0.09
            + min(0.9, 1.0 / math.sqrt(max(earn_last, 1.0))) ** 2
            + (0.3 * abs(slope) * step_logit) ** 2
        )
        rows.append(quantiles(mu, clamp(sigma, 0.4, 2.4), levels, zs))
    return rows


def quantiles(mu, sigma, levels, zs):
    """Quantile row on the percent scale, ordered and in range."""
    row = [clamp(round(inv_logit(mu + z * sigma), 4), RATE_LO, RATE_HI)
           for z in zs]
    for k in range(1, len(row)):
        row[k] = max(row[k], row[k - 1])
    return row


def fallback_rows(case):
    """Persistence rows from the last observed rates, if anything in
    the main forecast failed unexpectedly.  Always schema-valid."""
    trophies = case.get("trophies") or []
    levels = case.get("levels") or DEFAULT_LEVELS
    zs = [NormalDist().inv_cdf(tau) for tau in levels]
    days = max(float(case.get("horizon_minutes") or 0), 0.0) / 1440.0
    sigma = clamp(0.5 * math.sqrt(days), 0.3, 2.0)
    last_rates = [None] * len(trophies)
    for read in reversed(case.get("history") or []):
        rates = read.get("rates") if isinstance(read, dict) else None
        if not isinstance(rates, list):
            continue
        for i in range(len(trophies)):
            if last_rates[i] is None and i < len(rates) \
                    and isinstance(rates[i], (int, float)):
                last_rates[i] = float(rates[i])
        if all(v is not None for v in last_rates):
            break
    rows = []
    for rate in last_rates:
        rows.append(quantiles(logit(rate if rate is not None else 0.25),
                              sigma, levels, zs))
    return rows


def run_case(path, out_dir):
    with open(path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    trophies = case.get("trophies") or []
    try:
        rows = forecast_case(case)
        if len(rows) != len(trophies):
            raise ValueError("row count mismatch")
    except Exception:
        rows = fallback_rows(case)
    out_rows = []
    for trophy, row in zip(trophies, rows):
        tid = trophy.get("id") if isinstance(trophy, dict) else None
        out_rows.append({"id": tid, "q": row})
    payload = json.dumps({"trophies": out_rows}, separators=(",", ":"))
    stem = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, stem + ".out")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(payload)


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(in_dir, "*.in"))):
        run_case(path, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
