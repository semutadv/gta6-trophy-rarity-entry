[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/semutadv/gta6-trophy-rarity-entry/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/semutadv/gta6-trophy-rarity-entry/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

# GTA VI Trophy Rarity Forecaster

Entry for the make.fun contest **gta6-trophy-rarity-forecast-01**
("Forecast how many GTA VI players earn each trophy in week one",
harness program/v1).

`main.py` (Python 3, standard library only, no network, deterministic)
reads each forecast case in the input directory — a history of Exophase
rarity reads for the 55 official GTA VI trophies — and writes quantile
forecasts (levels 0.05, 0.25, 0.5, 0.75, 0.95) of every trophy's earn
rate at the case's target time.

## How it forecasts

An earn rate is a ratio, and its two parts behave differently during
launch week. The denominator — the players Exophase tracks — grows in
steps each time Exophase refreshes, and every step dilutes every rate.
The numerator — the players who have earned a trophy — only ever
accumulates, at a pace set by how deep into the game the trophy sits.
Forecasting the printed rate directly mixes the two motions together,
so the program separates them:

- **Pool view.** `ln(players_tracked)` is fitted against
  `ln(1 + hours since the first read)` — a clock on which launch-week
  growth decelerates on its own — and extrapolated to the target with
  a bounded increment.
- **Earners view.** Each trophy's earner count (rate × players) gets
  the same kind of fit, with its slope clipped to be non-negative,
  shrunk toward the pool-wide earners slope (hard for trophies earned
  by a handful of players, whose printed rates are mostly rounding),
  floored at the last observed count, and capped at the forecast pool.
- **Rate view.** The rate's own logit is fitted on the same clock,
  slope shrunk the same way, and an upward move is damped by the
  headroom left below 100%, so a fast riser is not extrapolated
  through the ceiling.

The median is the average of the earners view and the rate view on the
logit scale; the earners view is down-weighted when it saturates
against the pool cap. The spread around the median widens with the
horizon, with the size of the trend being extrapolated, and with the
sampling noise of low-count trophies. Repeated reads of an unchanged
page are collapsed to a single state first, so a stale page is not
weighted by how often it was polled.

## Running it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Every `*.in` file in the input directory produces one `<id>.out` in
the output directory. The program is deterministic: two runs on the
same case produce byte-identical forecasts.
