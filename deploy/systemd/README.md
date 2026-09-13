# Timers systemd

Deux envois périodiques, déclenchés hors du processus web : un seul point
d'exécution, pas de doublon si plusieurs workers tournent, et relançable à
la main.

## Installation sur la VM

```bash
sudo cp cra-*.service cra-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cra-digest.timer cra-closing-reminder.timer cra-backup.timer
systemctl list-timers 'cra-*'
```

## Sauvegarde de la base

`server/database.db` n'est pas versionnée : elle vit sur la VM et
`cra-backup.timer` la copie chaque nuit à 3h dans `~/cra-backups/`, trente
jours glissants. Restaurer = arrêter le backend, copier le fichier voulu à sa
place, redémarrer.

Sur une machine neuve, créer le fichier avant le premier démarrage
(`touch server/database.db`) : sans lui, Docker monte un dossier à sa place.

## Vérifier sans rien envoyer

`MAIL_DRY_RUN=true` dans `server/.env` : les messages sont construits et
écrits dans le journal, aucun n'est remis.

```bash
cd ~/cra-scopa/server
uv run python job_digest.py
uv run python job_closing_reminder.py --force 2026-09
journalctl -u cra-digest.service -n 50
```

## Relance

Les jobs sont idempotents : la contrainte d'unicité `(user_id, kind,
ref_date)` de la table `emaillog` fait qu'une seconde exécution le même jour
n'envoie rien.
