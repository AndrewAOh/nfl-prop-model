"""Lightweight checks used immediately after ingestion."""
from pathlib import Path
import pandas as pd

class ValidationError(ValueError):
    pass

def validate_tabular_file(path: Path, required_columns: list[str] | None = None) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        raise ValidationError(f"Missing or empty file: {path}")
    if path.suffix == ".csv":
        frame = pd.read_csv(path, nrows=5)
    elif path.suffix == ".parquet":
        frame = pd.read_parquet(path).head(5)
    else:
        raise ValidationError(f"Unsupported file type: {path.suffix}")
    required_columns = required_columns or []
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        raise ValidationError(f"Missing columns in {path.name}: {missing}")
    return {"columns": list(frame.columns), "sample_rows": len(frame)}
