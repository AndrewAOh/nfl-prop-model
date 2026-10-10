from pathlib import Path
import pandas as pd


DATA_DIR = Path("data/raw/nflverse")
SEASON = 2025


def load_parquet(path: Path) -> pd.DataFrame:
    """Load a parquet file and provide a useful error message."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    return pd.read_parquet(path)


def main():
    participation_path = DATA_DIR / f"participation_{SEASON}.parquet"

    participation = load_parquet(participation_path)

    # Datasets that may contain overlapping information.
    dataset_names = [
        "pbp",
        "player_stats",
        "snap_counts",
        "rosters",
        "rosters_weekly",
        "nextgen_stats",
        "pfr_advstats",
        "schedules",
    ]

    datasets = {}

    for name in dataset_names:
        path = DATA_DIR / f"{name}_{SEASON}.parquet"

        if not path.exists():
            print(f"Skipping missing dataset: {path}")
            continue

        try:
            datasets[name] = load_parquet(path)
        except Exception as exc:
            print(f"Could not load {name}: {exc}")

    participation_columns = set(participation.columns)

    all_other_columns = set()

    for name, df in datasets.items():
        all_other_columns.update(df.columns)

    unique_columns = sorted(
        participation_columns - all_other_columns
    )

    overlapping_columns = sorted(
        participation_columns & all_other_columns
    )

    print("\n" + "=" * 80)
    print(f"PARTICIPATION SCHEMA COMPARISON: {SEASON}")
    print("=" * 80)

    print(f"\nParticipation rows: {len(participation):,}")
    print(f"Participation columns: {len(participation.columns)}")
    print(f"Other datasets loaded: {list(datasets.keys())}")

    print("\n" + "-" * 80)
    print("COLUMNS UNIQUE TO PARTICIPATION")
    print("-" * 80)

    for column in unique_columns:
        series = participation[column]

        print(
            f"{column:35} "
            f"dtype={str(series.dtype):15} "
            f"non_null={series.notna().sum():,}"
        )

    print("\n" + "-" * 80)
    print("COLUMNS OVERLAPPING WITH OTHER DATASETS")
    print("-" * 80)

    for column in overlapping_columns:
        print(column)

    print("\n" + "-" * 80)
    print("COLUMNS BY DATASET")
    print("-" * 80)

    for name, df in datasets.items():
        overlap = sorted(participation_columns & set(df.columns))

        print(f"\n{name}:")
        print(f"  Columns: {len(df.columns)}")
        print(f"  Overlapping participation columns: {len(overlap)}")

        if overlap:
            print("  " + ", ".join(overlap))

    # Save a machine-readable report.
    report_rows = []

    for column in sorted(participation_columns):
        present_in = []

        for name, df in datasets.items():
            if column in df.columns:
                present_in.append(name)

        report_rows.append(
            {
                "column": column,
                "participation_dtype": str(
                    participation[column].dtype
                ),
                "participation_non_null": int(
                    participation[column].notna().sum()
                ),
                "present_in_other_datasets": ", ".join(present_in),
                "unique_to_participation": len(present_in) == 0,
            }
        )

    report = pd.DataFrame(report_rows)

    output_path = Path("data/schema_participation_comparison.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False)

    print(f"\nSchema report written to: {output_path}")


if __name__ == "__main__":
    main()