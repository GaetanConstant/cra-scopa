"""Cloisonnement : ce qu'un consultant peut lire, et ce qu'il ne peut pas.

Masquer un onglet dans la navbar ne protège rien — l'API répond à qui
l'appelle directement. Ces tests portent sur le serveur, pas sur l'écran.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from main import LeaveBalance, LeaveType, engine
from seed_holidays import seed as seed_holidays
from seed_leave_types import seed as seed_leave_types


@pytest.fixture(autouse=True)
def referentiel() -> None:
    seed_holidays(2026, 2026)
    seed_leave_types()


@pytest.fixture
def cp_id() -> int:
    with Session(engine) as session:
        return session.exec(select(LeaveType).where(LeaveType.code == "CP")).first().id


# --- Activité --------------------------------------------------------------


def test_consultant_ne_lit_pas_l_activite(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.get(
        "/reporting/activity?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


def test_consultant_n_exporte_pas_l_activite(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.get(
        "/reporting/activity/export?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


# --- CRA -------------------------------------------------------------------


def test_consultant_ne_lit_pas_le_cra_de_l_equipe(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    assert client.get("/cra/all/2026/6", headers=entetes_consultant).status_code == 403


def test_consultant_ne_lit_pas_le_cra_d_un_autre(
    client: TestClient, entetes_consultant: dict[str, str], admin_id: int
) -> None:
    reponse = client.get(f"/cra/{admin_id}/2026/6", headers=entetes_consultant)
    assert reponse.status_code == 403


def test_consultant_lit_son_propre_cra(
    client: TestClient, entetes_consultant: dict[str, str], consultant_id: int
) -> None:
    reponse = client.get(f"/cra/{consultant_id}/2026/6", headers=entetes_consultant)
    assert reponse.status_code == 200


def test_consultant_ne_lit_pas_le_mois_d_un_autre(
    client: TestClient, entetes_consultant: dict[str, str], admin_id: int
) -> None:
    reponse = client.get(
        f"/time?period=2026-06&user_id={admin_id}", headers=entetes_consultant
    )
    assert reponse.status_code == 403


def test_admin_lit_le_mois_d_un_consultant(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    reponse = client.get(
        f"/time?period=2026-06&user_id={consultant_id}", headers=entetes_admin
    )
    assert reponse.status_code == 200
    assert reponse.json()["user_id"] == consultant_id


# --- Congés ----------------------------------------------------------------


def test_consultant_ne_voit_que_ses_demandes(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    admin_id: int,
    consultant_id: int,
) -> None:
    for entetes in (entetes_admin, entetes_consultant):
        client.post(
            "/leaves",
            json={
                "leave_type_id": cp_id,
                "start_date": "2026-06-01",
                "end_date": "2026-06-02",
            },
            headers=entetes,
        )

    vues = client.get("/leaves", headers=entetes_consultant).json()
    assert {d["user_id"] for d in vues} == {consultant_id}

    # Même en demandant explicitement celles d'un autre.
    ciblees = client.get(f"/leaves?user_id={admin_id}", headers=entetes_consultant).json()
    assert {d["user_id"] for d in ciblees} == {consultant_id}

    # L'administration voit tout.
    assert len(client.get("/leaves", headers=entetes_admin).json()) == 2


def test_consultant_ne_voit_que_ses_soldes(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    admin_id: int,
    consultant_id: int,
) -> None:
    with Session(engine) as session:
        for uid in (admin_id, consultant_id):
            session.add(
                LeaveBalance(user_id=uid, year=2026, leave_type_id=cp_id, acquired=25.0)
            )
        session.commit()

    vus = client.get("/leaves/balances?year=2026", headers=entetes_consultant).json()
    assert {s["user_id"] for s in vus} == {consultant_id}
    assert len(client.get("/leaves/balances?year=2026", headers=entetes_admin).json()) == 2


def test_calendrier_d_equipe_reste_ouvert(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
) -> None:
    """Savoir qui est absent quand est nécessaire pour s'organiser."""
    demande = client.post(
        "/leaves",
        json={
            "leave_type_id": cp_id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
        },
        headers=entetes_admin,
    ).json()
    client.post(
        f"/leaves/{demande['id']}/decide", json={"approve": True}, headers=entetes_admin
    )

    vu = client.get(
        "/leaves/team-calendar?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_consultant,
    )
    assert vu.status_code == 200
    assert len(vu.json()) == 1


# --- Ce qui reste ouvert, et pourquoi --------------------------------------


def test_annuaire_et_referentiel_restent_lisibles(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    """Les écrans Congés et Tickets ont besoin des noms et des projets."""
    assert client.get("/users/", headers=entetes_consultant).status_code == 200
    assert client.get("/projects/", headers=entetes_consultant).status_code == 200
    assert client.get("/tickets/board", headers=entetes_consultant).status_code == 200


# --- Tickets ---------------------------------------------------------------


def _ticket(client: TestClient, entetes: dict[str, str], **champs) -> dict:
    reponse = client.post("/tickets", json={"title": "T", **champs}, headers=entetes)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def test_consultant_ne_voit_que_ses_tickets(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
    admin_id: int,
) -> None:
    a_lui = _ticket(client, entetes_admin, title="Assigné au consultant",
                    assignee_id=consultant_id)
    ouvert_par_lui = _ticket(client, entetes_consultant, title="Ouvert par lui")
    _ticket(client, entetes_admin, title="Pour l'admin", assignee_id=admin_id)

    vus = client.get("/tickets/board", headers=entetes_consultant).json()
    ids = {t["id"] for colonne in vus.values() for t in colonne}
    assert ids == {a_lui["id"], ouvert_par_lui["id"]}

    tous = client.get("/tickets/board", headers=entetes_admin).json()
    assert len({t["id"] for c in tous.values() for t in c}) == 3


def test_consultant_n_ouvre_pas_le_ticket_d_un_autre(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    admin_id: int,
) -> None:
    autre = _ticket(client, entetes_admin, assignee_id=admin_id)
    assert client.get(f"/tickets/{autre['id']}", headers=entetes_consultant).status_code == 404


def test_consultant_ne_modifie_pas_le_ticket_d_un_autre(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    admin_id: int,
) -> None:
    autre = _ticket(client, entetes_admin, assignee_id=admin_id)
    assert (
        client.patch(
            f"/tickets/{autre['id']}", json={"title": "détourné"}, headers=entetes_consultant
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/tickets/{autre['id']}/move", json={"status": "done"}, headers=entetes_consultant
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/tickets/{autre['id']}/comments", json={"body": "coucou"},
            headers=entetes_consultant,
        ).status_code
        == 404
    )


def test_consultant_agit_sur_ses_propres_tickets(
    client: TestClient, entetes_consultant: dict[str, str], consultant_id: int
) -> None:
    sien = _ticket(client, entetes_consultant, assignee_id=consultant_id)
    assert client.get(f"/tickets/{sien['id']}", headers=entetes_consultant).status_code == 200
    assert (
        client.post(
            f"/tickets/{sien['id']}/move", json={"status": "in_progress"},
            headers=entetes_consultant,
        ).status_code
        == 200
    )
