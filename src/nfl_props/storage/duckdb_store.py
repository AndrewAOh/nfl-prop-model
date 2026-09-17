"""DuckDB metadata store. Large raw/intermediate datasets remain Parquet files."""
from pathlib import Path
import duckdb

class DuckDBStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(db_path))
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                run_id UUID DEFAULT uuid(),
                source VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                rows BIGINT,
                message VARCHAR,
                completed_at TIMESTAMPTZ NOT NULL,
                metadata JSON
            )
        """)

    def record_result(self, result) -> None:
        self.connection.execute(
            "INSERT INTO ingestion_runs (source, dataset, status, rows, message, completed_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [result.source, result.dataset, result.status, result.rows, result.message, result.completed_at, result.metadata],
        )

    def close(self) -> None:
        self.connection.close()
