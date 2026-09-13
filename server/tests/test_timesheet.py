"""Saisie du CRA : capacité, absences, affectations, copie de semaine, clôture.

Couvre l'étape 4 de SPEC-CRA.md §13 et les cinq critères « Temps » du §12.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from holidays import holidays_for_year
from main import LeaveType, engine
from seed_holidays import seed as seed_holidays
from seed_leave_types import seed as seed_leave_types
from timesheet import (
    TimesheetError,
    check_capacity,
    check_quantities,
    missing_working_days,
    period_bounds,
    period_of,
)

FERIES_2026 = set(holidays_for_year(2026))


# --- Règles pures ----------------------------------------------------------


def test_periode_mal_formee() -> None:
    with pytest.raises(TimesheetError):
        period_bounds("septembre 2026")


def test_bornes_de_periode() -> None:
    assert period_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_of(date(2026, 9, 7)) == "2026-09"


def test_quantite_hors_pas_de_demi_journee() -> None:
    with pytest.raises(TimesheetError):
        check_quantities([(date(2026, 6, 1), 0.3)])


def test_quantite_negative() -> None:
    with pytest.raises(TimesheetError):
        check_quantities([(date(2026, 6, 1), -1.0)])


def test_deux_demi_journees_le_meme_jour_sont_valides() -> None:
    check_capacity([(date(2026, 6, 1), 0.5), (date(2026, 6, 1), 0.5)], {})


def test_trois_demi_journees_le_meme_jour_sont_refusees() -> None:
    with pytest.raises(TimesheetError):
        check_capacity(
            [(date(2026, 6, 1), 0.5), (date(2026, 6, 1), 0.5), (date(2026, 6, 1), 0.5)],
            {},
        )


def test_demi_journee_de_conge_laisse_une_demi_journee() -> None:
    jour = date(2026, 6, 1)
    check_capacity([(jour, 0.5)], {jour: 0.5})
    with pytest.raises(TimesheetError):
        check_capacity([(jour, 1.0)], {jour: 0.5})


def test_jours_ouvres_manquants() -> None:
    trous = missing_working_days("2026-05", [], {}, FERIES_2026)
    assert len(trous) == 17  # 21 jours de semaine moins 4 fériés
    assert date(2026, 5, 25) not in trous  # lundi de Pentecôte


def test_un_jour_couvert_par_une_absence_n_est_pas_un_trou() -> None:
    trous = missing_working_days("2026-05", [], {date(2026, 5, 4): 1.0}, FERIES_2026)
    assert date(2026, 5, 4) not in trous
    assert len(trous) == 16


# --- Fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def referentiel() -> None:
    seed_holidays(2026, 2026)
    seed_leave_types()


@pytest.fixture
def cp_id() -> int:
    with Session(engine) as session:
        return session.exec(select(LeaveType).where(LeaveType.code == "CP")).first().id


def _projet(client: TestClient, entetes: dict[str, str], **champs) -> dict:
    corps = {"name": "MISSION-A", "category": "Mission"} | champs
    reponse = client.post("/projects/", json=corps, headers=entetes)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _affecter(
    client: TestClient, entetes: dict[str, str], user_id: int, project_id: int
) -> None:
    client.post(
        f"/users/{user_id}/projects",
        json={"project_ids": [project_id]},
        headers=entetes,
    )


def _ligne(jour: str, user_id: int, quantite: float = 1.0, project_id=None) -> dict:
    return {
        "date": jour,
        "duration_factor": quantite,
        "activity_type": "Mission",
        "user_id": user_id,
        "project_id": project_id,
    }


def _enregistrer(client: TestClient, entetes: dict[str, str], lignes: list[dict]):
    return client.post("/cra/batch", json=lignes, headers=entetes)


# --- Capacité journalière --------------------------------------------------


def test_deux_demi_journees_sur_deux_projets(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    """§12 — deux demi-journées le même jour passent, une troisième non."""
    a = _projet(client, entetes_admin, name="MISSION-A")
    b = _projet(client, entetes_admin, name="MISSION-B")
    reponse = _enregistrer(
        client,
        entetes_admin,
        [
            _ligne("2026-06-01", admin_id, 0.5, a["id"]),
            _ligne("2026-06-01", admin_id, 0.5, b["id"]),
        ],
    )
    assert reponse.status_code == 200


def test_troisieme_demi_journee_refusee(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    a = _projet(client, entetes_admin, name="MISSION-A")
    b = _projet(client, entetes_admin, name="MISSION-B")
    c = _projet(client, entetes_admin, name="MISSION-C")
    reponse = _enregistrer(
        client,
        entetes_admin,
        [
            _ligne("2026-06-01", admin_id, 0.5, a["id"]),
            _ligne("2026-06-01", admin_id, 0.5, b["id"]),
            _ligne("2026-06-01", admin_id, 0.5, c["id"]),
        ],
    )
    assert reponse.status_code == 422


def test_quantite_hors_pas_refusee_par_l_api(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    reponse = _enregistrer(
        client, entetes_admin, [_ligne("2026-06-01", admin_id, 0.3)]
    )
    assert reponse.status_code == 422


def test_lignes_de_mois_differents_refusees(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    """L'enregistrement remplace un mois : mélanger deux mois en effacerait un."""
    reponse = _enregistrer(
        client,
        entetes_admin,
        [_ligne("2026-06-01", admin_id), _ligne("2026-07-01", admin_id)],
    )
    assert reponse.status_code == 422


