"""Jours fériés : calcul de Pâques, dérivés, alimentation et lecture.

Couvre l'étape 2 de SPEC-CRA.md §13, qui demande explicitement des tests
sur Pâques et la Pentecôte.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from holidays import easter_sunday, holidays_for_range, holidays_for_year
from main import PublicHoliday, engine
from seed_holidays import seed


# --- Pâques ----------------------------------------------------------------

# Dates de référence publiées par l'Église catholique romaine. Elles couvrent
# les deux branches de l'algorithme : Pâques en mars comme en avril, et 2038
# qui est le cas tardif classique.
PAQUES = {
    2024: date(2024, 3, 31),
    2025: date(2025, 4, 20),
    2026: date(2026, 4, 5),
    2027: date(2027, 3, 28),
    2028: date(2028, 4, 16),
    2030: date(2030, 4, 21),
    2038: date(2038, 4, 25),
}


@pytest.mark.parametrize("annee, attendu", sorted(PAQUES.items()))
def test_dimanche_de_paques(annee: int, attendu: date) -> None:
    assert easter_sunday(annee) == attendu


def test_paques_tombe_toujours_un_dimanche() -> None:
    for annee in range(2020, 2061):
        assert easter_sunday(annee).weekday() == 6, annee


# --- Fériés mobiles --------------------------------------------------------


def test_feries_mobiles_2026() -> None:
    """Pâques 2026 tombe le 5 avril : les trois dérivés en découlent."""
    jours = holidays_for_year(2026)
    assert jours[date(2026, 4, 6)] == "Lundi de Pâques"
    assert jours[date(2026, 5, 14)] == "Ascension"
    assert jours[date(2026, 5, 25)] == "Lundi de Pentecôte"


def test_ascension_toujours_un_jeudi_pentecote_un_lundi() -> None:
    for annee in range(2020, 2041):
        jours = holidays_for_year(annee)
        ascension = next(d for d, l in jours.items() if l == "Ascension")
        pentecote = next(d for d, l in jours.items() if l == "Lundi de Pentecôte")
        assert ascension.weekday() == 3, annee
        assert pentecote.weekday() == 0, annee


def test_onze_feries_par_an() -> None:
    for annee in range(2020, 2041):
        assert len(holidays_for_year(annee)) == 11, annee


def test_feries_fixes_presents() -> None:
    jours = holidays_for_year(2026)
    assert jours[date(2026, 1, 1)] == "Jour de l'an"
    assert jours[date(2026, 5, 1)] == "Fête du Travail"
    assert jours[date(2026, 12, 25)] == "Noël"


def test_plage_inversee_refusee() -> None:
    with pytest.raises(ValueError):
        holidays_for_range(2027, 2025)


# --- Alimentation ----------------------------------------------------------


def test_seed_ecrit_la_fenetre_demandee() -> None:
    ajoutes, modifies = seed(2025, 2027)
    assert (ajoutes, modifies) == (33, 0)  # 11 par an sur trois ans

    with Session(engine) as session:
        total = len(session.exec(select(PublicHoliday)).all())
    assert total == 33


def test_seed_est_idempotent() -> None:
    seed(2026, 2026)
    ajoutes, modifies = seed(2026, 2026)
    assert (ajoutes, modifies) == (0, 0)

    with Session(engine) as session:
        assert len(session.exec(select(PublicHoliday)).all()) == 11


def test_seed_conserve_un_ferie_saisi_a_la_main() -> None:
    """Un pont d'entreprise posé en base ne doit pas disparaître."""
    pont = date(2026, 5, 15)  # lendemain de l'Ascension
    with Session(engine) as session:
        session.add(PublicHoliday(date=pont, label="Pont de l'Ascension"))
        session.commit()

    seed(2026, 2026)

    with Session(engine) as session:
        garde = session.get(PublicHoliday, pont)
    assert garde is not None
    assert garde.label == "Pont de l'Ascension"


# --- Lecture par l'API -----------------------------------------------------


def test_holidays_exige_un_jeton(client: TestClient) -> None:
    assert client.get("/holidays").status_code == 401


def test_holidays_filtre_sur_l_annee(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    seed(2025, 2027)
    reponse = client.get("/holidays?year=2026", headers=entetes_consultant)
    assert reponse.status_code == 200

    jours = reponse.json()
    assert len(jours) == 11
    assert jours[0] == {"date": "2026-01-01", "label": "Jour de l'an"}
    assert jours[-1] == {"date": "2026-12-25", "label": "Noël"}


def test_holidays_sans_annee_renvoie_tout(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    seed(2025, 2026)
    reponse = client.get("/holidays", headers=entetes_consultant)
    assert len(reponse.json()) == 22
