# NFL Player Prop Model

Free-first, point-in-time NFL player prop modeling system using Python, Parquet, and DuckDB.

## Principles
- Raw downloads are immutable and never committed to Git.
- Every source is isolated behind an adapter.
- Source failures are logged and do not automatically stop unrelated ingestion.
- Features must have an availability timestamp and be usable before kickoff.
- Proprietary or restricted sources are optional; the MVP can run without API keys.

## Setup (macOS)
```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python scripts/init_project.py
python scripts/healthcheck.py
```

## Run free-source foundation
```bash
python scripts/ingest_foundation.py --season 2025
```

The initial implementation downloads nflverse data and records optional-source skips. Advanced sources are deliberately disabled unless a public endpoint/format is configured and validated.
