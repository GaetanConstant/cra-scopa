"""Rappels de clôture du CRA, le 18 et le 20 de chaque mois.

    uv run python job_closing_reminder.py            # décide selon la date
    uv run python job_closing_reminder.py 2026-09-18 # simule un jour donné
    uv run python job_closing_reminder.py --force 2026-09

Deux rappels, le 18 et le 20, sur le mois en cours : les salaires sont
établis à partir des CRA clôturés, il faut donc que chacun ait arrêté le
sien avant la paie. Les jours manquants couvrent **tout le mois**, jours à
venir compris : le CRA se remplit par anticipation et se clôture avant la
fin du mois.

Quand une date tombe un week-end ou un férié, le rappel **recule** au jour
ouvré précédent — jamais après : un rappel lu le lundi 21 arrive trop tard.
Le 18 et le 20 ne peuvent pas être tous deux un week-end (deux jours
d'écart) ; s'ils reculent sur le même jour ouvré, un seul mail part.

Le job ne fait rien les autres jours : le timer systemd peut tourner tous
les matins sans réfléchir, c'est ici qu'on décide.
"""

import argparse
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
JOURS_DE_RAPPEL = (18, 20)


def jour_ouvre_avant(jour: date, feries: set[date]) -> date:
    """Le jour lui-même s'il est ouvré, sinon le dernier jour ouvré avant."""
    while jour.weekday() >= 5 or jour in feries:
        jour -= timedelta(days=1)
    return jour


def jours_de_rappel(annee: int, mois: int, feries: set[date]) -> list[date]:
    """Jours d'envoi du mois, dédoublonnés et triés.

    Un rappel envoyé un dimanche est lu le lundi au milieu d'autre chose ;
    on préfère le vendredi, quand il reste du temps pour agir.
    """
    return sorted(
        {jour_ouvre_avant(date(annee, mois, j), feries) for j in JOURS_DE_RAPPEL}
    )


def periode_a_rappeler(jour: date, feries: set[date] = frozenset()) -> str | None:
    """Période concernée par un rappel ce jour-là, ou None.

    Le rappel porte sur le mois en cours, le dernier jour ouvré jusqu'au 18
    puis jusqu'au 20. Les autres jours, rien.
    """
    if jour not in jours_de_rappel(jour.year, jour.month, feries):
        return None
    return f"{jour.year:04d}-{jour.month:02d}"


def run(jour: date, force_periode: str | None = None) -> dict[str, int]:
    """Envoie les rappels dus. Renvoie le décompte par statut."""
    resultats: dict[str, int] = {}
    base_url = config_mail().base_url

    with Session(engine) as session:
        feries_du_mois = charger_feries(
            session, date(jour.year, jour.month, 1), date(jour.year, jour.month, 28)
        )
        periode = force_periode or periode_a_rappeler(jour, feries_du_mois)
        if periode is None:
            logger.info(
                "%s n'est pas un jour de rappel (%s).",
                jour,
                ", ".join(
                    d.isoformat()
                    for d in jours_de_rappel(jour.year, jour.month, feries_du_mois)
                ),
            )
            return {"hors_calendrier": 1}

        debut, fin = period_bounds(periode)
        feries = charger_feries(session, debut, fin)
        non_clotures = []

        for utilisateur in session.exec(select(User).where(User.is_active == True)).all():  # noqa: E712
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
