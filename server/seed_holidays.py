"""Alimente la table des jours fériés.

Par défaut de l'année précédente à N+2, la fenêtre dont l'application a
besoin : le CRA de l'an dernier reste consultable, et les congés se posent
sur l'année suivante.

    uv run python seed_holidays.py                # N-1 → N+2
    uv run python seed_holidays.py 2024 2030      # fenêtre explicite

Le script est idempotent : relancé, il met à jour les libellés et n'ajoute
aucun doublon. Il ne supprime jamais une date déjà en base — un férié saisi
à la main (pont d'entreprise, jour local d'Alsace-Moselle) y survit.
"""

import argparse
import logging
import sys
from datetime import date

from sqlmodel import Session, select

from holidays import holidays_for_range
from main import PublicHoliday, engine

logger = logging.getLogger(__name__)


def seed(first_year: int, last_year: int) -> tuple[int, int]:
    """Écrit les fériés de la fenêtre. Renvoie (ajoutés, mis à jour)."""
    attendus = holidays_for_range(first_year, last_year)
    ajoutes = modifies = 0

    with Session(engine) as session:
        existants = {
            j.date: j
            for j in session.exec(
                select(PublicHoliday).where(
                    PublicHoliday.date >= date(first_year, 1, 1),
                    PublicHoliday.date <= date(last_year, 12, 31),
                )
            ).all()
        }

        for jour, libelle in attendus.items():
            existant = existants.get(jour)
            if existant is None:
                session.add(PublicHoliday(date=jour, label=libelle))
                ajoutes += 1
            elif existant.label != libelle:
                existant.label = libelle
                session.add(existant)
                modifies += 1

        session.commit()

    return ajoutes, modifies


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    annee = date.today().year

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_year", nargs="?", type=int, default=annee - 1)
    parser.add_argument("last_year", nargs="?", type=int, default=annee + 2)
    args = parser.parse_args()

    if args.last_year < args.first_year:
        logger.error("L'année de fin précède l'année de début.")
        return 1

    ajoutes, modifies = seed(args.first_year, args.last_year)
    logger.info(
        "Jours fériés %s-%s : %s ajouté(s), %s mis à jour.",
        args.first_year,
        args.last_year,
        ajoutes,
        modifies,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
