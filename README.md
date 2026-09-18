# NFL Player Prop Model — Free Local MVP

This is a Python-first scaffold for a reproducible NFL player prop projection system.
The initial focus is receiving yards and receptions, with modular ingestion, feature,
modeling, simulation, pricing, and evaluation components.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

## Run the demo

```bash
python scripts/demo_projection.py
```

## Download public nflverse data

```bash
python scripts/download_nflverse.py --season 2024 --dataset player_stats
python scripts/download_nflverse.py --season 2024 --dataset schedules
python scripts/download_nflverse.py --season 2024 --dataset pbp
```

## Run tests

```bash
pytest
```

## Current status

This is an initial implementation scaffold, not a production-ready betting model.
The simple opportunity and efficiency models are placeholders. Before using the
outputs for decisions, add point-in-time feature snapshots, robust player/team ID
mapping, game-state models, target allocation across teammates, defensive matchup
features, uncertainty scenarios, and chronological backtesting.

## Data notes

- nflverse is used as the main free historical data source.
- Open-Meteo is provided as a weather integration example.
- Odds API integration is optional and requires a configured key if used.
- Manual odds CSV ingestion is supported so the model can operate without a paid odds API.
