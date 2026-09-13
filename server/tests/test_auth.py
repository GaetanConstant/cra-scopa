"""Authentification et contrôle d'accès des routes.

Couvre les critères d'accès du §4 et du §12 de SPEC-CRA.md.
"""

from fastapi.testclient import TestClient

from conftest import MOT_DE_PASSE


# --- Connexion -------------------------------------------------------------


def test_login_valide_delivre_un_jeton(client: TestClient, admin_id: int) -> None:
    reponse = client.post(
        "/auth/login", json={"username": "admin", "password": MOT_DE_PASSE}
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["access_token"]
    assert corps["token_type"] == "bearer"
    assert corps["is_admin"] is True


def test_message_identique_sur_compte_inconnu_et_mot_de_passe_faux(
    client: TestClient, admin_id: int
) -> None:
    """Un message différencié confirmerait l'existence d'un compte."""
    mauvais_mdp = client.post(
        "/auth/login", json={"username": "admin", "password": "faux"}
    )
    inconnu = client.post(
        "/auth/login", json={"username": "fantome", "password": MOT_DE_PASSE}
    )
    assert mauvais_mdp.status_code == inconnu.status_code == 401
    assert mauvais_mdp.json()["detail"] == inconnu.json()["detail"]


# --- Protection des routes -------------------------------------------------


def test_route_sans_jeton_est_refusee(client: TestClient) -> None:
    assert client.get("/projects/").status_code == 401


def test_jeton_invalide_est_refuse(client: TestClient) -> None:
    reponse = client.get("/projects/", headers={"Authorization": "Bearer nawak"})
    assert reponse.status_code == 401


def test_consultant_peut_lire_le_referentiel(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    assert client.get("/projects/", headers=entetes_consultant).status_code == 200


# --- Réservé à l'admin -----------------------------------------------------


def test_consultant_ne_cree_pas_de_projet(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.post(
        "/projects/",
        json={"name": "MISSION-X", "category": "Mission"},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


def test_admin_cree_un_projet(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    reponse = client.post(
        "/projects/",
        json={"name": "MISSION-X", "category": "Mission"},
        headers=entetes_admin,
    )
    assert reponse.status_code == 200


def test_consultant_ne_supprime_pas_de_projet(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
) -> None:
    """§12 — « Un consultant reçoit un 403 sur la suppression »."""
    projet = client.post(
        "/projects/",
        json={"name": "MISSION-X", "category": "Mission"},
        headers=entetes_admin,
    ).json()
    reponse = client.delete(f"/projects/{projet['id']}", headers=entetes_consultant)
    assert reponse.status_code == 403


def test_consultant_ne_cree_pas_de_compte(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.post(
        "/users/",
        json={"full_name": "Intrus", "username": "intrus", "email": "i@test.co"},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


# --- Saisie du CRA ---------------------------------------------------------


def _saisie(user_id: int) -> list[dict[str, object]]:
    return [
        {
            "date": "2026-09-01",
            "duration_factor": 1.0,
            "activity_type": "Mission",
            "user_id": user_id,
        }
    ]


def test_consultant_ne_saisit_pas_le_cra_d_autrui(
    client: TestClient, entetes_consultant: dict[str, str], admin_id: int
) -> None:
    reponse = client.post(
        "/cra/batch", json=_saisie(admin_id), headers=entetes_consultant
    )
    assert reponse.status_code == 403


def test_consultant_saisit_son_propre_cra(
    client: TestClient, entetes_consultant: dict[str, str], consultant_id: int
) -> None:
    reponse = client.post(
        "/cra/batch", json=_saisie(consultant_id), headers=entetes_consultant
    )
    assert reponse.status_code == 200


def test_admin_saisit_pour_un_consultant(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    reponse = client.post(
        "/cra/batch", json=_saisie(consultant_id), headers=entetes_admin
    )
    assert reponse.status_code == 200


# --- Mot de passe ----------------------------------------------------------


def test_changement_de_mot_de_passe_ne_vise_que_soi(
    client: TestClient,
    entetes_consultant: dict[str, str],
    consultant_id: int,
    admin_id: int,
) -> None:
    """Le `user_id` du corps est ignoré : seul le jeton désigne la cible."""
    reponse = client.post(
        "/users/password",
        json={
            "user_id": admin_id,  # tentative de viser un autre compte
            "old_password": MOT_DE_PASSE,
            "new_password": "nouveau-mot-de-passe",
        },
        headers=entetes_consultant,
    )
    assert reponse.status_code == 200

    # L'admin garde son mot de passe, c'est bien le consultant qui a change.
    assert (
        client.post(
            "/auth/login", json={"username": "admin", "password": MOT_DE_PASSE}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/login",
            json={"username": "consultant", "password": "nouveau-mot-de-passe"},
        ).status_code
        == 200
    )
