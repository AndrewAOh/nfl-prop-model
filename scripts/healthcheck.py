from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nfl_props.config.settings import settings
print(f"Python project root: {settings.project_root}")
print(f"Data root exists: {settings.data_root.exists()}")
print(f"DB parent exists: {settings.db_path.parent.exists()}")
try:
    import pandas, pyarrow, duckdb, requests, pydantic
    print("Dependencies: OK")
except ImportError as exc:
    print(f"Dependencies: MISSING ({exc})")
    raise SystemExit(1)
