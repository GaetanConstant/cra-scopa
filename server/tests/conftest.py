"""Fixtures de test.

`main` construit son moteur SQLAlchemy à l'import, à partir de `DATABASE_URL`.
Les variables d'environnement sont donc posées **avant** l'import du module,
sur une base temporaire : jamais sur `database.db`.
"""

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

_TMP_DB = Path(tempfile.mkdtemp(prefix="cra-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SECRET_KEY"] = "cle-de-test-sans-valeur-en-production"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel, delete  # noqa: E402

import main  # noqa: E402
from main import (  # noqa: E402
    Client,
    CRAEntry,
    Project,
    PublicHoliday,
    User,
    UserProjectLink,
    app,
    engine,
)
from auth import hash_password  # noqa: E402

MOT_DE_PASSE = "secret-de-test"


@pytest.fixture(autouse=True)
def base_vierge() -> Iterator[None]:
    """Chaque test part d'un schéma vide, pour ne pas dépendre de l'ordre."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for model in (CRAEntry, UserProjectLink, Project, Client, PublicHoliday, User):
            session.exec(delete(model))
        session.commit()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _creer_utilisateur(username: str, is_admin: bool) -> int:
    with Session(engine) as session:
        user = User(
            full_name=username.capitalize(),
            username=username,
            email=f"{username}@test.co",
            hashed_password=hash_password(MOT_DE_PASSE),
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


@pytest.fixture
def admin_id() -> int:
    return _creer_utilisateur("admin", is_admin=True)


@pytest.fixture
def consultant_id() -> int:
    return _creer_utilisateur("consultant", is_admin=False)


def _entetes(client: TestClient, username: str) -> dict[str, str]:
    reponse = client.post(
        "/auth/login", json={"username": username, "password": MOT_DE_PASSE}
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


@pytest.fixture
def entetes_admin(client: TestClient, admin_id: int) -> dict[str, str]:
    return _entetes(client, "admin")


@pytest.fixture
def entetes_consultant(client: TestClient, consultant_id: int) -> dict[str, str]:
    return _entetes(client, "consultant")
