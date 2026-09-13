"""Envoi d'emails : configuration, mise en forme, remise.

`smtplib` et `email.message` suffisent — pas de dépendance externe pour une
poignée de messages par jour, conformément au §10 de SPEC-CRA.md.

Deux garde-fous en production :

- `MAIL_ENABLED=false` coupe tout, y compris les tentatives de connexion.
- `MAIL_DRY_RUN=true` construit et journalise le message sans l'envoyer.
  C'est le mode d'un premier essai en production, quand on veut voir ce qui
  partirait avant que ça parte.
"""

import logging
import os
import smtplib
import time
from dataclasses import dataclass
from pathlib import Path
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

TIMEOUT_SECONDES = 20
TENTATIVES = 2
ATTENTE_ENTRE_TENTATIVES = 30


class MailError(RuntimeError):
    """L'envoi a échoué après toutes les tentatives."""


def _bool_env(nom: str, defaut: bool) -> bool:
    valeur = os.environ.get(nom)
    if valeur is None:
        return defaut
    return valeur.strip().lower() in ("1", "true", "yes", "oui")


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str
    base_url: str
    enabled: bool
    dry_run: bool

    @classmethod
    def from_env(cls) -> "MailConfig":
        return cls(
            host=os.environ.get("SMTP_HOST", ""),
            port=int(os.environ.get("SMTP_PORT", "587")),
            user=os.environ.get("SMTP_USER", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            sender=os.environ.get("SMTP_FROM", "CRA SCOPA <no-reply@scopa.co>"),
            base_url=os.environ.get("APP_BASE_URL", "http://localhost:3300"),
            enabled=_bool_env("MAIL_ENABLED", False),
            dry_run=_bool_env("MAIL_DRY_RUN", True),
        )

    def manque(self) -> list[str]:
        """Réglages indispensables encore vides."""
        return [
            nom
            for nom, valeur in (
                ("SMTP_HOST", self.host),
                ("SMTP_USER", self.user),
                ("SMTP_PASSWORD", self.password),
            )
            if not valeur
        ]


LOGO = Path(__file__).parent / "assets" / "scopa-logo.png"
LOGO_CID = "scopa-logo"


def build_message(
    config: MailConfig, to: str, subject: str, text: str, html: str
) -> EmailMessage:
    """Message multipart texte + HTML, logo SCOPA joint en ligne.

    La version texte n'est pas une politesse : certains clients ne rendent
    que celle-là, et une alternative absente fait chuter la délivrabilité.

    Le logo voyage avec le message plutôt que d'être chargé depuis un
    serveur : les clients bloquent les images distantes par défaut, une
    pièce jointe en ligne s'affiche sans que le lecteur ait rien à autoriser.
    """
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    if f"cid:{LOGO_CID}" in html and LOGO.exists():
        partie_html = message.get_payload()[-1]
        partie_html.add_related(
            LOGO.read_bytes(),
            maintype="image",
            subtype="png",
            cid=f"<{LOGO_CID}>",
            filename="scopa.png",
        )
    return message


def send(
    config: MailConfig,
    to: str,
    subject: str,
    text: str,
    html: str,
    _dormir=time.sleep,
) -> str:
    """Envoie un message. Renvoie « sent », « dry_run » ou « disabled ».

    Deux tentatives espacées, puis abandon : au-delà, c'est le serveur SMTP
    qui a un problème et réessayer indéfiniment ne ferait que retarder le
    reste du lot.
    """
    if not config.enabled:
        logger.info("Envoi désactivé (MAIL_ENABLED) — %s à %s", subject, to)
        return "disabled"

    if config.dry_run:
        logger.info("Essai à blanc — %s à %s\n%s", subject, to, text)
        return "dry_run"

    manquants = config.manque()
    if manquants:
        raise MailError(f"Configuration SMTP incomplète : {', '.join(manquants)}")

    message = build_message(config, to, subject, text, html)
    derniere: Optional[Exception] = None

    for tentative in range(1, TENTATIVES + 1):
        try:
            with smtplib.SMTP(config.host, config.port, timeout=TIMEOUT_SECONDES) as smtp:
                smtp.starttls()
                smtp.login(config.user, config.password)
                smtp.send_message(message)
            logger.info("Envoyé à %s : %s", to, subject)
            return "sent"
        except (smtplib.SMTPException, OSError) as exc:
            derniere = exc
            logger.warning(
                "Envoi à %s en échec (tentative %s/%s) : %s",
                to,
                tentative,
                TENTATIVES,
                exc,
            )
            if tentative < TENTATIVES:
                _dormir(ATTENTE_ENTRE_TENTATIVES)

    raise MailError(f"Envoi à {to} abandonné après {TENTATIVES} tentatives : {derniere}")
