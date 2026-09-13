"""Pose les types d'absence de référence.

    uv run python seed_leave_types.py

Idempotent : relancé, il met à jour libellé, couleur et décompte, et ne crée
aucun doublon. Il ne supprime pas les types ajoutés à la main.

`counts_against_balance` dit si le type consomme un droit acquis. Un arrêt
maladie ou un congé sans solde n'entament aucun compteur : ils s'observent,
ils ne se décomptent pas.
"""

import logging
import sys

from sqlmodel import Session, select

from main import LeaveType, engine

logger = logging.getLogger(__name__)

# (code, libellé, décompté sur un solde, couleur)
LEAVE_TYPES: tuple[tuple[str, str, bool, str], ...] = (
    ("CP", "Congés payés", True, "#6186EA"),
    ("RTT", "RTT", True, "#22c55e"),
    ("MALADIE", "Arrêt maladie", False, "#ef4444"),
    ("SANS_SOLDE", "Congé sans solde", False, "#9ca3af"),
    ("FORMATION", "Formation", False, "#3b82f6"),
)


def seed() -> tuple[int, int]:
    """Écrit les types de référence. Renvoie (ajoutés, mis à jour)."""
    ajoutes = modifies = 0

    with Session(engine) as session:
        existants = {t.code: t for t in session.exec(select(LeaveType)).all()}

        for code, libelle, decompte, couleur in LEAVE_TYPES:
            existant = existants.get(code)
            if existant is None:
                session.add(
                    LeaveType(
                        code=code,
                        label=libelle,
                        counts_against_balance=decompte,
                        color=couleur,
                    )
                )
                ajoutes += 1
                continue

            attendu = (libelle, decompte, couleur)
            actuel = (existant.label, existant.counts_against_balance, existant.color)
            if actuel != attendu:
                existant.label, existant.counts_against_balance, existant.color = attendu
                session.add(existant)
                modifies += 1

        session.commit()

    return ajoutes, modifies


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ajoutes, modifies = seed()
    logger.info("Types d'absence : %s ajouté(s), %s mis à jour.", ajoutes, modifies)
    return 0


if __name__ == "__main__":
    sys.exit(main())
