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
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", primary_key=True)

# Models
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_admin: bool = False
    
    cra_entries: List["CRAEntry"] = Relationship(back_populates="user")
    projects: List["Project"] = Relationship(back_populates="users", link_model=UserProjectLink)

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    category: str = "Mission" # Mission or Formation
    
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
    create_db_and_tables()

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
    
    if not req.project_ids:
        user.projects = []
    else:
        new_projects = session.exec(select(Project).where(Project.id.in_(req.project_ids))).all()
        user.projects = new_projects
    
    session.add(user)
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
    project: Project,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    existing = session.exec(select(Project).where(Project.name == project.name)).first()
    if existing: return existing
    session.add(project)
    session.commit()
    session.refresh(project)
    return project

@app.put("/projects/{project_id}", response_model=Project)
def update_project(
    project_id: int,
    project_data: Project,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
):
    db_project = session.get(Project, project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    
    db_project.name = project_data.name
    db_project.category = project_data.category
    
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
