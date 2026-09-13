"""Absences : décompte, chevauchement, décision, soldes, calendrier d'équipe.

Couvre l'étape 3 de SPEC-CRA.md §13 et les quatre critères « Absences » du §12.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from holidays import holidays_for_year
from leaves import LeaveError, count_leave_days, working_days
from main import LeaveType, engine
from seed_holidays import seed as seed_holidays
from seed_leave_types import seed as seed_leave_types

FERIES_2026 = set(holidays_for_year(2026))


# --- Décompte, sans base ---------------------------------------------------


def test_vendredi_a_lundi_compte_deux_jours() -> None:
    """§12 — le week-end ne se décompte pas."""
    assert count_leave_days(date(2026, 5, 29), date(2026, 6, 1), FERIES_2026) == 2.0


def test_vendredi_a_lundi_avec_ferie_compte_un_jour() -> None:
    """§12 — le lundi 25/05/2026 est le lundi de Pentecôte."""
    assert count_leave_days(date(2026, 5, 22), date(2026, 5, 25), FERIES_2026) == 1.0


@pytest.mark.parametrize(
    "debut, fin, attendu",
    [
        (None, None, 1.0),
        ("am", "am", 0.5),
        ("pm", "pm", 0.5),
        ("am", "pm", 1.0),
    ],
)
def test_demi_journees_sur_un_seul_jour(debut, fin, attendu) -> None:
    jour = date(2026, 6, 2)
    assert count_leave_days(jour, jour, FERIES_2026, debut, fin) == attendu


def test_journee_unique_qui_finit_avant_de_commencer() -> None:
    jour = date(2026, 6, 2)
    with pytest.raises(LeaveError):
        count_leave_days(jour, jour, FERIES_2026, "pm", "am")


def test_demi_journees_aux_deux_bornes() -> None:
    """Lundi après-midi au mercredi matin : 0,5 + 1 + 0,5."""
    assert (
        count_leave_days(date(2026, 6, 1), date(2026, 6, 3), FERIES_2026, "pm", "am")
        == 2.0
    )


def test_borne_tombant_un_week_end_ne_retranche_rien() -> None:
    """Commencer « samedi après-midi » ne consomme pas une demi-journée."""
    assert (
        count_leave_days(date(2026, 6, 6), date(2026, 6, 9), FERIES_2026, "pm", None)
        == 2.0
    )


def test_periode_sans_jour_ouvre() -> None:
    assert count_leave_days(date(2026, 6, 6), date(2026, 6, 7), FERIES_2026) == 0.0


def test_dates_inversees_refusees() -> None:
    with pytest.raises(LeaveError):
        count_leave_days(date(2026, 6, 10), date(2026, 6, 1), FERIES_2026)


def test_jours_ouvres_excluent_feries_et_week_ends() -> None:
    jours = working_days(date(2026, 5, 22), date(2026, 5, 26), FERIES_2026)
    assert jours == [date(2026, 5, 22), date(2026, 5, 26)]


# --- Fixtures d'API --------------------------------------------------------


@pytest.fixture
def cp_id() -> int:
    seed_leave_types()
    with Session(engine) as session:
        cp = session.exec(select(LeaveType).where(LeaveType.code == "CP")).first()
        return cp.id


@pytest.fixture(autouse=True)
def feries() -> None:
    seed_holidays(2026, 2026)


def _demander(
    client: TestClient,
    entetes: dict[str, str],
    cp_id: int,
    debut: str,
    fin: str,
    **extra,
) -> dict:
    reponse = client.post(
        "/leaves",
        json={"leave_type_id": cp_id, "start_date": debut, "end_date": fin, **extra},
        headers=entetes,
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


# --- Dépôt -----------------------------------------------------------------


def test_demande_calcule_son_decompte(
    client: TestClient, entetes_consultant: dict[str, str], cp_id: int
) -> None:
    demande = _demander(client, entetes_consultant, cp_id, "2026-05-22", "2026-05-25")
    assert demande["days"] == 1.0
    assert demande["status"] == "pending"


def test_decompte_du_client_est_ignore(
    client: TestClient, entetes_consultant: dict[str, str], cp_id: int
) -> None:
    """Le nombre de jours ne se prend pas dans la requête."""
    demande = _demander(
        client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05", days=99
    )
    assert demande["days"] == 5.0


def test_chevauchement_refuse(
    client: TestClient, entetes_consultant: dict[str, str], cp_id: int
) -> None:
    """§12 — deux demandes qui se chevauchent : la seconde est refusée."""
    _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")
    reponse = client.post(
        "/leaves",
        json={
            "leave_type_id": cp_id,
            "start_date": "2026-06-04",
            "end_date": "2026-06-10",
        },
        headers=entetes_consultant,
    )
    assert reponse.status_code == 409


def test_demande_annulee_ne_bloque_plus(
    client: TestClient, entetes_consultant: dict[str, str], cp_id: int
) -> None:
    demande = _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")
    client.post(f"/leaves/{demande['id']}/cancel", headers=entetes_consultant)
    _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")


def test_periode_sans_jour_ouvre_refusee(
    client: TestClient, entetes_consultant: dict[str, str], cp_id: int
) -> None:
    reponse = client.post(
        "/leaves",
        json={
            "leave_type_id": cp_id,
            "start_date": "2026-06-06",
            "end_date": "2026-06-07",
        },
        headers=entetes_consultant,
    )
    assert reponse.status_code == 422


def test_consultant_ne_depose_pas_pour_un_autre(
    client: TestClient,
    entetes_consultant: dict[str, str],
    cp_id: int,
    admin_id: int,
) -> None:
    reponse = client.post(
        "/leaves",
        json={
            "leave_type_id": cp_id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "user_id": admin_id,
        },
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


def test_admin_depose_pour_un_consultant(
    client: TestClient,
    entetes_admin: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    demande = _demander(
        client,
        entetes_admin,
        cp_id,
        "2026-06-01",
        "2026-06-02",
        user_id=consultant_id,
    )
    assert demande["user_id"] == consultant_id


# --- Décision --------------------------------------------------------------


def test_admin_approuve(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
) -> None:
    demande = _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")
    reponse = client.post(
        f"/leaves/{demande['id']}/decide",
        json={"approve": True, "comment": "ok"},
        headers=entetes_admin,
    )
    assert reponse.status_code == 200
    assert reponse.json()["status"] == "approved"
    assert reponse.json()["decision_comment"] == "ok"


def test_consultant_ne_decide_pas(
    client: TestClient, entetes_consultant: dict[str, str], cp_id: int
) -> None:
    demande = _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")
    reponse = client.post(
        f"/leaves/{demande['id']}/decide",
        json={"approve": True},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


def test_decision_sur_demande_deja_tranchee(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
) -> None:
    demande = _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")
    client.post(
        f"/leaves/{demande['id']}/decide", json={"approve": True}, headers=entetes_admin
    )
    reponse = client.post(
        f"/leaves/{demande['id']}/decide",
        json={"approve": False},
        headers=entetes_admin,
    )
    assert reponse.status_code == 409


def test_consultant_n_annule_pas_la_demande_d_un_autre(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    admin_id: int,
) -> None:
    demande = _demander(
        client, entetes_admin, cp_id, "2026-06-01", "2026-06-05", user_id=admin_id
    )
    reponse = client.post(
        f"/leaves/{demande['id']}/cancel", headers=entetes_consultant
    )
    assert reponse.status_code == 403


# --- Soldes ----------------------------------------------------------------


def _poser_solde(
    client: TestClient,
    entetes_admin: dict[str, str],
    user_id: int,
    cp_id: int,
    acquis: float,
) -> None:
    reponse = client.put(
        "/leaves/balances",
        json={
            "user_id": user_id,
            "year": 2026,
            "leave_type_id": cp_id,
            "acquired": acquis,
        },
        headers=entetes_admin,
    )
    assert reponse.status_code == 200, reponse.text


def test_solde_ne_bouge_qu_a_l_approbation(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    """§12 — une demande en attente n'est jamais déduite."""
    _poser_solde(client, entetes_admin, consultant_id, cp_id, 25.0)
    demande = _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")

    avant = client.get("/leaves/balances?year=2026", headers=entetes_admin).json()[0]
    assert avant["remaining"] == 25.0
    assert avant["pending"] == 5.0
    assert avant["taken"] == 0.0

    client.post(
        f"/leaves/{demande['id']}/decide", json={"approve": True}, headers=entetes_admin
    )

    apres = client.get("/leaves/balances?year=2026", headers=entetes_admin).json()[0]
    assert apres["remaining"] == 20.0
    assert apres["taken"] == 5.0
    assert apres["pending"] == 0.0


