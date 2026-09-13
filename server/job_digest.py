"""Récap matinal, du lundi au vendredi.

    uv run python job_digest.py            # aujourd'hui
    uv run python job_digest.py 2026-09-15 # une date précise

Appelé par un timer systemd, pas par un ordonnanceur intégré au serveur web :
un seul point d'exécution, aucun doublon si plusieurs workers tournent, et
relançable à la main. Le journal d'envoi rend la relance sans effet si le
récap du jour est déjà parti.

Rien n'est envoyé à qui n'a rien à lire.
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from main import (
    EmailLog,
    Project,
    PublicHoliday,
    TkTicket,
    User,
    config_mail,
    engine,
    envoyer_et_journaliser,
    prefs_de,
)
import mail_content

logger = logging.getLogger(__name__)

KIND = "daily_digest"
STATUTS_OUVERTS = ("todo", "in_progress", "to_validate")


def _libelle(ticket: TkTicket, projets: dict[int, Project]) -> str:
    projet = projets.get(ticket.project_id)
    suffixe = f" [{projet.code or projet.name}]" if projet else ""
    echeance = f" — échéance {ticket.due_date:%d/%m}" if ticket.due_date else ""
    return f"#{ticket.id} {ticket.title}{suffixe}{echeance}"


def _anciennete(ticket: TkTicket, aujourdhui: date) -> str:
    jours = (aujourdhui - ticket.updated_at.date()).days
    if jours <= 0:
        return "aujourd'hui"
    return f"depuis {jours} jour{'s' if jours > 1 else ''}"


def sections_pour(
    session: Session, utilisateur: User, aujourdhui: date
) -> dict[str, list[str]]:
    """Ce qu'un utilisateur doit voir ce matin."""
    projets = {p.id: p for p in session.exec(select(Project)).all()}
    demain = aujourdhui + timedelta(days=1)

    miens = session.exec(
        select(TkTicket).where(
            TkTicket.assignee_id == utilisateur.id,
            TkTicket.status.in_(STATUTS_OUVERTS),
        )
    ).all()

    en_retard = [
        _libelle(t, projets)
        for t in miens
        if t.due_date and t.due_date < aujourdhui
    ]
    en_cours = [
        f"{_libelle(t, projets)} ({_anciennete(t, aujourdhui)})"
        for t in miens
        if t.status == "in_progress"
    ]
    a_valider = [_libelle(t, projets) for t in miens if t.status == "to_validate"]
    echeances = [
        _libelle(t, projets)
        for t in miens
        if t.due_date in (aujourdhui, demain)
    ]

    sections = {
        "Tickets en retard": en_retard,
        "En cours": en_cours,
        "À valider": a_valider,
        "Échéances aujourd'hui et demain": echeances,
    }

    # L'administrateur voit en plus ce que toute l'équipe lui soumet.
    if utilisateur.is_admin:
        equipe = session.exec(
            select(TkTicket).where(
                TkTicket.status == "to_validate",
                TkTicket.assignee_id != utilisateur.id,
            )
        ).all()
        sections["À valider — équipe"] = [_libelle(t, projets) for t in equipe]

    return sections


def run(jour: date) -> dict[str, int]:
    """Envoie le récap du jour. Renvoie le décompte par statut."""
    if jour.weekday() >= 5:
        logger.info("%s est un week-end, pas de récap.", jour)
        return {"weekend": 1}

    resultats: dict[str, int] = {}
    base_url = config_mail().base_url

    with Session(engine) as session:
        # Un récap le 11 novembre serait lu le 12, avec un jour de retard sur
        # tout ce qu'il annonce. On se tait les jours fériés.
        if session.get(PublicHoliday, jour) is not None:
            logger.info("%s est férié, pas de récap.", jour)
            return {"ferie": 1}

        for utilisateur in session.exec(select(User).where(User.is_active == True)).all():  # noqa: E712
            if not prefs_de(session, utilisateur.id).daily_digest:
                resultats["prefs_off"] = resultats.get("prefs_off", 0) + 1
                continue

            contenu = mail_content.digest(
                utilisateur.full_name,
                sections_pour(session, utilisateur, jour),
                base_url,
            )
            if contenu is None:
                resultats["vide"] = resultats.get("vide", 0) + 1
                continue

            statut = envoyer_et_journaliser(
                session,
                utilisateur.id,
                utilisateur.email,
                KIND,
                jour.isoformat(),
                contenu,
            )
            resultats[statut] = resultats.get(statut, 0) + 1

    return resultats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jour", nargs="?", default=None, help="AAAA-MM-JJ")
    args = parser.parse_args()

    jour = (
        datetime.strptime(args.jour, "%Y-%m-%d").date() if args.jour else date.today()
    )
    resultats = run(jour)
    logger.info("Récap du %s : %s", jour, resultats or "rien à envoyer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
