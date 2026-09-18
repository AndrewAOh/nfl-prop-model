from pathlib import Path
import argparse

from nfl_props.ingestion.nflverse import NflverseClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--dataset", choices=["pbp", "player_stats", "schedules"], default="player_stats")
    args = parser.parse_args()

    client = NflverseClient(Path(args.root) / "data" / "raw")
    if args.dataset == "pbp":
        df = client.load_pbp(args.season)
    elif args.dataset == "schedules":
        df = client.load_schedules(args.season)
    else:
        df = client.load_player_stats(args.season)
    print(f"Downloaded {args.dataset} for {args.season}: {len(df):,} rows")


if __name__ == "__main__":
    main()
