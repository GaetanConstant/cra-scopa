import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from sqlmodel import Field, Relationship, SQLModel, create_engine, Session, select
from sqlalchemy.orm import selectinload
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from holidays import holidays_for_range
from leaves import LeaveError, count_leave_days, daily_load, overlaps
from timesheet import (
    TimesheetError,
    check_quantities,
    missing_working_days,
    overloaded_days,
    period_bounds,
    period_of,
)
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

# La colonne s'appelle `date`, comme le type : sans alias, Pydantic resout
# l'annotation vers le champ plutot que vers datetime.date.
DateType = date


class PublicHoliday(SQLModel, table=True):
    """Jour ferie, alimente par seed_holidays.py.

    La table est la reference commune du decompte des conges et des jours
    ouvres du pilotage : le calcul vit dans holidays.py, mais deux modules
    qui recalculent chacun de leur cote finiraient par diverger.
    """

    date: DateType = Field(primary_key=True)
    label: str


LEAVE_STATUSES = ("pending", "approved", "rejected", "cancelled")


class LeaveType(SQLModel, table=True):
    """Nature d'une absence. Alimente par seed_leave_types.py."""

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)  # CP, RTT, MALADIE...
    label: str
    counts_against_balance: bool = True
    color: Optional[str] = None


class LeaveRequest(SQLModel, table=True):
    """Demande d'absence, de son depot a sa decision.

    `days` est fige a la creation plutot que recalcule a la lecture : si un
    ferie est ajoute apres coup, le solde deja arrete ne doit pas bouger
    dans le dos du salarie.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    leave_type_id: int = Field(foreign_key="leavetype.id")

    start_date: DateType = Field(index=True)
    end_date: DateType
    start_half: Optional[str] = None  # nul = journee entiere
    end_half: Optional[str] = None
    days: float

    reason: Optional[str] = None
    status: str = Field(default="pending", index=True)
    decided_by: Optional[int] = Field(default=None, foreign_key="user.id")
    decided_at: Optional[datetime] = None
    decision_comment: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class LeaveBalance(SQLModel, table=True):
    """Droits acquis d'un utilisateur pour une annee et un type d'absence.

    Le solde restant n'est pas stocke : il se deduit des demandes approuvees,
    seule source qui ne puisse pas se desynchroniser.
    """

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    year: int = Field(primary_key=True)
    leave_type_id: int = Field(foreign_key="leavetype.id", primary_key=True)
    acquired: float = 0.0
    adjustment: float = 0.0  # reprise d'anteriorite, correction admin


class MonthClosure(SQLModel, table=True):
    """Cloture d'un mois pour un utilisateur.

    Une ligne presente en statut `closed` verrouille la periode : plus aucune
    ecriture, meme par un administrateur, tant qu'elle n'est pas rouverte.
    """

    user_id: int = Field(foreign_key="user.id", primary_key=True)
    period: str = Field(primary_key=True)  # AAAA-MM
    status: str = "closed"
    closed_at: Optional[datetime] = None
    closed_by: Optional[int] = Field(default=None, foreign_key="user.id")


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


class LeaveCreate(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    start_half: Optional[str] = None
    end_half: Optional[str] = None
    reason: Optional[str] = None
    user_id: Optional[int] = None  # admin uniquement : deposer pour un autre


class LeaveDecision(BaseModel):
    approve: bool
    comment: Optional[str] = None


class BalanceUpdate(BaseModel):
    user_id: int
    year: int
    leave_type_id: int
    acquired: float = 0.0
    adjustment: float = 0.0


class ClosePeriod(BaseModel):
    period: str
    user_id: Optional[int] = None  # admin : cloturer pour un autre


class ReopenPeriod(BaseModel):
    period: str
    user_id: int


class CopyWeek(BaseModel):
    target_week_start: date
    user_id: Optional[int] = None


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


@app.get("/holidays")
def read_holidays(
    year: Optional[int] = None,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Jours feries en base, filtres sur une annee si elle est fournie."""
    requete = select(PublicHoliday)
    if year is not None:
        requete = requete.where(
            PublicHoliday.date >= date(year, 1, 1),
            PublicHoliday.date <= date(year, 12, 31),
        )
    jours = session.exec(requete.order_by(PublicHoliday.date)).all()
    return [{"date": j.date, "label": j.label} for j in jours]


