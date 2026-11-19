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
