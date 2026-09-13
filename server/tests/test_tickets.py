"""Tickets : positions du kanban, déplacements, étiquettes, commentaires, journal.

Couvre l'étape 6 de SPEC-CRA.md §13 et les trois critères « Tickets » du §12.
"""

import pytest
from fastapi.testclient import TestClient

from positions import (
    GAP,
    MIN_GAP,
    needs_rebalance,
    position_between,
    rebalance,
    sorted_positions,
)


# --- Positions, sans base --------------------------------------------------


def test_colonne_vide() -> None:
    assert position_between(None, None) == 0.0


def test_en_tete_de_colonne() -> None:
    assert position_between(None, 1000.0) == 1000.0 - GAP


def test_en_queue_de_colonne() -> None:
    assert position_between(3000.0, None) == 3000.0 + GAP


def test_entre_deux_cartes() -> None:
    assert position_between(1000.0, 2000.0) == 1500.0


def test_voisines_dans_le_desordre() -> None:
    with pytest.raises(ValueError):
        position_between(2000.0, 1000.0)


def test_reequilibrage_signale_avant_la_perte_de_precision() -> None:
    assert needs_rebalance(1.0, 1.0 + MIN_GAP / 2) is True
    assert needs_rebalance(1000.0, 2000.0) is False
    assert needs_rebalance(None, 2000.0) is False


def test_insertions_repetees_finissent_par_reclamer_un_reequilibrage() -> None:
    """Le scénario qui casse : toujours déposer au même endroit."""
    avant, apres = 0.0, GAP
    for _ in range(100):
        if needs_rebalance(avant, apres):
            break
        apres = position_between(avant, apres)
    else:
        pytest.fail("Le rééquilibrage n'a jamais été réclamé")
    assert avant < apres


def test_reequilibrage_produit_des_positions_croissantes() -> None:
    positions = rebalance(5)
    assert len(positions) == 5
    assert sorted_positions(positions)
    assert all(needs_rebalance(a, b) is False for a, b in zip(positions, positions[1:]))


# --- Aides d'API -----------------------------------------------------------


def _ticket(client: TestClient, entetes: dict[str, str], **champs) -> dict:
    corps = {"title": "Corriger le calcul du TACE"} | champs
    reponse = client.post("/tickets", json=corps, headers=entetes)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _colonne(client: TestClient, entetes: dict[str, str], statut: str) -> list[dict]:
    return client.get("/tickets/board", headers=entetes).json()[statut]


def _deplacer(
    client: TestClient, entetes: dict[str, str], ticket_id: int, **corps
) -> dict:
    reponse = client.post(f"/tickets/{ticket_id}/move", json=corps, headers=entetes)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


# --- Création --------------------------------------------------------------


