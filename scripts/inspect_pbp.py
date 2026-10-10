import pandas as pd
from pprint import pprint

file_path = "data/raw/nflverse/pbp_2026.parquet"

df = pd.read_parquet(file_path)

# Display settings
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 30)
pd.set_option("display.width", 200)

print("\n" + "=" * 100)
print("FIRST 10 ROWS — PBP 2026")
print("=" * 100)

for i, row in df.head(10).iterrows():
    print(f"\n{'─' * 100}")
    print(f"ROW {i}")
    print(f"{'─' * 100}")

    for column, value in row.items():
        print(f"{column:<35}: {value}")

print("\n" + "=" * 100)