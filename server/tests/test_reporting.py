"""Mesure de l'activité : jours disponibles, saisis, taux d'occupation, export.

Version resserrée de l'étape 8 : ni chiffre d'affaires ni prévisionnel, qui
dépendent du TJM et de `billable`, encore à trancher.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from holidays import holidays_for_year
from main import LeaveType, engine
from reporting import occupancy, summarise_user, to_csv, working_days_count
from seed_holidays import seed as seed_holidays
from seed_leave_types import seed as seed_leave_types

FERIES_2026 = set(holidays_for_year(2026))


# --- Calculs purs ----------------------------------------------------------


def test_jours_ouvres_du_mois() -> None:
    """Mai 2026 : 21 jours de semaine, moins 4 fériés."""
    assert working_days_count(date(2026, 5, 1), date(2026, 5, 31), FERIES_2026) == 17


def test_jours_ouvres_hors_ferie() -> None:
    assert working_days_count(date(2026, 6, 1), date(2026, 6, 30), FERIES_2026) == 22


def test_taux_d_occupation() -> None:
    assert occupancy(15.0, 20.0) == 0.75
    assert occupancy(0.0, 20.0) == 0.0


def test_taux_indefini_sans_jour_disponible() -> None:
    """Un mois entièrement en congé : 0 % ferait croire à un oubli de saisie."""
    assert occupancy(0.0, 0.0) is None


def test_resume_d_un_consultant() -> None:
    resume = summarise_user({"HOMESERVE": 12.0, "Interne": 3.0}, working_days=20, leave_days=2.0)
    assert resume["available_days"] == 18.0
    assert resume["entered_days"] == 15.0
    assert resume["missing_days"] == 3.0
    assert resume["occupancy"] == round(15 / 18, 4)


def test_jours_manquants_jamais_negatifs() -> None:
    """Plusieurs missions sur une journée peuvent dépasser les jours disponibles."""
    resume = summarise_user({"A": 25.0}, working_days=20, leave_days=0.0)
    assert resume["missing_days"] == 0.0
    assert resume["occupancy"] > 1


def test_csv_en_format_francais() -> None:
    csv = to_csv(
        [{"nom": "A. Patou", "jours": 12.5, "taux": None}], ("nom", "jours", "taux")
    )
    lignes = csv.strip().split("\n")
    assert lignes[0] == "nom;jours;taux"
    assert lignes[1] == "A. Patou;12,50;"


def test_csv_echappe_le_separateur() -> None:
    csv = to_csv([{"nom": "Dupont; Martin"}], ("nom",))
    assert '"Dupont; Martin"' in csv


# --- API -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def referentiel() -> None:
    seed_holidays(2026, 2026)
    seed_leave_types()


@pytest.fixture
def cp_id() -> int:
    with Session(engine) as session:
        return session.exec(select(LeaveType).where(LeaveType.code == "CP")).first().id


def _projet(client: TestClient, entetes: dict[str, str], nom: str) -> int:
    return client.post(
        "/projects/", json={"name": nom, "category": "Mission"}, headers=entetes
    ).json()["id"]


def _saisir(
    client: TestClient,
    entetes: dict[str, str],
    user_id: int,
    project_id: int,
    jours: list[str],
) -> None:
    lignes = [
        {
            "date": j,
            "duration_factor": 1.0,
            "activity_type": "Mission",
            "user_id": user_id,
            "project_id": project_id,
        }
        for j in jours
    ]
    assert client.post("/cra/batch", json=lignes, headers=entetes).status_code == 200


def test_activite_agrege_par_consultant(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    projet = _projet(client, entetes_admin, "HOMESERVE")
    _saisir(client, entetes_admin, admin_id, projet, ["2026-06-01", "2026-06-02"])

    reponse = client.get(
        "/reporting/activity?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_admin,
    )
    assert reponse.status_code == 200

    ligne = next(l for l in reponse.json()["rows"] if l["user_id"] == admin_id)
    assert ligne["working_days"] == 22
    assert ligne["entered_days"] == 2.0
    assert ligne["missing_days"] == 20.0
    assert ligne["by_project"] == [{"label": "HOMESERVE", "days": 2.0}]


def test_absence_approuvee_reduit_les_jours_disponibles(
    client: TestClient,
    entetes_admin: dict[str, str],
    admin_id: int,
    cp_id: int,
) -> None:
    demande = client.post(
        "/leaves",
        json={
            "leave_type_id": cp_id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
        },
        headers=entetes_admin,
    ).json()
    client.post(
        f"/leaves/{demande['id']}/decide", json={"approve": True}, headers=entetes_admin
    )

    ligne = next(
        l
        for l in client.get(
            "/reporting/activity?from_date=2026-06-01&to_date=2026-06-30",
            headers=entetes_admin,
        ).json()["rows"]
        if l["user_id"] == admin_id
    )
    assert ligne["leave_days"] == 5.0
    assert ligne["available_days"] == 17.0


def test_activite_sans_saisie(
    client: TestClient, entetes_admin: dict[str, str], consultant_id: int
) -> None:
    ligne = next(
        l
        for l in client.get(
            "/reporting/activity?from_date=2026-06-01&to_date=2026-06-30",
            headers=entetes_admin,
        ).json()["rows"]
        if l["user_id"] == consultant_id
    )
    assert ligne["entered_days"] == 0.0
    assert ligne["occupancy"] == 0.0
    assert ligne["by_project"] == []


def test_periode_inversee_refusee(
    client: TestClient, entetes_admin: dict[str, str]
) -> None:
    reponse = client.get(
        "/reporting/activity?from_date=2026-06-30&to_date=2026-06-01",
        headers=entetes_admin,
    )
    assert reponse.status_code == 422


def test_activite_exige_un_jeton(client: TestClient) -> None:
    reponse = client.get("/reporting/activity?from_date=2026-06-01&to_date=2026-06-30")
    assert reponse.status_code == 401


def test_export_csv(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int
) -> None:
    projet = _projet(client, entetes_admin, "HOMESERVE")
    _saisir(client, entetes_admin, admin_id, projet, ["2026-06-01"])

    reponse = client.get(
        "/reporting/activity/export?from_date=2026-06-01&to_date=2026-06-30",
        headers=entetes_admin,
    )
    assert reponse.status_code == 200
    assert "text/csv" in reponse.headers["content-type"]
    assert "attachment" in reponse.headers["content-disposition"]

    lignes = reponse.text.strip().split("\n")
    assert lignes[0].startswith("collaborateur;jours_ouvres")
    assert any("Admin" in l for l in lignes[1:])


def test_colonnes_numeriques_toujours_decimales() -> None:
    """Sans saisie, sum() renvoie un entier : la colonne mélangeait 0 et 22,00."""
    vide = summarise_user({}, working_days=20, leave_days=0)
    assert isinstance(vide["entered_days"], float)
    assert isinstance(vide["leave_days"], float)
    assert isinstance(vide["missing_days"], float)
    assert to_csv([vide], ("entered_days",)).strip().split("\n")[1] == "0,00"
