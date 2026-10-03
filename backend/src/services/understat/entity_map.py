"""Canonical entity map: Understat team names → SabiScore PostgreSQL slugs.

The mapping is intentionally explicit rather than fuzzy to make every
resolution traceable and auditable.  A name that is absent from the map
raises ``UnmappedEntityError`` — the caller catches that per-row, logs it,
and moves on to the next match rather than aborting the whole batch.
"""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical slug map
# ---------------------------------------------------------------------------
# Key   — the string exactly as it appears in Understat JSON (team name field)
# Value — the canonical slug used in SabiScore's `teams.id` / rolling-xG keys
# ---------------------------------------------------------------------------
UNDERSTAT_ENTITY_MAP: Final[dict[str, str]] = {
    # Italy – Serie A
    "Inter": "inter_milan",
    "AC Milan": "ac_milan",
    "Juventus": "juventus",
    "Napoli": "napoli",
    "Roma": "as_roma",
    "Atalanta": "atalanta",
    "Lazio": "lazio",
    "Fiorentina": "fiorentina",
    "Bologna": "bologna",
    "Torino": "torino",
    "Monza": "monza",
    "Genoa": "genoa",
    "Cagliari": "cagliari",
    "Udinese": "udinese",
    "Sassuolo": "sassuolo",
    "Empoli": "empoli",
    "Verona": "hellas_verona",
    "Lecce": "lecce",
    "Frosinone": "frosinone",
    "Salernitana": "salernitana",
    "Venezia": "venezia",
    "Parma": "parma",
    "Como": "como",
    # England – Premier League
    "Manchester City": "manchester_city",
    "Arsenal": "arsenal",
    "Liverpool": "liverpool",
    "Chelsea": "chelsea",
    "Tottenham": "tottenham_hotspur",
    "Spurs": "tottenham_hotspur",
    "Manchester United": "manchester_united",
    "Man Utd": "manchester_united",
    "Newcastle United": "newcastle_united",
    "Aston Villa": "aston_villa",
    "Brighton": "brighton",
    "West Ham": "west_ham_united",
    "Wolves": "wolverhampton_wanderers",
    "Wolverhampton Wanderers": "wolverhampton_wanderers",
    "Crystal Palace": "crystal_palace",
    "Everton": "everton",
    "Fulham": "fulham",
    "Brentford": "brentford",
    "Nottingham Forest": "nottingham_forest",
    "Bournemouth": "bournemouth",
    "Leicester": "leicester_city",
    "Southampton": "southampton",
    "Ipswich": "ipswich_town",
    # Spain – La Liga
    "Real Madrid": "real_madrid",
    "Barcelona": "barcelona",
    "Atletico Madrid": "atletico_madrid",
    "Sevilla": "sevilla",
    "Real Sociedad": "real_sociedad",
    "Villarreal": "villarreal",
    "Athletic Club": "athletic_bilbao",
    "Valencia": "valencia",
    "Betis": "real_betis",
    "Real Betis": "real_betis",
    "Osasuna": "osasuna",
    "Girona": "girona",
    "Las Palmas": "las_palmas",
    "Mallorca": "rcd_mallorca",
    "Celta Vigo": "celta_vigo",
    "Getafe": "getafe",
    "Rayo Vallecano": "rayo_vallecano",
    "Cadiz": "cadiz",
    "Alaves": "deportivo_alaves",
    "Leganes": "cd_leganes",
    "Valladolid": "real_valladolid",
    # Germany – Bundesliga
    "Bayern Munich": "bayern_munich",
    "Borussia Dortmund": "borussia_dortmund",
    "RB Leipzig": "rb_leipzig",
    "Leverkusen": "bayer_leverkusen",
    "Bayer Leverkusen": "bayer_leverkusen",
    "Eintracht Frankfurt": "eintracht_frankfurt",
    "Wolfsburg": "vfl_wolfsburg",
    "Freiburg": "sc_freiburg",
    "Hoffenheim": "tsg_hoffenheim",
    "Borussia M'gladbach": "borussia_monchengladbach",
    "Mainz": "fsv_mainz_05",
    "Augsburg": "fc_augsburg",
    "Stuttgart": "vfb_stuttgart",
    "Union Berlin": "union_berlin",
    "Heidenheim": "fc_heidenheim",
    "St. Pauli": "fc_st_pauli",
    "Werder Bremen": "werder_bremen",
    "Bochum": "vfl_bochum",
    # France – Ligue 1
    "PSG": "paris_saint_germain",
    "Paris Saint Germain": "paris_saint_germain",
    "Paris Saint-Germain": "paris_saint_germain",
    "Marseille": "olympique_marseille",
    "Lyon": "olympique_lyonnais",
    "Monaco": "as_monaco",
    "Lille": "losc_lille",
    "Lens": "rc_lens",
    "Nice": "ogc_nice",
    "Rennes": "stade_rennais",
    "Strasbourg": "rc_strasbourg",
    "Toulouse": "toulouse_fc",
    "Nantes": "fc_nantes",
    "Montpellier": "montpellier_hsc",
    "Reims": "stade_de_reims",
    "Le Havre": "le_havre_ac",
    "Brest": "stade_brestois",
    "Metz": "fc_metz",
    "Clermont": "clermont_foot",
    "Lorient": "fc_lorient",
    "Saint-Etienne": "as_saint_etienne",
    "Auxerre": "aaj_auxerre",
    "Angers": "angers_sco",
    # Champions League common variants
    "Porto": "fc_porto",
    "Benfica": "sl_benfica",
    "Sporting CP": "sporting_cp",
    "Ajax": "afc_ajax",
    "PSV": "psv_eindhoven",
    "Feyenoord": "feyenoord",
    "Celtic": "celtic",
    "Rangers": "rangers",
    "Red Bull Salzburg": "rb_salzburg",
    "Shakhtar": "shakhtar_donetsk",
    "Dinamo Zagreb": "gnk_dinamo_zagreb",
}


class UnmappedEntityError(ValueError):
    """Raised when an Understat team name has no canonical slug mapping."""

    def __init__(self, raw_name: str) -> None:
        self.raw_name = raw_name
        super().__init__(
            f"Understat team name {raw_name!r} has no canonical slug mapping. "
            "Add it to UNDERSTAT_ENTITY_MAP."
        )


def resolve_slug(raw_name: str) -> str:
    """Return the canonical SabiScore slug for an Understat team name.

    Args:
        raw_name: The team name string exactly as extracted from Understat JSON.

    Returns:
        The canonical slug string (e.g. ``"inter_milan"``).

    Raises:
        UnmappedEntityError: If ``raw_name`` is absent from the entity map.
            Callers should catch this, log a critical warning, and continue
            processing the rest of the batch rather than re-raising.
    """
    slug = UNDERSTAT_ENTITY_MAP.get(raw_name)
    if slug is None:
        logger.critical(
            "UNMAPPED_ENTITY raw_name=%r — add to UNDERSTAT_ENTITY_MAP",
            raw_name,
        )
        raise UnmappedEntityError(raw_name)
    return slug


__all__ = [
    "UNDERSTAT_ENTITY_MAP",
    "UnmappedEntityError",
    "resolve_slug",
]
