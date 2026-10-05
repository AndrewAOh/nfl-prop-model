"""
NFL player identity lookup using nflverse player data.

Canonical player identifier:
    gsis_id

nflverse identifies gsis_id as the primary key for its players dataset.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Optional

import pandas as pd


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

NFLVERSE_PLAYERS_URL = (
    "https://github.com/nflverse/nflverse-data/"
    "releases/download/players/players.csv"
)


# Cache inside the project.
DEFAULT_CACHE_PATH = Path("data/reference/nflverse_players.csv")


# -------------------------------------------------------------------------
# Name normalization
# -------------------------------------------------------------------------

_SUFFIXES = {
    "jr",
    "jr.",
    "sr",
    "sr.",
    "ii",
    "iii",
    "iv",
    "v",
}


def normalize_player_name(name: Optional[str]) -> str:
    """
    Normalize a player name for matching.

    Examples:

        "Rashee Rice"       -> "rashee rice"
        "Rashee  Rice"      -> "rashee rice"
        "RASHEE RICE"       -> "rashee rice"
        "Jameson Williams"  -> "jameson williams"
        "Jameson Williams Jr." -> "jameson williams"
    """

    if name is None:
        return ""

    name = str(name).strip()

    if not name:
        return ""

    # Normalize unicode characters.
    name = unicodedata.normalize("NFKD", name)

    # Remove accents.
    name = "".join(
        char
        for char in name
        if not unicodedata.combining(char)
    )

    # Lowercase.
    name = name.lower()

    # Replace apostrophes with nothing.
    name = name.replace("'", "")

    # Replace hyphens with spaces.
    name = name.replace("-", " ")

    # Remove all other punctuation.
    name = re.sub(r"[^a-z0-9\s]", " ", name)

    # Collapse whitespace.
    name = re.sub(r"\s+", " ", name).strip()

    # Remove suffixes.
    parts = name.split()

    if parts and parts[-1] in _SUFFIXES:
        parts = parts[:-1]

    return " ".join(parts)


# -------------------------------------------------------------------------
# Manual aliases
# -------------------------------------------------------------------------

# These are useful when a sportsbook/API uses a name that differs from
# nflverse's display_name.
#
# Keep this dictionary small. It should only contain genuine naming
# differences that cannot be solved through normalization.

PLAYER_NAME_ALIASES = {
    # Example:
    # "odds api name": "nflverse name",
}


# -------------------------------------------------------------------------
# Player lookup class
# -------------------------------------------------------------------------

class NFLPlayerLookup:
    """
    Resolve player names to nflverse gsis_id values.

    The nflverse dataset is downloaded once and cached locally.
    """

    def __init__(
        self,
        cache_path: Path | str = DEFAULT_CACHE_PATH,
        refresh: bool = False,
    ):
        self.cache_path = Path(cache_path)

        self.players: pd.DataFrame = pd.DataFrame()

        self.name_to_gsis: dict[str, str] = {}

        self._load_players(refresh=refresh)

        self.unresolved_names = set()

        self.mult_matched_names = set()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_players(self, refresh: bool = False) -> None:
        """
        Load nflverse players.

        Uses the local cache when available.
        """

        if (
            self.cache_path.exists()
            and not refresh
        ):
            logger.info(
                "Loading nflverse players from cache: %s",
                self.cache_path,
            )

            players = pd.read_csv(
                self.cache_path,
                dtype=str,
            )

        else:
            logger.info(
                "Downloading nflverse players from %s",
                NFLVERSE_PLAYERS_URL,
            )

            players = pd.read_csv(
                NFLVERSE_PLAYERS_URL,
                dtype=str,
            )

            self.cache_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            players.to_csv(
                self.cache_path,
                index=False,
            )

            logger.info(
                "Saved nflverse player cache: %s",
                self.cache_path,
            )

        # --------------------------------------------------------------
        # Validate required columns
        # --------------------------------------------------------------

        required_columns = {
            "gsis_id",
            "display_name",
        }

        missing = required_columns - set(
            players.columns
        )

        if missing:
            raise ValueError(
                "nflverse player dataset is missing "
                f"required columns: {missing}"
            )

        # --------------------------------------------------------------
        # Remove players without a canonical ID
        # --------------------------------------------------------------

        players = players[
            players["gsis_id"].notna()
            & (players["gsis_id"].str.strip() != "")
        ].copy()

        # --------------------------------------------------------------
        # Build normalized name
        # --------------------------------------------------------------

        players["normalized_name"] = (
            players["display_name"]
            .apply(normalize_player_name)
        )

        # Remove empty names.
        players = players[
            players["normalized_name"] != ""
        ].copy()

        self.players = players

        self._build_name_lookup()

        logger.info(
            "Loaded %d nflverse players",
            len(self.players),
        )

    # ------------------------------------------------------------------
    # Build lookup dictionary
    # ------------------------------------------------------------------

    def _build_name_lookup(self) -> None:
        """
        Build:

            normalized name -> gsis_id

        Only unique names are automatically mapped.

        This prevents us from accidentally assigning the wrong player
        when two players have the same normalized name.
        """

        grouped = (
            self.players
            .groupby("normalized_name")["gsis_id"]
            .agg(lambda values: set(values.dropna()))
        )

        self.name_to_gsis = {}

        for normalized_name, gsis_ids in grouped.items():

            # Only automatically map unambiguous names.
            if len(gsis_ids) == 1:
                self.name_to_gsis[
                    normalized_name
                ] = next(iter(gsis_ids))

    # ------------------------------------------------------------------
    # Resolve a player
    # ------------------------------------------------------------------

    def lookup(
        self,
        player_name: Optional[str],
        home_abbr=None,
        away_abbr=None,
    ) -> Optional[str]:
        """
        Resolve a player name to gsis_id.

        Returns:
            gsis_id string
            None if no unambiguous match exists
        """

        if not player_name:
            return None

        normalized_name = normalize_player_name(
            player_name
        )

        if not normalized_name:
            return None

        # --------------------------------------------------------------
        # Check manual aliases first
        # --------------------------------------------------------------

        alias = PLAYER_NAME_ALIASES.get(
            normalized_name
        )

        if alias:
            normalized_name = normalize_player_name(
                alias
            )

        # --------------------------------------------------------------
        # Exact normalized match
        # --------------------------------------------------------------

        gsis_id = self.name_to_gsis.get(
            normalized_name
        )

        if gsis_id:
            return gsis_id

        # --------------------------------------------------------------
        # Multiple possible matches
        # --------------------------------------------------------------
        matches = self.players[
            (self.players["normalized_name"] == normalized_name)
            & (self.players["status"] == "ACT")
            & (self.players['position'].isin(['QB', 'RB', 'FB', 'WR', 'TE']))
        ]

        event_teams = {
            home_abbr,
            away_abbr,
        }

        team_matches = matches[
            matches["latest_team"].isin(event_teams)
        ]

        if len(team_matches) == 1:
            # logger.log(f"Player ({normalized_name} matched with Team {team_matches.iloc[0]['team_abbr']})")
            self.mult_matched_names.add(
                (normalized_name, team_matches.iloc[0]["latest_team"])
            )
            return team_matches.iloc[0]["gsis_id"]

        # --------------------------------------------------------------
        # Unresolved
        # --------------------------------------------------------------

        if normalized_name not in self.unresolved_names:
            self.unresolved_names.add(normalized_name)
            return None

        return None

    # ------------------------------------------------------------------
    # Resolve with information
    # ------------------------------------------------------------------

    def lookup_details(
        self,
        player_name: Optional[str],
    ) -> Optional[dict]:
        """
        Return the full nflverse player record for a name.
        """

        gsis_id = self.lookup(player_name)

        if gsis_id is None:
            return None

        matches = self.players[
            self.players["gsis_id"] == gsis_id
        ]

        if matches.empty:
            return None

        return matches.iloc[0].to_dict()


    def log_unresolved_names(self):
        if not self.unresolved_names:
            logger.info("All NFL player names were resolved successfully.")
            return

        logger.warning(
            "Could not resolve %d unique NFL player names:",
            len(self.unresolved_names),
        )

        for name in sorted(self.unresolved_names):
            logger.warning("  - %s", name)

        logger.info("Possible NFL Player mismatches")
        for name in sorted(self.unresolved_names):
            normalized = normalize_player_name(name)
            matches = self.players[
                self.players['normalized_name'] == normalized
            ]

            print(f'\n{name}')
            print(f'Normalized: {normalized}')
            print(f'Matches: {len(matches)}')

            if len(matches):
                print(
                    matches[
                        ['display_name', 'gsis_id']
                    ].to_string(index=False)
                )

    def log_mult_matched_names(self):
        if not self.mult_matched_names:
            return

        logger.info("Players resolved using team disambiguation:")
        for name, team in sorted(self.mult_matched_names):
            logger.info(
                "Player (%s) matched with Team %s",
                name,
                team,
            )