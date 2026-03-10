# Utiliser l'image légère de uv
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY pyproject.toml uv.lock ./

# Installer les dépendances (sans installer le projet actuel si non présent)
RUN uv sync --frozen --no-dev

# Copier le code source et la base de données
COPY main.py seed.py database.db ./

# Exposer le port de FastAPI unifié (5500)
EXPOSE 5500

# Lancer l'application uvicorn sur le port 5500
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5500"]
