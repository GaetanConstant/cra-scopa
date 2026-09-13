"""Mesure de l'activité : jours disponibles, jours saisis, taux d'occupation.

Volontairement limité à ce qui se lit sans discussion. Le §8 de SPEC-CRA.md
prévoit aussi le chiffre d'affaires et un prévisionnel ; ils dépendent du TJM
et de `billable`, dont les définitions restent à trancher, et ne sont pas
nécessaires pour savoir qui a rempli son CRA et à quoi il a passé son temps.

Les fonctions sont pures : elles reçoivent des listes, pas une session.
"""

import logging
from datetime import date, timedelta
from typing import Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)


def working_days_count(start: date, end: date, holidays: Iterable[date]) -> int:
    """Jours du lundi au vendredi de la période, fériés retirés."""
    feries = set(holidays)
    total = 0
    jour = start
    while jour <= end:
        if jour.weekday() < 5 and jour not in feries:
            total += 1
        jour += timedelta(days=1)
    return total


def occupancy(entered: float, available: float) -> float | None:
    """Part des jours disponibles couverte par une saisie.

    `None` quand aucun jour n'était disponible : sur un mois entièrement en
    congé, un taux de 0 % laisserait croire à un oubli de saisie.
    """
    if available <= 0:
        return None
    return round(entered / available, 4)


def summarise_user(
    entered_by_project: Mapping[str, float],
    working_days: int,
    leave_days: float,
) -> dict:
    """Ligne d'activité d'un consultant sur la période."""
    # float() explicite : sum() d'un dictionnaire vide renvoie un entier, et
    # l'export melangeait alors « 0 » et « 22,00 » dans la meme colonne.
    saisi = round(float(sum(entered_by_project.values())), 2)
    disponibles = round(float(working_days) - float(leave_days), 2)
    return {
        "working_days": working_days,
        "leave_days": round(float(leave_days), 2),
        "available_days": disponibles,
        "entered_days": saisi,
        "missing_days": round(max(disponibles - saisi, 0.0), 2),
        "occupancy": occupancy(saisi, disponibles),
    }


def to_csv(lignes: Sequence[Mapping[str, object]], colonnes: Sequence[str]) -> str:
    """Rend un CSV à séparateur point-virgule, lisible par Excel en français.

    Les décimales sont écrites avec une virgule pour la même raison : un
    export qu'il faut retraiter avant de l'ouvrir ne sert personne.
    """
    def cellule(valeur: object) -> str:
        if valeur is None:
            return ""
        if isinstance(valeur, float):
            return f"{valeur:.2f}".replace(".", ",")
        texte = str(valeur)
        return f'"{texte}"' if ";" in texte or '"' in texte else texte

    lignes_csv = [";".join(colonnes)]
    for ligne in lignes:
        lignes_csv.append(";".join(cellule(ligne.get(c)) for c in colonnes))
    return "\n".join(lignes_csv) + "\n"
