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


# --- Tickets : projet et suppression ---------------------------------------


def _affecter(
    client: TestClient, entetes_admin: dict[str, str], user_id: int, project_id: int
) -> None:
    client.post(
        f"/users/{user_id}/projects",
        json={"project_ids": [project_id]},
        headers=entetes_admin,
    )


def _creer_projet(client: TestClient, entetes_admin: dict[str, str], nom: str) -> int:
    return client.post(
        "/projects/", json={"name": nom, "category": "Mission"}, headers=entetes_admin
    ).json()["id"]


def test_consultant_ne_cree_pas_de_ticket_sur_un_projet_non_affecte(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
) -> None:
    autre = _creer_projet(client, entetes_admin, "PROJET DES AUTRES")
    reponse = client.post(
        "/tickets",
        json={"title": "Intrusion", "project_id": autre},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403
    assert "pas affecte" in reponse.json()["detail"]


def test_consultant_cree_un_ticket_sur_sa_mission(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    sien = _creer_projet(client, entetes_admin, "SA MISSION")
    _affecter(client, entetes_admin, consultant_id, sien)
    reponse = client.post(
        "/tickets", json={"title": "Chez moi", "project_id": sien}, headers=entetes_consultant
    )
    assert reponse.status_code == 200
    assert reponse.json()["project_id"] == sien


def test_consultant_ne_deplace_pas_un_ticket_vers_un_projet_non_affecte(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
) -> None:
    autre = _creer_projet(client, entetes_admin, "PROJET DES AUTRES")
    ticket = _ticket(client, entetes_consultant)
    reponse = client.patch(
        f"/tickets/{ticket['id']}", json={"project_id": autre}, headers=entetes_consultant
    )
    assert reponse.status_code == 403


def test_admin_rattache_a_n_importe_quel_projet(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    projet = _creer_projet(client, entetes_admin, "N'IMPORTE LEQUEL")
    reponse = client.post(
        "/tickets", json={"title": "X", "project_id": projet}, headers=entetes_admin
    )
    assert reponse.status_code == 200


def test_auteur_supprime_son_ticket(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    sien = _ticket(client, entetes_consultant)
    assert client.delete(f"/tickets/{sien['id']}", headers=entetes_consultant).status_code == 200


def test_assigne_ne_supprime_pas_le_ticket_d_un_autre(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    """Un ticket qu'on vous confie n'est pas à vous."""
    confie = _ticket(client, entetes_admin, assignee_id=consultant_id)
    reponse = client.delete(f"/tickets/{confie['id']}", headers=entetes_consultant)
    assert reponse.status_code == 403


def test_admin_supprime_n_importe_quel_ticket(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
) -> None:
    autrui = _ticket(client, entetes_consultant)
    assert client.delete(f"/tickets/{autrui['id']}", headers=entetes_admin).status_code == 200


def test_le_detail_dit_si_on_peut_supprimer(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    confie = _ticket(client, entetes_admin, assignee_id=consultant_id)
    vu_par_l_assigne = client.get(f"/tickets/{confie['id']}", headers=entetes_consultant).json()
    assert vu_par_l_assigne["can_delete"] is False

    vu_par_l_admin = client.get(f"/tickets/{confie['id']}", headers=entetes_admin).json()
    assert vu_par_l_admin["can_delete"] is True


# --- Suppression d'utilisateurs --------------------------------------------


def test_consultant_ne_supprime_pas_de_compte(
    client: TestClient, entetes_consultant: dict[str, str], admin_id: int
) -> None:
    assert client.delete(f"/users/{admin_id}", headers=entetes_consultant).status_code == 403


def test_compte_vierge_est_supprime(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    nouveau = client.post(
        "/users/",
        json={"full_name": "Test", "username": "test", "email": "t@t.co"},
        headers=entetes_admin,
    ).json()
    reponse = client.delete(f"/users/{nouveau['id']}", headers=entetes_admin)
    assert reponse.status_code == 200
    assert reponse.json()["status"] == "deleted"
    assert nouveau["id"] not in {u["id"] for u in client.get("/users/", headers=entetes_admin).json()}


def test_compte_avec_saisies_est_desactive(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    """L'historique de paie ne s'efface pas : on désactive."""
    client.post(
        "/cra/batch",
        json=[{"date": "2026-06-01", "duration_factor": 1.0, "activity_type": "Interne",
               "user_id": consultant_id}],
        headers=entetes_consultant,
    )
    reponse = client.delete(f"/users/{consultant_id}", headers=entetes_admin)
    assert reponse.status_code == 200
    assert reponse.json()["status"] == "deactivated"

    # Plus dans la liste, plus de connexion, mais les lignes sont toujours là.
    assert consultant_id not in {u["id"] for u in client.get("/users/", headers=entetes_admin).json()}
    from conftest import MOT_DE_PASSE
    assert (
        client.post("/auth/login", json={"username": "consultant", "password": MOT_DE_PASSE}).status_code
        == 401
    )
    assert len(client.get(f"/cra/{consultant_id}/2026/6", headers=entetes_admin).json()) == 1


def test_jeton_d_un_compte_desactive_est_refuse(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    client.post(
        "/cra/batch",
        json=[{"date": "2026-06-01", "duration_factor": 1.0, "activity_type": "Interne",
               "user_id": consultant_id}],
        headers=entetes_consultant,
    )
    client.delete(f"/users/{consultant_id}", headers=entetes_admin)
    assert client.get("/projects/", headers=entetes_consultant).status_code == 401


def test_admin_ne_se_supprime_pas_lui_meme(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    assert client.delete(f"/users/{admin_id}", headers=entetes_admin).status_code == 422


def test_dernier_admin_est_protege(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    autre = client.post(
        "/users/",
        json={"full_name": "Second", "username": "second", "email": "s@t.co", "is_admin": True},
        headers=entetes_admin,
    ).json()
    # Le second admin peut partir : il en reste un.
    assert client.delete(f"/users/{autre['id']}", headers=entetes_admin).status_code == 200


def test_tickets_survivent_a_la_suppression_de_leur_auteur(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    ticket = _ticket(client, entetes_consultant, assignee_id=consultant_id)
    assert client.delete(f"/users/{consultant_id}", headers=entetes_admin).json()["status"] == "deleted"
    detail = client.get(f"/tickets/{ticket['id']}", headers=entetes_admin).json()
    assert detail["assignee_id"] is None
    assert detail["reporter_id"] is None
