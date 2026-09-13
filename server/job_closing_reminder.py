"""Rappel de clôture du CRA.

    uv run python job_closing_reminder.py            # décide selon la date
    uv run python job_closing_reminder.py 2026-09-30 # simule un jour donné
    uv run python job_closing_reminder.py --force    # ignore le calendrier

Le job ne fait quelque chose que deux fois par mois : le dernier jour ouvré,
puis le 3 du mois suivant si la période est encore ouverte. Le timer systemd
peut donc tourner tous les jours sans réfléchir — c'est ici qu'on décide.
"""

import argparse
import calendar
import logging
import sys
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from main import (
    CRAEntry,
    MonthClosure,
    User,
    charge_absences,
    charger_feries,
    config_mail,
    engine,
    envoyer_et_journaliser,
    prefs_de,
)
import mail_content
from timesheet import missing_working_days, period_bounds

logger = logging.getLogger(__name__)

KIND = "closing_reminder"
JOUR_DE_RELANCE = 3


def dernier_jour_ouvre(annee: int, mois: int, feries: set[date]) -> date:
    """Dernier jour de la semaine du mois qui ne soit pas férié."""
    jour = date(annee, mois, calendar.monthrange(annee, mois)[1])
    while jour.weekday() >= 5 or jour in feries:
        jour -= timedelta(days=1)
    return jour


def periode_a_rappeler(jour: date, feries: set[date]) -> str | None:
    """Période concernée par un rappel ce jour-là, ou None."""
    if jour == dernier_jour_ouvre(jour.year, jour.month, feries):
        return f"{jour.year:04d}-{jour.month:02d}"
    if jour.day == JOUR_DE_RELANCE:
        precedent = date(jour.year, jour.month, 1) - timedelta(days=1)
        return f"{precedent.year:04d}-{precedent.month:02d}"
    return None


def run(jour: date, force_periode: str | None = None) -> dict[str, int]:
    """Envoie les rappels dus. Renvoie le décompte par statut."""
    resultats: dict[str, int] = {}
    base_url = config_mail().base_url

    with Session(engine) as session:
        annee = jour.year
        feries_annee = charger_feries(session, date(annee, 1, 1), date(annee, 12, 31))
        periode = force_periode or periode_a_rappeler(jour, feries_annee)
        if periode is None:
            logger.info("%s n'est ni une fin de mois ouvrée ni un %s.", jour, JOUR_DE_RELANCE)
            return {"hors_calendrier": 1}

        debut, fin = period_bounds(periode)
        feries = charger_feries(session, debut, fin)
        non_clotures = []

        for utilisateur in session.exec(select(User)).all():
            cloture = session.get(MonthClosure, (utilisateur.id, periode))
            if cloture is not None and cloture.status == "closed":
                resultats["cloture"] = resultats.get("cloture", 0) + 1
                continue

            non_clotures.append(utilisateur.full_name)

            if not prefs_de(session, utilisateur.id).closing_reminder:
                resultats["prefs_off"] = resultats.get("prefs_off", 0) + 1
                continue

            lignes = session.exec(
                select(CRAEntry).where(
                    CRAEntry.user_id == utilisateur.id,
                    CRAEntry.date >= debut,
                    CRAEntry.date <= fin,
                )
            ).all()
            trous = missing_working_days(
                periode,
                [(l.date, l.duration_factor) for l in lignes],
                charge_absences(session, utilisateur.id, debut, fin),
                feries,
            )

            contenu = mail_content.closing_reminder(
                utilisateur.full_name, periode, trous, base_url
            )
            statut = envoyer_et_journaliser(
                session,
                utilisateur.id,
                utilisateur.email,
                KIND,
                f"{periode}:{jour.isoformat()}",
                contenu,
            )
            resultats[statut] = resultats.get(statut, 0) + 1

        # Synthese pour l'administration : qui n'a pas cloture.
        if non_clotures:
            synthese = mail_content.digest(
                "l'équipe d'administration",
                {f"CRA {periode} non clôturés": sorted(non_clotures)},
                base_url,
            )
            for admin in session.exec(select(User).where(User.is_admin == True)).all():  # noqa: E712
                envoyer_et_journaliser(
                    session,
                    admin.id,
                    admin.email,
                    "closing_summary",
                    f"{periode}:{jour.isoformat()}",
                    synthese,
                )

    return resultats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jour", nargs="?", default=None, help="AAAA-MM-JJ")
    parser.add_argument(
        "--force",
        metavar="AAAA-MM",
        default=None,
        help="Rappeler cette période sans tenir compte du calendrier",
    )
    args = parser.parse_args()

    jour = (
        datetime.strptime(args.jour, "%Y-%m-%d").date() if args.jour else date.today()
    )
    resultats = run(jour, args.force)
    logger.info("Rappels du %s : %s", jour, resultats or "rien à envoyer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
