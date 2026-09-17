from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nfl_props.config.settings import settings
for path in [settings.raw_root, settings.interim_root, settings.processed_root, settings.db_path.parent]:
    path.mkdir(parents=True, exist_ok=True)
print(f"Initialized directories under {settings.project_root}")
print(f"Database: {settings.db_path}")
