from pathlib import Path
import pandas as pd
from nfl_props.validation.basic import validate_tabular_file

def test_validate_csv(tmp_path: Path):
    path = tmp_path / "sample.csv"
    pd.DataFrame({"game_id": ["x"], "player_id": ["y"]}).to_csv(path, index=False)
    result = validate_tabular_file(path, ["game_id", "player_id"])
    assert "game_id" in result["columns"]