def test_creation_place_en_bas_de_colonne(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    a = _ticket(client, entetes_consultant, title="A")
    b = _ticket(client, entetes_consultant, title="B")
    assert b["position"] > a["position"]

    colonne = _colonne(client, entetes_consultant, "todo")
    assert [t["title"] for t in colonne] == ["A", "B"]


def test_creation_journalisee(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    ticket = _ticket(client, entetes_consultant)
    detail = client.get(f"/tickets/{ticket['id']}", headers=entetes_consultant).json()
    assert [e["kind"] for e in detail["events"]] == ["created"]


def test_priorite_invalide(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.post(
        "/tickets", json={"title": "X", "priority": "urgentissime"}, headers=entetes_consultant
    )
    assert reponse.status_code == 422


def test_ticket_sans_jeton(client: TestClient) -> None:
    assert client.post("/tickets", json={"title": "X"}).status_code == 401


# --- Déplacements ----------------------------------------------------------


def test_deplacement_entre_colonnes_persiste(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    """§12 — le déplacement persiste après rechargement."""
    ticket = _ticket(client, entetes_consultant)
    _deplacer(client, entetes_consultant, ticket["id"], status="in_progress")

    board = client.get("/tickets/board", headers=entetes_consultant).json()
    assert board["todo"] == []
    assert [t["id"] for t in board["in_progress"]] == [ticket["id"]]


def test_reordonnancement_dans_une_colonne(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    """§12 — le réordonnancement persiste après rechargement."""
    a = _ticket(client, entetes_consultant, title="A")
    b = _ticket(client, entetes_consultant, title="B")
    c = _ticket(client, entetes_consultant, title="C")

    # On remonte C entre A et B.
    _deplacer(
        client,
        entetes_consultant,
        c["id"],
        status="todo",
        before_id=a["id"],
        after_id=b["id"],
    )
    assert [t["title"] for t in _colonne(client, entetes_consultant, "todo")] == [
        "A",
        "C",
        "B",
    ]


def test_deplacement_en_tete_de_colonne(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    a = _ticket(client, entetes_consultant, title="A")
    b = _ticket(client, entetes_consultant, title="B")
    _deplacer(client, entetes_consultant, b["id"], status="todo", after_id=a["id"])
    assert [t["title"] for t in _colonne(client, entetes_consultant, "todo")] == ["B", "A"]


def test_voisine_dans_une_autre_colonne_est_refusee(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    a = _ticket(client, entetes_consultant, title="A")
    b = _ticket(client, entetes_consultant, title="B")
    _deplacer(client, entetes_consultant, a["id"], status="done")

    reponse = client.post(
        f"/tickets/{b['id']}/move",
        json={"status": "todo", "after_id": a["id"]},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 422


def test_insertions_repetees_gardent_l_ordre(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    """Vingt dépôts juste avant la même carte, sans collision de position.

    C'est le scénario qui casse un kanban : le serveur relit la colonne à
    chaque fois, donc chaque carte se glisse derrière la précédente au lieu
    de recalculer la même moyenne vingt fois.
    """
    _ticket(client, entetes_consultant, title="A")
    b = _ticket(client, entetes_consultant, title="B")

    for i in range(20):
        t = _ticket(client, entetes_consultant, title=f"T{i}")
        _deplacer(client, entetes_consultant, t["id"], status="todo", after_id=b["id"])

    colonne = _colonne(client, entetes_consultant, "todo")
    attendu = ["A", *[f"T{i}" for i in range(20)], "B"]
    assert [t["title"] for t in colonne] == attendu

    positions = [t["position"] for t in colonne]
    assert sorted_positions(positions), "deux cartes partagent une position"
    assert len(set(positions)) == len(positions)


def test_retour_en_arriere_permis(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    ticket = _ticket(client, entetes_consultant)
    _deplacer(client, entetes_consultant, ticket["id"], status="done")
    revenu = _deplacer(client, entetes_consultant, ticket["id"], status="todo")
    assert revenu["status"] == "todo"


def test_cloture_horodatee_a_l_entree_dans_done(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    ticket = _ticket(client, entetes_consultant)
    fini = _deplacer(client, entetes_consultant, ticket["id"], status="done")
    assert fini["closed_at"] is not None

    ressorti = _deplacer(client, entetes_consultant, ticket["id"], status="in_progress")
    assert ressorti["closed_at"] is None


def test_changement_de_statut_journalise(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    ticket = _ticket(client, entetes_consultant)
    _deplacer(client, entetes_consultant, ticket["id"], status="in_progress")
    detail = client.get(f"/tickets/{ticket['id']}", headers=entetes_consultant).json()
    kinds = [e["kind"] for e in detail["events"]]
    assert "status_changed" in kinds
    assert "todo -> in_progress" in [e["payload"] for e in detail["events"] if e["payload"]]


# --- Colonne done bornée ---------------------------------------------------


def test_done_borne_aux_trente_derniers_jours(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    from datetime import datetime, timedelta

    from sqlmodel import Session

    from main import TkTicket, engine

    ticket = _ticket(client, entetes_consultant)
    _deplacer(client, entetes_consultant, ticket["id"], status="done")

    with Session(engine) as session:
        vieux = session.get(TkTicket, ticket["id"])
        vieux.closed_at = datetime.now() - timedelta(days=45)
        session.add(vieux)
        session.commit()

    borne = client.get("/tickets/board", headers=entetes_consultant).json()
    assert borne["done"] == []

    tout = client.get("/tickets/board?done_since_days=0", headers=entetes_consultant).json()
    assert len(tout["done"]) == 1


# --- Filtres ---------------------------------------------------------------


def test_filtres_mine_et_tag_se_combinent(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
    admin_id: int,
) -> None:
    """§12 — les filtres « mes tickets » et tag se combinent."""
    tag = client.post(
        "/tickets/tags", json={"name": "urgent-client"}, headers=entetes_consultant
    ).json()

    a_moi_tague = _ticket(
        client, entetes_consultant, title="A", assignee_id=consultant_id, tag_ids=[tag["id"]]
    )
    _ticket(client, entetes_consultant, title="B", assignee_id=consultant_id)
    _ticket(
        client, entetes_consultant, title="C", assignee_id=admin_id, tag_ids=[tag["id"]]
    )

    board = client.get(
        f"/tickets/board?mine=true&tag_id={tag['id']}", headers=entetes_consultant
    ).json()
    assert [t["id"] for t in board["todo"]] == [a_moi_tague["id"]]


def test_recherche_par_titre(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    _ticket(client, entetes_consultant, title="Corriger le TACE")
    _ticket(client, entetes_consultant, title="Écrire la doc")
    board = client.get("/tickets/board?q=TACE", headers=entetes_consultant).json()
    assert [t["title"] for t in board["todo"]] == ["Corriger le TACE"]


def test_filtre_priorite(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    _ticket(client, entetes_consultant, title="A", priority="urgent")
    _ticket(client, entetes_consultant, title="B", priority="low")
    board = client.get("/tickets/board?priority=urgent", headers=entetes_consultant).json()
    assert [t["title"] for t in board["todo"]] == ["A"]


# --- Étiquettes ------------------------------------------------------------


def test_etiquette_en_double_refusee(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    client.post("/tickets/tags", json={"name": "back"}, headers=entetes_consultant)
    reponse = client.post(
        "/tickets/tags", json={"name": "back"}, headers=entetes_consultant
    )
    assert reponse.status_code == 400


def test_etiquette_utilisee_s_archive_sans_disparaitre(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    tag = client.post(
        "/tickets/tags", json={"name": "legacy"}, headers=entetes_consultant
    ).json()
    ticket = _ticket(client, entetes_consultant, tag_ids=[tag["id"]])

    client.patch(
        f"/tickets/tags/{tag['id']}",
        json={"name": "legacy", "archived": True},
        headers=entetes_consultant,
    )

    visibles = client.get("/tickets/tags", headers=entetes_consultant).json()
    assert visibles == []
    toutes = client.get(
        "/tickets/tags?include_archived=true", headers=entetes_consultant
    ).json()
    assert [t["name"] for t in toutes] == ["legacy"]

    # Le classement du ticket survit à l'archivage.
    detail = client.get(f"/tickets/{ticket['id']}", headers=entetes_consultant).json()
    assert detail["tag_ids"] == [tag["id"]]


def test_changement_d_etiquettes_journalise(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    tag = client.post(
        "/tickets/tags", json={"name": "front"}, headers=entetes_consultant
    ).json()
    ticket = _ticket(client, entetes_consultant)
    client.patch(
        f"/tickets/{ticket['id']}",
        json={"tag_ids": [tag["id"]]},
        headers=entetes_consultant,
    )
    detail = client.get(f"/tickets/{ticket['id']}", headers=entetes_consultant).json()
    assert "tags_changed" in [e["kind"] for e in detail["events"]]


def test_etiquette_inconnue_refusee(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    reponse = client.post(
        "/tickets", json={"title": "X", "tag_ids": [9999]}, headers=entetes_consultant
    )
    assert reponse.status_code == 404


# --- Suppression -----------------------------------------------------------


def test_consultant_ne_supprime_pas_le_ticket_d_un_autre(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
) -> None:
    """Le §12 réservait la suppression à l'admin ; décision SCOPA : l'auteur
    peut supprimer le sien, mais pas celui qu'on lui a confié."""
    confie = _ticket(client, entetes_admin, assignee_id=consultant_id)
    assert client.delete(f"/tickets/{confie['id']}", headers=entetes_consultant).status_code == 403


def test_admin_supprime_et_nettoie(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
) -> None:
    tag = client.post(
        "/tickets/tags", json={"name": "jetable"}, headers=entetes_consultant
    ).json()
    ticket = _ticket(client, entetes_consultant, tag_ids=[tag["id"]])
    client.post(
        f"/tickets/{ticket['id']}/comments", json={"body": "à jeter"}, headers=entetes_consultant
    )

    assert client.delete(f"/tickets/{ticket['id']}", headers=entetes_admin).status_code == 200
    assert client.get(f"/tickets/{ticket['id']}", headers=entetes_admin).status_code == 404
    # L'étiquette, elle, survit à la suppression du ticket.
    assert client.get("/tickets/tags", headers=entetes_admin).json()[0]["name"] == "jetable"


# --- Commentaires ----------------------------------------------------------


def test_commentaire(
    client: TestClient, entetes_consultant: dict[str, str], consultant_id: int
) -> None:
    ticket = _ticket(client, entetes_consultant)
    reponse = client.post(
        f"/tickets/{ticket['id']}/comments",
        json={"body": "  Je m'en occupe  "},
        headers=entetes_consultant,
    )
    assert reponse.status_code == 200
    assert reponse.json()["body"] == "Je m'en occupe"
    assert reponse.json()["author_id"] == consultant_id

    detail = client.get(f"/tickets/{ticket['id']}", headers=entetes_consultant).json()
    assert len(detail["comments"]) == 1


def test_commentaire_vide_refuse(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    ticket = _ticket(client, entetes_consultant)
    reponse = client.post(
        f"/tickets/{ticket['id']}/comments", json={"body": "   "}, headers=entetes_consultant
    )
    assert reponse.status_code == 422


def test_done_sans_date_de_cloture_reste_visible(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    """Une carte créée directement en `done` n'a pas de date : ne pas la masquer."""
    from sqlmodel import Session

    from main import TkTicket, engine

    ticket = _ticket(client, entetes_consultant, status="done")
    with Session(engine) as session:
        carte = session.get(TkTicket, ticket["id"])
        carte.closed_at = None
        session.add(carte)
        session.commit()

    board = client.get("/tickets/board", headers=entetes_consultant).json()
    assert [t["id"] for t in board["done"]] == [ticket["id"]]


# --- Rattachement à un projet ----------------------------------------------


def _projet_pour_tickets(
    client: TestClient,
    entetes_admin: dict[str, str],
    nom: str,
    affecter_a: int | None = None,
) -> int:
    """Cree un projet, et y affecte un consultant si demande.

    Un non-administrateur ne peut rattacher un ticket qu'a une mission ou il
    est affecte : sans l'affectation, la creation est refusee.
    """
    reponse = client.post(
        "/projects/", json={"name": nom, "category": "Mission"}, headers=entetes_admin
    )
    assert reponse.status_code == 200, reponse.text
    projet_id = reponse.json()["id"]
    if affecter_a is not None:
        client.post(
            f"/users/{affecter_a}/projects",
            json={"project_ids": [projet_id]},
            headers=entetes_admin,
        )
    return projet_id


def test_ticket_porte_un_projet(
    client: TestClient, entetes_admin: dict[str, str], entetes_consultant: dict[str, str]
) -> None:
    projet_id = _projet_pour_tickets(client, entetes_admin, "HOMESERVE")
    ticket = _ticket(client, entetes_admin, project_id=projet_id)
    assert ticket["project_id"] == projet_id


def test_projet_modifiable_et_detachable(
    client: TestClient, entetes_admin: dict[str, str], entetes_consultant: dict[str, str]
) -> None:
    a = _projet_pour_tickets(client, entetes_admin, "A")
    b = _projet_pour_tickets(client, entetes_admin, "B")
    ticket = _ticket(client, entetes_admin, project_id=a)

    rattache = client.patch(
        f"/tickets/{ticket['id']}", json={"project_id": b}, headers=entetes_admin
    ).json()
    assert rattache["project_id"] == b

    detache = client.patch(
        f"/tickets/{ticket['id']}", json={"project_id": None}, headers=entetes_admin
    ).json()
    assert detache["project_id"] is None


def test_filtre_par_projet(
    client: TestClient, entetes_admin: dict[str, str], entetes_consultant: dict[str, str]
) -> None:
    a = _projet_pour_tickets(client, entetes_admin, "A")
    b = _projet_pour_tickets(client, entetes_admin, "B")
    _ticket(client, entetes_admin, title="Sur A", project_id=a)
    _ticket(client, entetes_admin, title="Sur B", project_id=b)
    _ticket(client, entetes_admin, title="Sans projet")

    board = client.get(f"/tickets/board?project_id={a}", headers=entetes_admin).json()
    assert [t["title"] for t in board["todo"]] == ["Sur A"]


def test_filtre_projet_se_combine_avec_mine(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    consultant_id: int,
    admin_id: int,
) -> None:
    projet_id = _projet_pour_tickets(client, entetes_admin, "A")
    attendu = _ticket(
        client, entetes_admin, title="À moi", project_id=projet_id, assignee_id=consultant_id
    )
    _ticket(
        client, entetes_admin, title="À l'autre", project_id=projet_id, assignee_id=admin_id
    )

    board = client.get(
        f"/tickets/board?mine=true&project_id={projet_id}", headers=entetes_consultant
    ).json()
    assert [t["id"] for t in board["todo"]] == [attendu["id"]]
