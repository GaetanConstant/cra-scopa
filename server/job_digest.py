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
from datetime import date, datetime

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


def _libelle(ticket: TkTicket, projets: dict[int, Project], aujourdhui: date) -> str:
    """L'année n'apparaît que hors de l'année en cours : une échéance
    « 08/10 — EN RETARD » un 15 septembre cache une faute de frappe sur
    l'année, « 08/10/2016 » la montre."""
    projet = projets.get(ticket.project_id)
    suffixe = f" [{projet.code or projet.name}]" if projet else ""
    echeance = ""
    if ticket.due_date:
        forme = "%d/%m" if ticket.due_date.year == aujourdhui.year else "%d/%m/%Y"
        echeance = f" — échéance {ticket.due_date:{forme}}"
    return f"#{ticket.id} {ticket.title}{suffixe}{echeance}"


def _anciennete(ticket: TkTicket, aujourdhui: date) -> str:
    jours = (aujourdhui - ticket.updated_at.date()).days
    if jours <= 0:
        return "aujourd'hui"
    return f"depuis {jours} jour{'s' if jours > 1 else ''}"


def sections_pour(
    session: Session, utilisateur: User, aujourdhui: date
) -> dict[str, list[str]]:
    """Ce qu'un utilisateur doit voir ce matin.

    Comme assigne : ce qu'il a a faire et ce qu'il a en cours, tous les jours
    tant que la liste n'est pas vide. Comme rapporteur : ce qui attend sa
    relecture. Une echeance depassee est signalee sur la ligne plutot que
    dans une section a part.
    """
    projets = {p.id: p for p in session.exec(select(Project)).all()}

    def ligne(t: TkTicket, avec_anciennete: bool = False) -> str:
        texte = _libelle(t, projets, aujourdhui)
        if t.due_date and t.due_date < aujourdhui:
            texte += " — EN RETARD"
        if avec_anciennete:
            texte += f" ({_anciennete(t, aujourdhui)})"
        return texte

    miens = session.exec(
        select(TkTicket)
        .where(
            TkTicket.assignee_id == utilisateur.id,
            TkTicket.status.in_(("todo", "in_progress")),
        )
        .order_by(TkTicket.position)
    ).all()
    a_relire = session.exec(
        select(TkTicket)
        .where(
            TkTicket.reporter_id == utilisateur.id,
            TkTicket.status == "to_validate",
        )
        .order_by(TkTicket.position)
    ).all()

    return {
        "À faire": [ligne(t) for t in miens if t.status == "todo"],
        "En cours": [ligne(t, avec_anciennete=True) for t in miens if t.status == "in_progress"],
        "À valider": [ligne(t) for t in a_relire],
    }


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
