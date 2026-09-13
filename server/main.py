import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
from sqlmodel import Field, Relationship, SQLModel, create_engine, Session, select
from sqlalchemy.orm import selectinload
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from auth import (
    bearer_scheme,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)


def load_dotenv(path: Path) -> None:
    """Charge un .env minimal dans os.environ, sans dependance externe.

    Les variables deja presentes dans l'environnement ne sont pas ecrasees :
    en production, systemd ou Docker priment sur le fichier.
    """
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_dotenv(Path(__file__).parent / ".env")

# Database Setup
# DATABASE_URL permet de pointer une base jetable (tests, verification) sans
# toucher a database.db ; c'est la meme variable que lit alembic/env.py.
sqlite_file_name = "database.db"
sqlite_url = os.environ.get("DATABASE_URL", f"sqlite:///{sqlite_file_name}")
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

def create_db_and_tables():
    """Cree le schema a partir des modeles.

    Reserve aux tests, qui montent une base temporaire. En execution reelle
    le schema appartient a Alembic : `create_all` ne sait pas ajouter une
    colonne a une table existante, et creerait en silence les tables des
    migrations non encore appliquees.
    """
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session


CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentification requise",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> "User":
    """Utilisateur porte par le jeton Bearer, ou 401."""
    if credentials is None:
        raise CREDENTIALS_ERROR
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise CREDENTIALS_ERROR
    user = session.get(User, int(payload["sub"]))
    if user is None:
        # Compte supprime depuis l'emission du jeton.
        raise CREDENTIALS_ERROR
    return user


def require_admin(current_user: "User" = Depends(get_current_user)) -> "User":
    """Restreint la route aux administrateurs."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action reservee aux administrateurs",
        )
    return current_user

# Link Table for Many-to-Many
class UserProjectLink(SQLModel, table=True):
    """Affectation d'un consultant sur un projet.

    Le TJM et la fenetre de dates vivent ici et non sur le projet : deux
    consultants sur la meme mission n'ont ni le meme taux ni forcement les
    memes dates. La cle primaire reste (user_id, project_id) : une seule
    fenetre d'affectation par couple, ce qui suffit a l'usage actuel.
    """

    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", primary_key=True)

    daily_rate: Optional[float] = None  # TJM, visible des administrateurs seuls
    start_date: Optional[date] = None
    end_date: Optional[date] = None

# Models
class Client(SQLModel, table=True):
    """Donneur d'ordre. Un client porte une ou plusieurs missions."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    siren: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)

    projects: List["Project"] = Relationship(back_populates="client")


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_admin: bool = False
    
    cra_entries: List["CRAEntry"] = Relationship(back_populates="user")
    projects: List["Project"] = Relationship(back_populates="users", link_model=UserProjectLink)

PROJECT_STATUSES = ("prospect", "active", "paused", "closed")


class Project(SQLModel, table=True):
    """Mission ou activite sur laquelle on impute du temps.

    La table s'appelle toujours `project` : c'est le nom en place, porte par
    les 185 entrees CRA existantes. Les champs ajoutes sont ceux dont le
    pilotage a besoin — sans `billable` ni `daily_rate`, ni taux de
    facturation ni chiffre d'affaires.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    category: str = "Mission" # Mission or Formation

    code: Optional[str] = Field(default=None, unique=True)  # court, pour le calendrier
    client_id: Optional[int] = Field(default=None, foreign_key="client.id")
    billable: bool = True
    start_date: Optional[date] = None
    end_date: Optional[date] = None  # nul = en cours
    sold_days: Optional[float] = None  # jours vendus, alimente le previsionnel
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.now)

    client: Optional[Client] = Relationship(back_populates="projects")
    cra_entries: List["CRAEntry"] = Relationship(back_populates="project")
    users: List["User"] = Relationship(back_populates="projects", link_model=UserProjectLink)

class CRAEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date
    duration_factor: float = 1.0 
    activity_type: str = "Mission" 
    
    user_id: int = Field(foreign_key="user.id")
    user: User = Relationship(back_populates="cra_entries")
    
    project_id: Optional[int] = Field(default=None, foreign_key="project.id")
    project: Optional[Project] = Relationship(back_populates="cra_entries")

# DTOs
class LoginRequest(BaseModel):
    username: str
    password: str

class PasswordChangeRequest(BaseModel):
    user_id: int
    old_password: str
    new_password: str

class UserProjectsUpdate(BaseModel):
    project_ids: List[int]

class ClientCreateUpdate(BaseModel):
    name: str
    siren: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    is_active: bool = True


class ProjectCreateUpdate(BaseModel):
    """Corps des requetes projet.

    Un modele de table SQLModel ne valide pas les types en entree : les dates
    arrivaient telles quelles, en chaine, jusque dans SQLite. Ce DTO les
    convertit, et empeche au passage de forcer `id` ou `created_at`.
    """

    name: str
    category: str = "Mission"
    code: Optional[str] = None
    client_id: Optional[int] = None
    billable: bool = True
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    sold_days: Optional[float] = None
    status: str = "active"


class AssignmentUpdate(BaseModel):
    """Conditions d'une affectation existante. Ne cree ni ne supprime le lien."""

    user_id: int
    project_id: int
    daily_rate: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class UserCreateUpdate(BaseModel):
    full_name: str
    username: str
    email: str
    is_admin: bool = False
    password: Optional[str] = None

