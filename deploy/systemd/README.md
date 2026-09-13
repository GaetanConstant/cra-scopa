# Timers systemd

Deux envois périodiques, déclenchés hors du processus web : un seul point
d'exécution, pas de doublon si plusieurs workers tournent, et relançable à
la main.

## Installation sur la VM

```bash
sudo cp cra-*.service cra-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cra-digest.timer cra-closing-reminder.timer
systemctl list-timers 'cra-*'
```

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
