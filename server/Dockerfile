# Utiliser l'image légère de uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY pyproject.toml uv.lock ./

# Installer les dépendances (sans installer le projet actuel si non présent)
RUN uv sync --frozen --no-dev

# Copier le code source et la base de données
# Tout le code serveur : modules metier, jobs, scripts d'alimentation.
COPY *.py ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY assets ./assets
# La base n'est pas dans l'image : docker-compose la monte depuis l'hote.
# Sur une machine neuve, creer le fichier avant le premier demarrage
# (`touch server/database.db`), sinon Docker monte un dossier a sa place.

# Exposer le port de FastAPI unifié (5500)
EXPOSE 5500

# Lancer l'application uvicorn sur le port 5500
# Le schema est applique avant le demarrage : un deploiement qui ajoute une
# migration met la base a jour tout seul.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn main:app --host 0.0.0.0 --port 5500"]
