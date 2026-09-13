"""Primitives d'authentification : mots de passe et jetons.

Ce module ne connaît ni les modèles ni la base : il ne manipule que des
chaînes et des identifiants. Les dépendances FastAPI qui chargent
l'utilisateur courant vivent dans `main.py`, là où sont déclarés les modèles.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from fastapi.security import HTTPBearer

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
TOKEN_TTL_HOURS = 12

# Schéma Bearer : `auto_error=False` pour renvoyer nos propres messages
# plutôt que le 403 par défaut de Starlette sur en-tête absent.
bearer_scheme = HTTPBearer(auto_error=False)


def get_secret_key() -> str:
    """Clé de signature des jetons, lue dans l'environnement.

    Absente, l'application refuse de démarrer : une clé par défaut en dur
    rendrait tous les jetons forgeables par quiconque a lu le dépôt.
    """
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY absente de l'environnement. "
            "Copier server/.env.example vers server/.env et y placer une clé "
            "générée par : python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    return secret


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_byte_enc = plain_password.encode("utf-8")
    hashed_password_byte_enc = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_byte_enc, hashed_password_byte_enc)


def create_access_token(user_id: int, is_admin: bool) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Renvoie la charge utile du jeton, ou None s'il est invalide ou expiré."""
    try:
        return jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        logger.info("Jeton refusé : %s", exc)
        return None