# FastAPI App
app = FastAPI(title="CRA Scopa")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    # Le schema est applique par `alembic upgrade head`, joue au demarrage du
    # conteneur et par run_dev.sh — pas par l'application elle-meme.
    logger.info("Demarrage de l'API CRA")

def verifier_statut(statut: str) -> None:
    """Le statut pilote le previsionnel : une valeur libre le fausserait."""
    if statut not in PROJECT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Statut invalide. Valeurs admises : {', '.join(PROJECT_STATUSES)}",
        )


# API Endpoints
@app.post("/auth/login")
def login(req: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == req.username)).first()
    # Message unique : distinguer "compte inconnu" de "mot de passe faux"
    # revient a confirmer l'existence d'un compte a qui le demande.
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    return {
        "access_token": create_access_token(user.id, user.is_admin),
        "token_type": "bearer",
        "id": user.id,
        "full_name": user.full_name,
        "username": user.username,
        "is_admin": user.is_admin
    }

@app.post("/users/password")
def change_password(
    req: PasswordChangeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Le corps de la requete ne decide pas de la cible : seul le jeton le fait.
    user = session.get(User, current_user.id)
    if not user or not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Ancien mot de passe incorrect")
    
    user.hashed_password = hash_password(req.new_password)
    session.add(user)
    session.commit()
    return {"status": "ok"}

@app.post("/users/")
def create_user(
    req: UserCreateUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    existing = session.exec(select(User).where(User.username == req.username)).first()
    if existing: raise HTTPException(status_code=400, detail="Ce nom d'utilisateur existe déjà")
    
    hashed = hash_password(req.password or "scopa2024")
    user = User(
        full_name=req.full_name,
        username=req.username,
        email=req.email,
        is_admin=req.is_admin,
        hashed_password=hashed
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@app.put("/users/{user_id}")
def update_user(
    user_id: int,
    req: UserCreateUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    user = session.get(User, user_id)
    if not user: raise HTTPException(status_code=404)
    
    user.full_name = req.full_name
    user.username = req.username
    user.email = req.email
    user.is_admin = req.is_admin
    
    if req.password:
        user.hashed_password = hash_password(req.password)
        
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

@app.get("/users/")
def read_users(
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    statement = select(User).options(selectinload(User.projects))
    users = session.exec(statement).all()
    # Explicitly convert to dict to include relationships
    return [
        {
            **u.model_dump(exclude={"hashed_password"}),
            "projects": [p.model_dump() for p in u.projects]
        }
        for u in users
    ]

# Get projects for a specific user
@app.get("/users/{user_id}/projects")
def get_user_projects(
    user_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    statement = select(User).where(User.id == user_id).options(selectinload(User.projects))
    user = session.exec(statement).first()
    if not user: raise HTTPException(status_code=404)
    return user.projects

# Update projects for a user (Admin only logic on frontend)
@app.post("/users/{user_id}/projects")
def update_user_projects(
    user_id: int,
    req: UserProjectsUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    statement = select(User).where(User.id == user_id).options(selectinload(User.projects))
    user = session.exec(statement).first()
    if not user: raise HTTPException(status_code=404)
    
    # Remplacer user.projects supprimerait puis recreerait toutes les lignes de
    # liaison, et avec elles le TJM et les dates de chaque affectation. On ne
    # touche donc qu'aux differences.
    voulus = set(req.project_ids or [])
    liens = session.exec(
        select(UserProjectLink).where(UserProjectLink.user_id == user_id)
    ).all()
    actuels = {lien.project_id for lien in liens}

    for lien in liens:
        if lien.project_id not in voulus:
            session.delete(lien)

    for project_id in voulus - actuels:
        session.add(UserProjectLink(user_id=user_id, project_id=project_id))

    session.commit()
    return {"status": "ok"}

@app.get("/projects/", response_model=List[Project])
def read_projects(
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    return session.exec(select(Project)).all()

@app.post("/projects/", response_model=Project)
def create_project(
    req: ProjectCreateUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    verifier_statut(req.status)
    existing = session.exec(select(Project).where(Project.name == req.name)).first()
    if existing: return existing
    project = Project(**req.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

@app.put("/projects/{project_id}", response_model=Project)
def update_project(
    project_id: int,
    project_data: ProjectCreateUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    db_project = session.get(Project, project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    
    # Seuls les champs presents dans la requete sont ecrits : l'ecran Projets
    # n'envoie que le nom et la categorie, et un simple renommage ne doit pas
    # effacer les jours vendus, les dates ou le statut.
    champs = project_data.model_dump(exclude_unset=True)
    if "status" in champs:
        verifier_statut(champs["status"])
    for champ, valeur in champs.items():
        setattr(db_project, champ, valeur)

    session.add(db_project)
    session.commit()
    session.refresh(db_project)
    return db_project

@app.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    session.delete(project)
    session.commit()
    return {"status": "ok"}

@app.get("/clients/", response_model=List[Client])
def read_clients(
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    return session.exec(select(Client).order_by(Client.name)).all()


@app.post("/clients/", response_model=Client)
def create_client(
    req: ClientCreateUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    if session.exec(select(Client).where(Client.name == req.name)).first():
        raise HTTPException(status_code=400, detail="Ce client existe deja")
    client = Client(**req.model_dump())
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


@app.put("/clients/{client_id}", response_model=Client)
def update_client(
    client_id: int,
    req: ClientCreateUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client non trouve")
    for champ, valeur in req.model_dump().items():
        setattr(client, champ, valeur)
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


@app.get("/projects/{project_id}/assignments")
def read_project_assignments(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Qui travaille sur ce projet, et a quelles conditions.

    Le TJM n'est renvoye qu'aux administrateurs (SPEC-CRA.md §4) : la
    transparence de la cooperative porte sur les temps, pas sur les taux.
    """
    if not session.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Projet non trouve")

    liens = session.exec(
        select(UserProjectLink).where(UserProjectLink.project_id == project_id)
    ).all()
    utilisateurs = {u.id: u for u in session.exec(select(User)).all()}

    return [
        {
            "user_id": lien.user_id,
            "full_name": utilisateurs[lien.user_id].full_name if lien.user_id in utilisateurs else None,
            "project_id": lien.project_id,
            "start_date": lien.start_date,
            "end_date": lien.end_date,
            **({"daily_rate": lien.daily_rate} if current_user.is_admin else {}),
        }
        for lien in liens
    ]


@app.put("/assignments")
def update_assignment(
    req: AssignmentUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Fixe TJM et fenetre de dates sur une affectation deja existante.

    L'appartenance d'un consultant a un projet se gere par
    POST /users/{id}/projects : cette route ne cree pas de lien.
    """
    lien = session.get(UserProjectLink, (req.user_id, req.project_id))
    if not lien:
        raise HTTPException(
            status_code=404,
            detail="Ce consultant n'est pas affecte a ce projet",
        )
    if req.start_date and req.end_date and req.end_date < req.start_date:
        raise HTTPException(
            status_code=422, detail="La date de fin precede la date de debut"
        )

    lien.daily_rate = req.daily_rate
    lien.start_date = req.start_date
    lien.end_date = req.end_date
    session.add(lien)
    session.commit()
    return {"status": "ok"}


@app.post("/cra/batch")
def create_cra_batch(
    entries: List[CRAEntry],
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Un consultant ne saisit que pour lui-meme ; l'admin peut saisir pour tous.
    if not current_user.is_admin and any(e.user_id != current_user.id for e in entries):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Saisie possible uniquement sur son propre CRA",
        )
    for entry in entries:
        if isinstance(entry.date, str):
            entry.date = datetime.strptime(entry.date, "%Y-%m-%d").date()

    if not entries:
        return {"status": "ok"}

    user_id = entries[0].user_id
    year = entries[0].date.year
    month = entries[0].date.month

    # Supprimer toutes les entrées existantes du mois pour cet utilisateur
    existing_entries = session.exec(
        select(CRAEntry).where(
            CRAEntry.user_id == user_id,
            CRAEntry.date >= date(year, month, 1),
            CRAEntry.date < date(year + (month // 12), (month % 12) + 1, 1)
        )
    ).all()
    for e in existing_entries:
        session.delete(e)

    for entry in entries:
        session.add(CRAEntry(
            date=entry.date,
            duration_factor=entry.duration_factor,
            activity_type=entry.activity_type,
            user_id=entry.user_id,
            project_id=entry.project_id
        ))

    session.commit()
    return {"status": "ok"}

@app.get("/cra/all/{year}/{month}", response_model=List[CRAEntry])
def read_all_cra(
    year: int,
    month: int,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    entries = session.exec(
        select(CRAEntry).where(
            CRAEntry.date >= date(year, month, 1)
        )
    ).all()
    return [e for e in entries if e.date.month == month and e.date.year == year]

@app.get("/cra/{user_id}/{year}/{month}", response_model=List[CRAEntry])
def read_user_cra(
    user_id: int,
    year: int,
    month: int,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    entries = session.exec(
        select(CRAEntry).where(
            CRAEntry.user_id == user_id,
            CRAEntry.date >= date(year, month, 1)
        )
    ).all()
    return [e for e in entries if e.date.month == month and e.date.year == year]



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5500)
