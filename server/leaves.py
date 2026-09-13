"""Décompte des congés : combien de jours consomme une demande.

Isolé de l'API et de la base pour être testable seul. C'est la règle que
tout le monde vérifie sur son bulletin : une erreur d'un demi-jour ici se
retrouve dans les soldes, dans le CRA et dans le taux d'occupation.
"""

import logging
from datetime import date, timedelta
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

HALVES = ("am", "pm")


class LeaveError(ValueError):
    """Demande incohérente. Le message est destiné à l'utilisateur."""


def working_days(
    start: date, end: date, holidays: Iterable[date]
) -> list[date]:
    """Jours ouvrés de la plage : du lundi au vendredi, fériés retirés."""
    feries = set(holidays)
    jours = []
    courant = start
    while courant <= end:
        if courant.weekday() < 5 and courant not in feries:
            jours.append(courant)
        courant += timedelta(days=1)
    return jours


def count_leave_days(
    start: date,
    end: date,
    holidays: Iterable[date],
    start_half: Optional[str] = None,
    end_half: Optional[str] = None,
) -> float:
    """Jours décomptés par une demande, en pas de 0,5.

    `start_half` est la demi-journée où le congé commence, `end_half` celle
    où il finit. Absents, la demande couvre des journées entières. Une borne
    qui tombe un week-end ou un férié n'a pas de demi-journée à retrancher :
    il n'y avait rien à poser ce jour-là.
    """
    if end < start:
        raise LeaveError("La date de fin précède la date de début")
    for valeur in (start_half, end_half):
        if valeur is not None and valeur not in HALVES:
            raise LeaveError("Demi-journée invalide : attendu « am » ou « pm »")

    debut = start_half or "am"
    fin = end_half or "pm"

    ouvres = working_days(start, end, holidays)
    if not ouvres:
        return 0.0

    if start == end:
        if debut == "pm" and fin == "am":
            raise LeaveError("Un congé ne peut pas finir le matin s'il commence l'après-midi")
        # am→pm = 2 demies, am→am ou pm→pm = 1 demie.
        demies = (HALVES.index(fin) - HALVES.index(debut)) + 1
        return demies / 2

    demies = 2 * len(ouvres)
    # Les bornes ne se retranchent que si elles sont elles-mêmes travaillées.
    if debut == "pm" and start in ouvres:
        demies -= 1
    if fin == "am" and end in ouvres:
        demies -= 1
    return demies / 2


def overlaps(
    start_a: date, end_a: date, start_b: date, end_b: date
) -> bool:
    """Deux plages de dates se chevauchent-elles ?

    Le test porte sur la journée, pas sur la demi-journée : deux demandes le
    même jour sont refusées même si l'une est le matin et l'autre l'après-midi.
    C'est volontairement strict — le cas est rare et la correction se fait à
    la main plutôt que par une règle que personne ne saurait relire.
    """
    return start_a <= end_b and start_b <= end_a


def daily_load(
    start: date,
    end: date,
    holidays: Iterable[date],
    start_half: Optional[str] = None,
    end_half: Optional[str] = None,
) -> dict[date, float]:
    """Charge posée par une absence, jour par jour.

    Le CRA raisonne à la journée : il lui faut savoir qu'un mardi est pris à
    0,5 et non seulement que la demande vaut 3,5 jours au total.
    """
    ouvres = working_days(start, end, holidays)
    if not ouvres:
        return {}

    if start == end:
        return {ouvres[0]: count_leave_days(start, end, holidays, start_half, end_half)}

    debut = start_half or "am"
    fin = end_half or "pm"
    charge = {jour: 1.0 for jour in ouvres}
    if debut == "pm" and start in charge:
        charge[start] = 0.5
    if fin == "am" and end in charge:
        charge[end] = 0.5
    return charge