# --- Absences approuvées ---------------------------------------------------


def _poser_conge_approuve(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes: dict[str, str],
    cp_id: int,
    debut: str,
    fin: str,
    **extra,
) -> None:
    demande = client.post(
        "/leaves",
        json={"leave_type_id": cp_id, "start_date": debut, "end_date": fin, **extra},
        headers=entetes,
    ).json()
    client.post(
        f"/leaves/{demande['id']}/decide", json={"approve": True}, headers=entetes_admin
    )


def test_jour_de_conge_bloque_la_saisie(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    """§12 — un jour de congé approuvé est couvert, on n'y saisit rien de plus."""
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    _poser_conge_approuve(
        client, entetes_admin, entetes_consultant, cp_id, "2026-06-01", "2026-06-01"
    )

    reponse = _enregistrer(
        client,
        entetes_consultant,
        [_ligne("2026-06-01", consultant_id, 1.0, projet["id"])],
    )
    assert reponse.status_code == 422
    assert "absence approuvée" in reponse.json()["detail"]


def test_demi_journee_de_conge_laisse_saisir_l_autre_moitie(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    _poser_conge_approuve(
        client,
        entetes_admin,
        entetes_consultant,
        cp_id,
        "2026-06-01",
        "2026-06-01",
        start_half="am",
        end_half="am",
    )

    reponse = _enregistrer(
        client,
        entetes_consultant,
        [_ligne("2026-06-01", consultant_id, 0.5, projet["id"])],
    )
    assert reponse.status_code == 200


def test_conge_en_attente_ne_bloque_pas(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    client.post(
        "/leaves",
        json={
            "leave_type_id": cp_id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
        },
        headers=entetes_consultant,
    )
    reponse = _enregistrer(
        client,
        entetes_consultant,
        [_ligne("2026-06-01", consultant_id, 1.0, projet["id"])],
    )
    assert reponse.status_code == 200


# --- Affectations ----------------------------------------------------------


def test_consultant_n_impute_pas_sur_un_projet_non_affecte(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    """§12 — imputer sur une mission où l'on n'est pas affecté est refusé."""
    projet = _projet(client, entetes_admin)
    reponse = _enregistrer(
        client,
        entetes_consultant,
        [_ligne("2026-06-01", consultant_id, 1.0, projet["id"])],
    )
    assert reponse.status_code == 422
    assert "pas affecte" in reponse.json()["detail"]


def test_admin_impute_partout(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    projet = _projet(client, entetes_admin)
    reponse = _enregistrer(
        client, entetes_admin, [_ligne("2026-06-01", admin_id, 1.0, projet["id"])]
    )
    assert reponse.status_code == 200


def test_saisie_hors_fenetre_d_affectation(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    client.put(
        "/assignments",
        json={
            "user_id": consultant_id,
            "project_id": projet["id"],
            "start_date": "2026-07-01",
        },
        headers=entetes_admin,
    )
    reponse = _enregistrer(
        client,
        entetes_consultant,
        [_ligne("2026-06-01", consultant_id, 1.0, projet["id"])],
    )
    assert reponse.status_code == 422
    assert "precede le debut" in reponse.json()["detail"]


# --- Clôture ---------------------------------------------------------------


def _remplir_le_mois(
    client: TestClient,
    entetes: dict[str, str],
    user_id: int,
    project_id: int,
    period: str = "2026-06",
) -> None:
    debut, fin = period_bounds(period)
    lignes = []
    jour = debut
    while jour <= fin:
        if jour.weekday() < 5 and jour not in FERIES_2026:
            lignes.append(_ligne(str(jour), user_id, 1.0, project_id))
        jour = date.fromordinal(jour.toordinal() + 1)
    assert _enregistrer(client, entetes, lignes).status_code == 200


def test_cloture_refusee_si_le_mois_a_des_trous(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    projet = _projet(client, entetes_admin)
    _enregistrer(
        client, entetes_admin, [_ligne("2026-06-01", admin_id, 1.0, projet["id"])]
    )
    reponse = client.post(
        "/time/close", json={"period": "2026-06"}, headers=entetes_admin
    )
    assert reponse.status_code == 409
    assert reponse.json()["detail"]["missing_days"]


def test_cloture_puis_ecriture_refusee(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    """§12 — après clôture, toute écriture renvoie une erreur explicite."""
    projet = _projet(client, entetes_admin)
    _remplir_le_mois(client, entetes_admin, admin_id, projet["id"])

    assert (
        client.post(
            "/time/close", json={"period": "2026-06"}, headers=entetes_admin
        ).status_code
        == 200
    )

    reponse = _enregistrer(
        client, entetes_admin, [_ligne("2026-06-01", admin_id, 1.0, projet["id"])]
    )
    assert reponse.status_code == 409
    assert "cloturee" in reponse.json()["detail"]


def test_seul_l_admin_rouvre(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    """§12 — seul l'admin peut rouvrir une période."""
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    _remplir_le_mois(client, entetes_consultant, consultant_id, projet["id"])
    client.post("/time/close", json={"period": "2026-06"}, headers=entetes_consultant)

    refus = client.post(
        "/time/reopen",
        json={"period": "2026-06", "user_id": consultant_id},
        headers=entetes_consultant,
    )
    assert refus.status_code == 403

    ok = client.post(
        "/time/reopen",
        json={"period": "2026-06", "user_id": consultant_id},
        headers=entetes_admin,
    )
    assert ok.status_code == 200

    # La saisie repasse.
    assert (
        _enregistrer(
            client,
            entetes_consultant,
            [_ligne("2026-06-01", consultant_id, 1.0, projet["id"])],
        ).status_code
        == 200
    )


def test_consultant_ne_cloture_pas_pour_un_autre(
    client: TestClient, entetes_consultant: dict[str, str], admin_id: int
) -> None:
    reponse = client.post(
        "/time/close",
        json={"period": "2026-06", "user_id": admin_id},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 403


# --- Vue mensuelle ---------------------------------------------------------


def test_vue_mensuelle_agrege_tout(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    _enregistrer(
        client,
        entetes_consultant,
        [_ligne("2026-06-02", consultant_id, 1.0, projet["id"])],
    )
    _poser_conge_approuve(
        client, entetes_admin, entetes_consultant, cp_id, "2026-06-03", "2026-06-03"
    )

    vue = client.get("/time?period=2026-06", headers=entetes_consultant).json()
    assert vue["closed"] is False
    assert len(vue["entries"]) == 1
    assert vue["leave_load"] == {"2026-06-03": 1.0}
    assert "2026-06-01" in vue["missing_days"]
    assert "2026-06-02" not in vue["missing_days"]
    assert "2026-06-03" not in vue["missing_days"]


# --- Copie de semaine ------------------------------------------------------


def test_copie_de_semaine(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    # Semaine du lundi 1er au vendredi 5 juin 2026.
    lignes = [
        _ligne(f"2026-06-0{j}", consultant_id, 1.0, projet["id"]) for j in range(1, 6)
    ]
    _enregistrer(client, entetes_consultant, lignes)

    reponse = client.post(
        "/time/copy-week",
        json={"target_week_start": "2026-06-08"},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 200
    assert reponse.json() == {"created": 5, "skipped": 0}

    vue = client.get("/time?period=2026-06", headers=entetes_consultant).json()
    assert len(vue["entries"]) == 10


def test_copie_de_semaine_ignore_les_jours_d_absence(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    cp_id: int,
    consultant_id: int,
) -> None:
    """§12 — « Copier la semaine précédente » ignore les jours d'absence."""
    projet = _projet(client, entetes_admin)
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    lignes = [
        _ligne(f"2026-06-0{j}", consultant_id, 1.0, projet["id"]) for j in range(1, 6)
    ]
    _enregistrer(client, entetes_consultant, lignes)
    _poser_conge_approuve(
        client, entetes_admin, entetes_consultant, cp_id, "2026-06-09", "2026-06-10"
    )

    reponse = client.post(
        "/time/copy-week",
        json={"target_week_start": "2026-06-08"},
        headers=entetes_consultant,
    )
    assert reponse.json() == {"created": 3, "skipped": 2}


def test_copie_de_semaine_ignore_une_mission_terminee(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    projet = _projet(client, entetes_admin, end_date="2026-06-05")
    _affecter(client, entetes_admin, consultant_id, projet["id"])
    lignes = [
        _ligne(f"2026-06-0{j}", consultant_id, 1.0, projet["id"]) for j in range(1, 6)
    ]
    _enregistrer(client, entetes_consultant, lignes)

    reponse = client.post(
        "/time/copy-week",
        json={"target_week_start": "2026-06-08"},
        headers=entetes_consultant,
    )
    assert reponse.json() == {"created": 0, "skipped": 5}


def test_copie_de_semaine_refusee_sur_periode_cloturee(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    projet = _projet(client, entetes_admin)
    _remplir_le_mois(client, entetes_admin, admin_id, projet["id"])
    client.post("/time/close", json={"period": "2026-06"}, headers=entetes_admin)

    reponse = client.post(
        "/time/copy-week",
        json={"target_week_start": "2026-06-08"},
        headers=entetes_admin,
    )
    assert reponse.status_code == 409