# --- Conges ---------------------------------------------------------------


def charger_feries(session: Session, start: date, end: date) -> set[date]:
    jours = session.exec(
        select(PublicHoliday).where(
            PublicHoliday.date >= start, PublicHoliday.date <= end
        )
    ).all()
    return {j.date for j in jours}


def demande_en_dict(demande: LeaveRequest) -> dict:
    return demande.model_dump()


@app.get("/leaves/types", response_model=List[LeaveType])
def read_leave_types(
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    return session.exec(select(LeaveType).order_by(LeaveType.code)).all()


@app.get("/leaves")
def read_leaves(
    user_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Demandes filtrees. Lecture ouverte a toute l'equipe (SPEC §4)."""
    requete = select(LeaveRequest)
    if user_id is not None:
        requete = requete.where(LeaveRequest.user_id == user_id)
    if from_date is not None:
        requete = requete.where(LeaveRequest.end_date >= from_date)
    if to_date is not None:
        requete = requete.where(LeaveRequest.start_date <= to_date)
    if status is not None:
        requete = requete.where(LeaveRequest.status == status)
    demandes = session.exec(requete.order_by(LeaveRequest.start_date)).all()
    return [demande_en_dict(d) for d in demandes]


@app.post("/leaves")
def create_leave(
    req: LeaveCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Depose une demande. Le decompte est calcule ici, pas envoye par le client."""
    cible = current_user.id
    if req.user_id is not None and req.user_id != current_user.id:
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demande possible uniquement pour soi-meme",
            )
        cible = req.user_id

    if not session.get(LeaveType, req.leave_type_id):
        raise HTTPException(status_code=404, detail="Type d'absence inconnu")

    # Le chevauchement se juge sur les demandes vivantes : une demande
    # refusee ou annulee ne bloque pas une nouvelle tentative.
    vivantes = session.exec(
        select(LeaveRequest).where(
            LeaveRequest.user_id == cible,
            LeaveRequest.status.in_(("pending", "approved")),
        )
    ).all()
    for autre in vivantes:
        if overlaps(req.start_date, req.end_date, autre.start_date, autre.end_date):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Chevauchement avec une demande du {autre.start_date} "
                    f"au {autre.end_date}"
                ),
            )

    feries = charger_feries(session, req.start_date, req.end_date)
    try:
        jours = count_leave_days(
            req.start_date, req.end_date, feries, req.start_half, req.end_half
        )
    except LeaveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if jours <= 0:
        raise HTTPException(
            status_code=422,
            detail="Cette periode ne contient aucun jour ouvre",
        )

    demande = LeaveRequest(
        user_id=cible,
        leave_type_id=req.leave_type_id,
        start_date=req.start_date,
        end_date=req.end_date,
        start_half=req.start_half,
        end_half=req.end_half,
        days=jours,
        reason=req.reason,
    )
    session.add(demande)
    session.commit()
    session.refresh(demande)
    return demande_en_dict(demande)


@app.post("/leaves/{leave_id}/decide")
def decide_leave(
    leave_id: int,
    req: LeaveDecision,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    demande = session.get(LeaveRequest, leave_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if demande.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cette demande est deja {demande.status}",
        )

    demande.status = "approved" if req.approve else "rejected"
    demande.decided_by = admin.id
    demande.decided_at = datetime.now()
    demande.decision_comment = req.comment
    session.add(demande)
    session.commit()
    session.refresh(demande)
    return demande_en_dict(demande)


@app.post("/leaves/{leave_id}/cancel")
def cancel_leave(
    leave_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Annule une demande.

    Une demande approuvee dont la date est passee exige l'accord de l'admin :
    le temps a ete pose, le retirer seul reecrirait l'historique.
    """
    demande = session.get(LeaveRequest, leave_id)
    if not demande:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if demande.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Annulation possible uniquement sur ses propres demandes",
        )
    if demande.status in ("rejected", "cancelled"):
        raise HTTPException(
            status_code=409, detail=f"Cette demande est deja {demande.status}"
        )
    if (
        demande.status == "approved"
        and demande.start_date < date.today()
        and not current_user.is_admin
    ):
        raise HTTPException(
            status_code=403,
            detail="Une absence deja commencee ne s'annule qu'avec l'accord d'un administrateur",
        )

    demande.status = "cancelled"
    session.add(demande)
    session.commit()
    session.refresh(demande)
    return demande_en_dict(demande)


@app.get("/leaves/balances")
def read_balances(
    year: Optional[int] = None,
    user_id: Optional[int] = None,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Soldes par utilisateur et par type.

    `remaining = acquired + adjustment - approuves`. Les demandes en attente
    sont exposees a part et jamais deduites : tant qu'elles ne sont pas
    validees, le droit reste acquis.
    """
    annee = year or date.today().year
    debut, fin = date(annee, 1, 1), date(annee, 12, 31)

    requete = select(LeaveBalance).where(LeaveBalance.year == annee)
    if user_id is not None:
        requete = requete.where(LeaveBalance.user_id == user_id)
    soldes = session.exec(requete).all()

    demandes = session.exec(
        select(LeaveRequest).where(
            LeaveRequest.start_date >= debut,
            LeaveRequest.start_date <= fin,
            LeaveRequest.status.in_(("pending", "approved")),
        )
    ).all()

    consomme: dict[tuple[int, int], float] = {}
    attente: dict[tuple[int, int], float] = {}
    for d in demandes:
        cle = (d.user_id, d.leave_type_id)
        cible = consomme if d.status == "approved" else attente
        cible[cle] = cible.get(cle, 0.0) + d.days

    return [
        {
            "user_id": s.user_id,
            "year": s.year,
            "leave_type_id": s.leave_type_id,
            "acquired": s.acquired,
            "adjustment": s.adjustment,
            "taken": consomme.get((s.user_id, s.leave_type_id), 0.0),
            "pending": attente.get((s.user_id, s.leave_type_id), 0.0),
            "remaining": round(
                s.acquired
                + s.adjustment
                - consomme.get((s.user_id, s.leave_type_id), 0.0),
                2,
            ),
        }
        for s in soldes
    ]


@app.put("/leaves/balances")
def upsert_balance(
    req: BalanceUpdate,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    """Pose ou corrige les droits acquis. Reserve a l'administration."""
    if not session.get(LeaveType, req.leave_type_id):
        raise HTTPException(status_code=404, detail="Type d'absence inconnu")

    cle = (req.user_id, req.year, req.leave_type_id)
    solde = session.get(LeaveBalance, cle)
    if solde is None:
        solde = LeaveBalance(**req.model_dump())
    else:
        solde.acquired = req.acquired
        solde.adjustment = req.adjustment
    session.add(solde)
    session.commit()
    return {"status": "ok"}


@app.get("/leaves/team-calendar")
def read_team_calendar(
    from_date: date,
    to_date: date,
    session: Session = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Qui est absent quand, sur la periode. Absences approuvees seulement."""
    demandes = session.exec(
        select(LeaveRequest).where(
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= from_date,
            LeaveRequest.start_date <= to_date,
        ).order_by(LeaveRequest.start_date)
    ).all()
    utilisateurs = {u.id: u.full_name for u in session.exec(select(User)).all()}
    types = {t.id: t.code for t in session.exec(select(LeaveType)).all()}

    return [
        {
            "user_id": d.user_id,
            "full_name": utilisateurs.get(d.user_id),
            "leave_type": types.get(d.leave_type_id),
            "start_date": d.start_date,
            "end_date": d.end_date,
            "start_half": d.start_half,
            "end_half": d.end_half,
            "days": d.days,
        }
        for d in demandes
    ]


# --- Saisie des temps -----------------------------------------------------


def charge_absences(session: Session, user_id: int, debut: date, fin: date) -> dict[date, float]:
    """Charge journaliere posee par les absences approuvees de la periode."""
    demandes = session.exec(
        select(LeaveRequest).where(
            LeaveRequest.user_id == user_id,
            LeaveRequest.status == "approved",
            LeaveRequest.end_date >= debut,
            LeaveRequest.start_date <= fin,
        )
    ).all()

    charge: dict[date, float] = {}
    for d in demandes:
        feries = charger_feries(session, d.start_date, d.end_date)
        for jour, valeur in daily_load(
            d.start_date, d.end_date, feries, d.start_half, d.end_half
        ).items():
            if debut <= jour <= fin:
                charge[jour] = charge.get(jour, 0.0) + valeur
    return charge


def periode_verrouillee(session: Session, user_id: int, period: str) -> bool:
    cloture = session.get(MonthClosure, (user_id, period))
    return cloture is not None and cloture.status == "closed"


def projets_autorises(session: Session, user_id: int) -> dict[int, UserProjectLink]:
    liens = session.exec(
        select(UserProjectLink).where(UserProjectLink.user_id == user_id)
    ).all()
    return {lien.project_id: lien for lien in liens}


def verifier_affectations(
    session: Session, user_id: int, lignes: List["CRAEntry"]
) -> None:
    """Un consultant n'impute que sur ses missions, dans leur fenetre."""
    autorises = projets_autorises(session, user_id)
    for ligne in lignes:
        if ligne.project_id is None:
            continue  # absence, ferie, activite sans projet
        lien = autorises.get(ligne.project_id)
        if lien is None:
            projet = session.get(Project, ligne.project_id)
            nom = projet.name if projet else ligne.project_id
            raise TimesheetError(f"Vous n'etes pas affecte au projet {nom}")
        if lien.start_date and ligne.date < lien.start_date:
            raise TimesheetError(
                f"Le {ligne.date} precede le debut de votre affectation "
                f"({lien.start_date})"
            )
        if lien.end_date and ligne.date > lien.end_date:
            raise TimesheetError(
                f"Le {ligne.date} depasse la fin de votre affectation "
                f"({lien.end_date})"
            )


@app.get("/time")
def read_timesheet(
    period: str,
    user_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Vue complete d'un mois : saisies, absences, feries, etat de cloture.

    Un seul aller-retour la ou l'ecran devait croiser quatre sources.
    """
    try:
        debut, fin = period_bounds(period)
    except TimesheetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    cible = user_id if user_id is not None else current_user.id

    lignes = session.exec(
        select(CRAEntry).where(
            CRAEntry.user_id == cible,
            CRAEntry.date >= debut,
            CRAEntry.date <= fin,
        )
    ).all()
    feries = charger_feries(session, debut, fin)
    absences = charge_absences(session, cible, debut, fin)
    cloture = session.get(MonthClosure, (cible, period))

    return {
        "period": period,
        "user_id": cible,
        "entries": [l.model_dump() for l in lignes],
        "leave_load": {str(j): v for j, v in sorted(absences.items())},
        "holidays": sorted(str(j) for j in feries),
        "closed": cloture is not None and cloture.status == "closed",
        "closed_at": cloture.closed_at if cloture else None,
        "overloaded_days": {
            str(j): v
            for j, v in overloaded_days(
                [(l.date, l.duration_factor) for l in lignes], absences
            ).items()
        },
        "missing_days": [
            str(j)
            for j in missing_working_days(
                period, [(l.date, l.duration_factor) for l in lignes], absences, feries
            )
        ],
    }


@app.post("/time/close")
def close_period(
    req: ClosePeriod,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Cloture un mois. Refuse tant qu'il reste un jour ouvre non couvert."""
    cible = current_user.id
    if req.user_id is not None and req.user_id != current_user.id:
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cloture possible uniquement sur son propre CRA",
            )
        cible = req.user_id

    try:
        debut, fin = period_bounds(req.period)
    except TimesheetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if periode_verrouillee(session, cible, req.period):
        raise HTTPException(status_code=409, detail="Cette periode est deja cloturee")

    lignes = session.exec(
        select(CRAEntry).where(
            CRAEntry.user_id == cible, CRAEntry.date >= debut, CRAEntry.date <= fin
        )
    ).all()
    feries = charger_feries(session, debut, fin)
    absences = charge_absences(session, cible, debut, fin)
    trous = missing_working_days(
        req.period, [(l.date, l.duration_factor) for l in lignes], absences, feries
    )
    if trous:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Des jours ouvres ne sont ni saisis ni couverts par une absence",
                "missing_days": [str(j) for j in trous],
            },
        )

    cloture = session.get(MonthClosure, (cible, req.period))
    if cloture is None:
        cloture = MonthClosure(user_id=cible, period=req.period)
    cloture.status = "closed"
    cloture.closed_at = datetime.now()
    cloture.closed_by = current_user.id
    session.add(cloture)
    session.commit()
    return {"status": "closed", "period": req.period, "user_id": cible}


@app.post("/time/reopen")
def reopen_period(
    req: ReopenPeriod,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin),
):
    """Rouvre une periode. Reserve a l'administration, et journalise."""
    cloture = session.get(MonthClosure, (req.user_id, req.period))
    if cloture is None or cloture.status != "closed":
        raise HTTPException(status_code=409, detail="Cette periode n'est pas cloturee")

    cloture.status = "open"
    cloture.closed_at = None
    cloture.closed_by = None
    session.add(cloture)
    session.commit()
    logger.warning(
        "Periode %s rouverte pour l'utilisateur %s par %s",
        req.period,
        req.user_id,
        admin.username,
    )
    return {"status": "open", "period": req.period, "user_id": req.user_id}


@app.post("/time/copy-week")
def copy_week(
    req: CopyWeek,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Recopie les 5 jours ouvres de la semaine precedente.

    Les jours couverts par une absence et les missions terminees sont
    ignores : recopier un conge ou une mission close ne produirait que des
    lignes a corriger ensuite.
    """
    cible = current_user.id
    if req.user_id is not None and req.user_id != current_user.id:
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Copie possible uniquement sur son propre CRA",
            )
        cible = req.user_id

    debut_cible = req.target_week_start - timedelta(days=req.target_week_start.weekday())
    debut_source = debut_cible - timedelta(days=7)
    fin_source = debut_source + timedelta(days=4)
    fin_cible = debut_cible + timedelta(days=4)

    periodes = {period_of(debut_cible), period_of(fin_cible)}
    for periode in periodes:
        if periode_verrouillee(session, cible, periode):
            raise HTTPException(
                status_code=409, detail=f"La periode {periode} est cloturee"
            )

    source = session.exec(
        select(CRAEntry).where(
            CRAEntry.user_id == cible,
            CRAEntry.date >= debut_source,
            CRAEntry.date <= fin_source,
        )
    ).all()
    if not source:
        return {"created": 0, "skipped": 0}

    feries = charger_feries(session, debut_cible, fin_cible)
    absences = charge_absences(session, cible, debut_cible, fin_cible)
    deja = {
        (l.date, l.project_id, l.activity_type)
        for l in session.exec(
            select(CRAEntry).where(
                CRAEntry.user_id == cible,
                CRAEntry.date >= debut_cible,
                CRAEntry.date <= fin_cible,
            )
        ).all()
    }
    projets = {p.id: p for p in session.exec(select(Project)).all()}
    crees = ignores = 0

    for ligne in source:
        cible_jour = ligne.date + timedelta(days=7)
        if cible_jour in feries or cible_jour.weekday() >= 5:
            ignores += 1
            continue
        if absences.get(cible_jour):
            ignores += 1
            continue
        projet = projets.get(ligne.project_id) if ligne.project_id else None
        if projet and projet.end_date and projet.end_date < cible_jour:
            ignores += 1
            continue
        if (cible_jour, ligne.project_id, ligne.activity_type) in deja:
            ignores += 1
            continue

        session.add(
            CRAEntry(
                date=cible_jour,
                duration_factor=ligne.duration_factor,
                activity_type=ligne.activity_type,
                user_id=cible,
                project_id=ligne.project_id,
            )
        )
        crees += 1

    session.commit()
    return {"created": crees, "skipped": ignores}


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
    periode = f"{year:04d}-{month:02d}"

    # L'enregistrement remplace le mois entier : toutes les lignes doivent
    # donc appartenir au meme mois et au meme utilisateur, sans quoi la
    # suppression ci-dessous effacerait des donnees qui ne sont pas remplacees.
    if any(e.user_id != user_id for e in entries):
        raise HTTPException(
            status_code=422, detail="Toutes les lignes doivent viser le meme utilisateur"
        )
    if any((e.date.year, e.date.month) != (year, month) for e in entries):
        raise HTTPException(
            status_code=422, detail="Toutes les lignes doivent appartenir au meme mois"
        )

    # Une periode cloturee est verrouillee pour tout le monde, administrateur
    # compris : la rouvrir est un acte explicite et journalise.
    if periode_verrouillee(session, user_id, periode):
        raise HTTPException(
            status_code=409,
            detail=f"La periode {periode} est cloturee. Un administrateur doit la rouvrir.",
        )

    lignes = [(e.date, e.duration_factor) for e in entries]
    try:
        check_quantities(lignes)
        if not current_user.is_admin:
            verifier_affectations(session, user_id, entries)
    except TimesheetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
