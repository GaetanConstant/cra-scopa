"""Référentiel : clients, missions facturables, affectations et TJM.

Couvre l'étape 1 de SPEC-CRA.md §13 et la règle du §4 sur la visibilité
des taux journaliers.
"""

from fastapi.testclient import TestClient


def _projet(client: TestClient, entetes: dict[str, str], **champs) -> dict:
    corps = {"name": "MISSION-A", "category": "Mission"} | champs
    reponse = client.post("/projects/", json=corps, headers=entetes)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


# --- Clients ---------------------------------------------------------------


def test_admin_cree_un_client(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    reponse = client.post(
        "/clients/",
        json={"name": "HOMESERVE", "siren": "123456789"},
        headers=entetes_admin,
    )
    assert reponse.status_code == 200
    assert reponse.json()["is_active"] is True


def test_consultant_ne_cree_pas_de_client(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.post(
        "/clients/", json={"name": "HOMESERVE"}, headers=entetes_consultant
    )
    assert reponse.status_code == 403


def test_client_en_double_est_refuse(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    client.post("/clients/", json={"name": "HOMESERVE"}, headers=entetes_admin)
    reponse = client.post(
        "/clients/", json={"name": "HOMESERVE"}, headers=entetes_admin
    )
    assert reponse.status_code == 400


def test_consultant_lit_les_clients(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
) -> None:
    client.post("/clients/", json={"name": "HOMESERVE"}, headers=entetes_admin)
    reponse = client.get("/clients/", headers=entetes_consultant)
    assert reponse.status_code == 200
    assert [c["name"] for c in reponse.json()] == ["HOMESERVE"]


# --- Missions --------------------------------------------------------------


def test_projet_porte_les_champs_de_pilotage(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    projet = _projet(
        client,
        entetes_admin,
        code="HS-DI",
        billable=True,
        sold_days=40.0,
        start_date="2026-01-05",
        end_date="2026-06-30",
        status="active",
    )
    assert projet["sold_days"] == 40.0
    assert projet["code"] == "HS-DI"
    assert projet["billable"] is True


def test_statut_invalide_est_refuse(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    reponse = client.post(
        "/projects/",
        json={"name": "MISSION-B", "category": "Mission", "status": "en_cours"},
        headers=entetes_admin,
    )
    assert reponse.status_code == 422


def test_mise_a_jour_conserve_les_champs_de_pilotage(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    projet = _projet(client, entetes_admin, sold_days=10.0)
    projet["sold_days"] = 25.0
    projet["status"] = "paused"
    reponse = client.put(
        f"/projects/{projet['id']}", json=projet, headers=entetes_admin
    )
    assert reponse.status_code == 200
    assert reponse.json()["sold_days"] == 25.0
    assert reponse.json()["status"] == "paused"


# --- Affectations ----------------------------------------------------------


def _affecter(
    client: TestClient, entetes: dict[str, str], user_id: int, project_id: int
) -> None:
    reponse = client.post(
        f"/users/{user_id}/projects",
        json={"project_ids": [project_id]},
        headers=entetes,
    )
    assert reponse.status_code == 200, reponse.text


def test_tjm_survit_a_un_reenregistrement_des_affectations(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    """Le piège : réécrire la liste des projets effaçait le TJM saisi."""
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])

    client.put(
        "/assignments",
        json={
            "user_id": consultant_id,
            "project_id": projet["id"],
            "daily_rate": 650.0,
        },
        headers=entetes_admin,
    )
    # L'admin réenregistre la même liste depuis l'écran Collaborateurs.
    _affecter(client, entetes_admin, consultant_id, projet["id"])

    affectations = client.get(
        f"/projects/{projet['id']}/assignments", headers=entetes_admin
    ).json()
    assert affectations[0]["daily_rate"] == 650.0


def test_tjm_masque_aux_consultants(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    """§4 — la transparence porte sur les temps, pas sur les taux."""
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    client.put(
        "/assignments",
        json={
            "user_id": consultant_id,
            "project_id": projet["id"],
            "daily_rate": 650.0,
        },
        headers=entetes_admin,
    )

    vue_admin = client.get(
        f"/projects/{projet['id']}/assignments", headers=entetes_admin
    ).json()
    vue_consultant = client.get(
        f"/projects/{projet['id']}/assignments", headers=entetes_consultant
    ).json()

    assert "daily_rate" in vue_admin[0]
    assert "daily_rate" not in vue_consultant[0]


def test_consultant_ne_fixe_pas_un_tjm(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    reponse = client.put(
        "/assignments",
        json={
            "user_id": consultant_id,
            "project_id": projet["id"],
            "daily_rate": 1.0,
        },
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


def test_tjm_sur_une_affectation_absente(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    projet = _projet(client, entetes_admin)
    reponse = client.put(
        "/assignments",
        json={"user_id": consultant_id, "project_id": projet["id"], "daily_rate": 500.0},
        headers=entetes_admin,
    )
    assert reponse.status_code == 404


def test_fenetre_de_dates_incoherente_est_refusee(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    reponse = client.put(
        "/assignments",
        json={
            "user_id": consultant_id,
            "project_id": projet["id"],
            "start_date": "2026-06-01",
            "end_date": "2026-01-01",
        },
        headers=entetes_admin,
    )
    assert reponse.status_code == 422


def test_desaffectation_supprime_le_lien(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    client.post(
        f"/users/{consultant_id}/projects", json={"project_ids": []}, headers=entetes_admin
    )
    affectations = client.get(
        f"/projects/{projet['id']}/assignments", headers=entetes_admin
    ).json()
    assert affectations == []


def test_renommer_un_projet_ne_perd_pas_le_pilotage(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    """L'écran Projets n'envoie que le nom et la catégorie."""
    projet = _projet(client, entetes_admin, sold_days=40.0, code="HS-DI", status="paused")
    reponse = client.put(
        f"/projects/{projet['id']}",
        json={"name": "MISSION-A RENOMMEE", "category": "Mission"},
        headers=entetes_admin,
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["name"] == "MISSION-A RENOMMEE"
    assert corps["sold_days"] == 40.0
    assert corps["code"] == "HS-DI"
    assert corps["status"] == "paused"
