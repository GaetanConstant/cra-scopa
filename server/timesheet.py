"""Règles de saisie du CRA : capacité journalière, trous, périodes.

Isolé de l'API comme le décompte des congés, et pour la même raison : ce
sont les règles que l'équipe conteste quand un chiffre surprend, elles
doivent être lisibles et testables sans monter une base.
"""

import calendar
import logging
from datetime import date, timedelta
from typing import Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Une journée pleine. La saisie se fait par demi-journées, donc en pas de 0,5.
FULL_DAY = 1.0
STEP = 0.5


class TimesheetError(ValueError):
    """Saisie invalide. Le message est destiné à l'utilisateur."""


def parse_period(period: str) -> tuple[int, int]:
    """« 2026-09 » vers (2026, 9)."""
    try:
        annee, mois = period.split("-")
        annee, mois = int(annee), int(mois)
        if not 1 <= mois <= 12:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise TimesheetError("Période attendue au format AAAA-MM") from exc
    return annee, mois


def period_bounds(period: str) -> tuple[date, date]:
    annee, mois = parse_period(period)
    dernier = calendar.monthrange(annee, mois)[1]
    return date(annee, mois, 1), date(annee, mois, dernier)


def period_of(jour: date) -> str:
    return f"{jour.year:04d}-{jour.month:02d}"


def daily_totals(entries: Iterable[tuple[date, float]]) -> dict[date, float]:
    """Somme des quantités saisies par date."""
    totaux: dict[date, float] = {}
    for jour, quantite in entries:
        totaux[jour] = totaux.get(jour, 0.0) + quantite
    return totaux


def check_quantities(entries: Sequence[tuple[date, float]]) -> None:
    """Chaque ligne vaut un multiple de 0,5, strictement positif."""
    for jour, quantite in entries:
        if quantite <= 0:
            raise TimesheetError(f"Le {jour} porte une quantité nulle ou négative")
        if round(quantite / STEP) * STEP != quantite:
            raise TimesheetError(
                f"Le {jour} porte {quantite} : la saisie se fait par demi-journées"
            )


def overloaded_days(
    entries: Sequence[tuple[date, float]],
    leave_load: Mapping[date, float],
) -> dict[date, float]:
    """Journées dont le total, absences comprises, dépasse 1,0.

    Ce n'est pas une erreur : plusieurs missions se cumulent légitimement sur
    une même journée chez SCOPA. On le remonte pour que l'écran puisse le
    signaler, et parce que ces journées font monter le taux d'occupation
    au-dessus de 100 % — mieux vaut savoir d'où ça vient.
    """
    totaux = daily_totals(entries)
    charges = {}
    for jour in set(totaux) | set(leave_load):
        total = round(totaux.get(jour, 0.0) + leave_load.get(jour, 0.0), 2)
        if total > FULL_DAY:
            charges[jour] = total
    return dict(sorted(charges.items()))


def missing_working_days(
    period: str,
    entries: Sequence[tuple[date, float]],
    leave_load: Mapping[date, float],
    holidays: Iterable[date],
) -> list[date]:
    """Jours ouvrés du mois ni saisis ni couverts par une absence.

    Ce sont les trous qui empêchent de clôturer : un mois incomplet fausse
    le taux d'occupation sans que personne s'en aperçoive.
    """
    premier, dernier = period_bounds(period)
    feries = set(holidays)
    totaux = daily_totals(entries)

    trous = []
    jour = premier
    while jour <= dernier:
        ouvre = jour.weekday() < 5 and jour not in feries
        if ouvre and not totaux.get(jour) and not leave_load.get(jour):
            trous.append(jour)
        jour += timedelta(days=1)
    return trous
