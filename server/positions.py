"""Ordre des cartes dans une colonne de kanban.

Les positions sont des réels : insérer entre deux cartes revient à prendre
leur moyenne, sans réécrire toute la colonne à chaque glisser-déposer.

Le piège est la précision. À force d'insérer au même endroit, l'écart entre
deux voisines est divisé par deux à chaque fois et finit par tomber sous la
résolution du flottant : deux cartes prennent alors la même position et
l'ordre devient arbitraire. D'où le rééquilibrage, déclenché avant que ça
n'arrive.
"""

import logging
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# Écart posé entre deux cartes lors d'un rééquilibrage, et en bout de colonne.
GAP = 1000.0

# En dessous de cet écart, les moyennes successives ne sont plus fiables.
MIN_GAP = 0.0001


def position_between(
    before: Optional[float], after: Optional[float]
) -> float:
    """Position d'une carte glissée entre `before` et `after`.

    `before` est la carte qui la précède, `after` celle qui la suit ; `None`
    signifie « bout de colonne ». Colonne vide : les deux sont `None`.
    """
    if before is None and after is None:
        return 0.0
    if before is None:
        return after - GAP
    if after is None:
        return before + GAP
    if after <= before:
        raise ValueError("Les deux voisines ne sont pas dans l'ordre")
    return (before + after) / 2


def needs_rebalance(before: Optional[float], after: Optional[float]) -> bool:
    """L'insertion entre ces deux voisines est-elle trop serrée ?"""
    if before is None or after is None:
        return False
    return (after - before) < MIN_GAP


def rebalance(count: int) -> list[float]:
    """Positions régulières pour une colonne de `count` cartes, dans l'ordre."""
    return [GAP * (i + 1) for i in range(count)]


def sorted_positions(positions: Sequence[float]) -> bool:
    """Les positions sont-elles strictement croissantes ? Utilisé par les tests."""
    return all(a < b for a, b in zip(positions, positions[1:]))