def test_ajustement_entre_dans_le_solde(
    client: TestClient,
    entetes_admin: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    client.put(
        "/leaves/balances",
        json={
            "user_id": consultant_id,
            "year": 2026,
            "leave_type_id": cp_id,
            "acquired": 25.0,
            "adjustment": 3.5,
        },
        headers=entetes_admin,
    )
    solde = client.get("/leaves/balances?year=2026", headers=entetes_admin).json()[0]
    assert solde["remaining"] == 28.5


def test_consultant_ne_pose_pas_de_solde(
    client: TestClient,
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    reponse = client.put(
        "/leaves/balances",
        json={
            "user_id": consultant_id,
            "year": 2026,
            "leave_type_id": cp_id,
            "acquired": 99.0,
        },
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


# --- Calendrier d'équipe ---------------------------------------------------


def test_calendrier_montre_les_absences_approuvees(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
) -> None:
    """§12 — le calendrier d'équipe affiche les absences approuvées du mois."""
    demande = _demander(client, entetes_consultant, cp_id, "2026-06-01", "2026-06-05")
    en_attente = client.get(
        "/leaves/team-calendar?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_consultant,
    ).json()
    assert en_attente == []

    client.post(
        f"/leaves/{demande['id']}/decide", json={"approve": True}, headers=entetes_admin
    )
    approuvees = client.get(
        "/leaves/team-calendar?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_consultant,
    ).json()
    assert len(approuvees) == 1
    assert approuvees[0]["leave_type"] == "CP"
    assert approuvees[0]["days"] == 5.0
