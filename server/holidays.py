"""Jours fériés français : calcul, sans dépendance ni appel réseau.

Le décompte des congés et tous les indicateurs du pilotage reposent sur les
jours ouvrés, donc sur cette liste. Une dépendance externe ou un appel HTTP
en feraient un point de panne pour une donnée qui, elle, ne bouge jamais :
les règles sont fixes depuis 1886 et Pâques se calcule.
"""

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Fériés à date fixe : (mois, jour, libellé).
FIXED_HOLIDAYS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Jour de l'an"),
    (5, 1, "Fête du Travail"),
    (5, 8, "Victoire 1945"),
    (7, 14, "Fête nationale"),
    (8, 15, "Assomption"),
    (11, 1, "Toussaint"),
    (11, 11, "Armistice 1918"),
    (12, 25, "Noël"),
)

# Fériés mobiles : (décalage en jours depuis Pâques, libellé).
EASTER_OFFSETS: tuple[tuple[int, str], ...] = (
    (1, "Lundi de Pâques"),
    (39, "Ascension"),
    (50, "Lundi de Pentecôte"),
)


def easter_sunday(year: int) -> date:
    """Dimanche de Pâques, algorithme de Butcher (grégorien anonyme).

    Valable de 1583 à 4099. Les noms des variables sont ceux de l'algorithme :
    les renommer rendrait la comparaison avec la référence impossible.
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holidays_for_year(year: int) -> dict[date, str]:
    """Les 11 jours fériés d'une année, dans l'ordre du calendrier."""
    jours = {date(year, mois, jour): libelle for mois, jour, libelle in FIXED_HOLIDAYS}
    paques = easter_sunday(year)
    for decalage, libelle in EASTER_OFFSETS:
        jours[paques + timedelta(days=decalage)] = libelle
    return dict(sorted(jours.items()))


def holidays_for_range(first_year: int, last_year: int) -> dict[date, str]:
    """Fériés de `first_year` à `last_year` inclus."""
    if last_year < first_year:
        raise ValueError("L'année de fin précède l'année de début")
    jours: dict[date, str] = {}
    for annee in range(first_year, last_year + 1):
        jours.update(holidays_for_year(annee))
    return jours
