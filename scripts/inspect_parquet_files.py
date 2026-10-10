from pathlib import Path
import pandas as pd


# Search locations
SEARCH_DIRS = [
    Path("data/raw/nflverse"),
    Path("data/raw/weather"),
]

TARGET_YEAR = "2025"


def format_size(size_bytes: int) -> str:
    """Convert bytes to a readable file size."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size:.2f} PB"


def inspect_parquet(path: Path):
    """Print metadata and columns for one Parquet file."""
    try:
        df = pd.read_parquet(path)

        print("\n" + "=" * 100)
        print(f"FILE: {path}")
        print(f"SIZE: {format_size(path.stat().st_size)}")
        print(f"ROWS: {len(df):,}")
        print(f"COLUMNS: {len(df.columns)}")

        print("\nCOLUMN NAMES:")
        for column in df.columns:
            print(f"  - {column}")

        print("\nDATA TYPES:")
        print(df.dtypes.to_string())

        if "season" in df.columns:
            print(
                "\nSEASONS:",
                sorted(df["season"].dropna().unique().tolist()),
            )

        if "week" in df.columns:
            print(
                "WEEKS:",
                sorted(df["week"].dropna().unique().tolist()),
            )

    except Exception as exc:
        print(f"\nERROR READING {path}: {exc}")


def main():
    parquet_files = []

    for directory in SEARCH_DIRS:
        if not directory.exists():
            print(f"Directory not found: {directory}")
            continue

        # Only include files containing the target year.
        parquet_files.extend(
            path
            for path in directory.rglob("*.parquet")
            if TARGET_YEAR in path.name
        )

    parquet_files = sorted(set(parquet_files))

    if not parquet_files:
        print(f"No {TARGET_YEAR} Parquet files found.")
        return

    print(
        f"Found {len(parquet_files)} Parquet files "
        f"for {TARGET_YEAR}."
    )

    for path in parquet_files:
        inspect_parquet(path)


if __name__ == "__main__":
    main()