"""Emails : contenu, remise, idempotence des jobs, préférences.

Aucun serveur SMTP n'est monté : la construction du contenu se teste seule,
et la remise se teste en remplaçant `smtplib.SMTP` par un double.
"""

import smtplib
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import mail_content
import mailer
from main import EmailLog, LeaveType, MonthClosure, TkTicket, engine
from mailer import MailConfig, MailError
from seed_holidays import seed as seed_holidays
from seed_leave_types import seed as seed_leave_types

CONFIG_ACTIVE = MailConfig(
    host="smtp.test",
    port=587,
    user="no-reply@scopa.co",
    password="secret",
    sender="CRA SCOPA <no-reply@scopa.co>",
    base_url="https://cra.scopa.co",
    enabled=True,
    dry_run=False,
)


# --- Contenu ---------------------------------------------------------------


def test_recap_vide_ne_produit_rien() -> None:
    """§12 — un consultant sans tâche en cours ne reçoit pas de récap."""
    assert mail_content.digest("A. Patou", {"En cours": [], "À valider": []}, "url") is None


def test_recap_liste_les_sections_remplies() -> None:
    contenu = mail_content.digest(
        "A. Patou",
        {"Tickets en retard": ["#1 Corriger le TACE"], "En cours": []},
        "https://cra.scopa.co",
    )
    assert "2 points" not in contenu["subject"]
    assert "1 point" in contenu["subject"]
    assert "Corriger le TACE" in contenu["text"]
    assert "Corriger le TACE" in contenu["html"]
    assert "En cours" not in contenu["html"]


def test_html_sans_ressource_distante() -> None:
    """Le logo est joint au message (cid:), rien n'est chargé depuis un serveur."""
    import re

    contenu = mail_content.digest("A", {"X": ["y"]}, "https://cra.scopa.co")
    html = contenu["html"]
    sources = re.findall(r'<img[^>]+src="([^"]+)"', html)
    assert sources == ["cid:scopa-logo"]
    assert "fonts.googleapis" not in html
    assert "<link" not in html
    assert "style=" in html  # styles en ligne


def test_le_logo_est_joint_au_message() -> None:
    contenu = mail_content.digest("A", {"X": ["y"]}, "https://cra.scopa.co")
    message = mailer.build_message(
        CONFIG_ACTIVE, "a@b.co", contenu["subject"], contenu["text"], contenu["html"]
    )
    pieces = [
        (p.get_content_type(), p.get("Content-ID"))
        for p in message.walk()
        if p.get_content_type() == "image/png"
    ]
    assert pieces == [("image/png", "<scopa-logo>")]


def test_contenu_echappe_le_html() -> None:
    contenu = mail_content.digest("A", {"X": ["<script>alert(1)</script>"]}, "url")
    assert "<script>" not in contenu["html"]
    assert "&lt;script&gt;" in contenu["html"]


def test_rappel_de_cloture_liste_les_trous() -> None:
    contenu = mail_content.closing_reminder(
        "A. Patou", "2026-09", [date(2026, 9, 1), date(2026, 9, 2)], "url"
    )
    assert "2 jour(s)" in contenu["subject"]
    assert "01/09" in contenu["text"]


def test_rappel_de_cloture_sans_trou() -> None:
    contenu = mail_content.closing_reminder("A. Patou", "2026-09", [], "url")
    assert "à clôturer" in contenu["subject"]
    assert "complet" in contenu["text"]


def test_decision_de_conge() -> None:
    contenu = mail_content.leave_decision(
        "A. Patou", "Congés payés", date(2026, 6, 1), date(2026, 6, 5), 5.0,
        True, "Bonnes vacances", "url",
    )
    assert "approuvée" in contenu["subject"]
    assert "Bonnes vacances" in contenu["text"]

    refus = mail_content.leave_decision(
        "A. Patou", "Congés payés", date(2026, 6, 1), date(2026, 6, 5), 5.0,
        False, None, "url",
    )
    assert "refusée" in refus["subject"]


# --- Remise ----------------------------------------------------------------


class FauxSMTP:
    """Double de `smtplib.SMTP` : compte les envois, ou échoue à volonté."""

    envoyes: list = []
    echecs_restants = 0

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        if FauxSMTP.echecs_restants > 0:
            FauxSMTP.echecs_restants -= 1
            raise smtplib.SMTPException("serveur indisponible")
        FauxSMTP.envoyes.append(message)


@pytest.fixture(autouse=True)
def smtp_double(monkeypatch):
    FauxSMTP.envoyes = []
    FauxSMTP.echecs_restants = 0
    monkeypatch.setattr(mailer.smtplib, "SMTP", FauxSMTP)
    yield FauxSMTP


def test_envoi_desactive() -> None:
    config = MailConfig(**{**CONFIG_ACTIVE.__dict__, "enabled": False})
    assert mailer.send(config, "a@b.co", "s", "t", "<p>h</p>") == "disabled"
    assert FauxSMTP.envoyes == []


def test_essai_a_blanc_n_envoie_rien() -> None:
    config = MailConfig(**{**CONFIG_ACTIVE.__dict__, "dry_run": True})
    assert mailer.send(config, "a@b.co", "s", "t", "<p>h</p>") == "dry_run"
    assert FauxSMTP.envoyes == []


def test_envoi_reel() -> None:
    assert mailer.send(CONFIG_ACTIVE, "a@b.co", "Sujet", "texte", "<p>html</p>") == "sent"
    assert len(FauxSMTP.envoyes) == 1
    message = FauxSMTP.envoyes[0]
    assert message["To"] == "a@b.co"
    assert message["Subject"] == "Sujet"
    assert message.get_content_type() == "multipart/alternative"


def test_une_seconde_tentative_apres_un_echec() -> None:
    FauxSMTP.echecs_restants = 1
    dormi = []
    assert (
        mailer.send(
            CONFIG_ACTIVE, "a@b.co", "s", "t", "<p>h</p>", _dormir=dormi.append
        )
        == "sent"
    )
    assert dormi == [mailer.ATTENTE_ENTRE_TENTATIVES]


def test_abandon_apres_deux_echecs() -> None:
    FauxSMTP.echecs_restants = 5
    with pytest.raises(MailError):
        mailer.send(CONFIG_ACTIVE, "a@b.co", "s", "t", "<p>h</p>", _dormir=lambda _: None)


def test_configuration_incomplete() -> None:
    config = MailConfig(**{**CONFIG_ACTIVE.__dict__, "password": ""})
    assert config.manque() == ["SMTP_PASSWORD"]
    with pytest.raises(MailError):
        mailer.send(config, "a@b.co", "s", "t", "<p>h</p>")


# --- Jobs ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def referentiel() -> None:
    seed_holidays(2026, 2026)
    seed_leave_types()


@pytest.fixture
def mail_actif(monkeypatch) -> None:
    """Envoi réel activé, vers le double SMTP."""
    monkeypatch.setenv("MAIL_ENABLED", "true")
    monkeypatch.setenv("MAIL_DRY_RUN", "false")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "no-reply@scopa.co")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")


def test_recap_du_jour_puis_relance_sans_doublon(
    client: TestClient,
    entetes_consultant: dict[str, str],
    consultant_id: int,
    mail_actif,
) -> None:
    """§12 — le job relancé deux fois n'envoie qu'un mail par personne."""
    import job_digest

    client.post(
        "/tickets",
        json={"title": "Corriger le TACE", "assignee_id": consultant_id},
        headers=entetes_consultant,
    )

    jour = date(2026, 9, 15)  # un mardi
    premier = job_digest.run(jour)
    assert premier.get("sent") == 1
    envoyes = len(FauxSMTP.envoyes)

    second = job_digest.run(jour)
    assert second.get("skipped") == 1
    assert len(FauxSMTP.envoyes) == envoyes


def test_recap_ignore_le_week_end(mail_actif) -> None:
    import job_digest

    assert job_digest.run(date(2026, 9, 13)) == {"weekend": 1}  # dimanche


def test_recap_non_envoye_si_rien_a_dire(
    client: TestClient, entetes_consultant: dict[str, str], mail_actif
) -> None:
    import job_digest

    resultats = job_digest.run(date(2026, 9, 15))
    assert resultats.get("vide", 0) >= 1
    assert FauxSMTP.envoyes == []


def test_preference_decochee_coupe_l_envoi(
    client: TestClient,
    entetes_consultant: dict[str, str],
    consultant_id: int,
    mail_actif,
) -> None:
    """§12 — la préférence décochée coupe l'envoi."""
    import job_digest

    client.post(
        "/tickets",
        json={"title": "X", "assignee_id": consultant_id},
        headers=entetes_consultant,
    )
    client.patch(
        "/notifications/prefs",
        json={"daily_digest": False, "closing_reminder": True},
        headers=entetes_consultant,
    )

    resultats = job_digest.run(date(2026, 9, 15))
    assert resultats.get("prefs_off", 0) >= 1
    assert resultats.get("sent", 0) == 0


def test_rappel_de_cloture_hors_calendrier(mail_actif) -> None:
    import job_closing_reminder

    assert job_closing_reminder.run(date(2026, 9, 15)) == {"hors_calendrier": 1}


def test_rappel_de_cloture_force(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int, mail_actif
) -> None:
    import job_closing_reminder

    resultats = job_closing_reminder.run(date(2026, 9, 15), force_periode="2026-09")
    assert resultats.get("sent", 0) >= 1
    assert any("2026-09" in m["Subject"] for m in FauxSMTP.envoyes)


def test_rappel_saute_les_periodes_cloturees(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int, mail_actif
) -> None:
    import job_closing_reminder

    with Session(engine) as session:
        session.add(
            MonthClosure(
                user_id=admin_id,
                period="2026-09",
                status="closed",
                closed_at=datetime.now(),
            )
        )
        session.commit()

    resultats = job_closing_reminder.run(date(2026, 9, 15), force_periode="2026-09")
    assert resultats.get("cloture", 0) == 1


def test_le_rappel_tombe_le_vingt_sur_le_mois_en_cours() -> None:
    from job_closing_reminder import periode_a_rappeler

    # 20 octobre 2026 est un mardi : le rappel part ce jour-là.
    assert periode_a_rappeler(date(2026, 10, 20)) == "2026-10"
    assert periode_a_rappeler(date(2026, 10, 19)) is None
    assert periode_a_rappeler(date(2026, 10, 21)) is None
    assert periode_a_rappeler(date(2026, 10, 30)) is None


def test_le_rappel_couvre_tout_le_mois(
    client: TestClient, entetes_admin: dict[str, str], mail_actif
) -> None:
    """Le CRA se remplit par anticipation : les jours à venir comptent aussi."""
    import job_closing_reminder

    # Le 20 est un dimanche, le rappel part le lundi 21.
    job_closing_reminder.run(date(2026, 9, 21))
    message = next(m for m in FauxSMTP.envoyes if "à compléter" in m["Subject"])
    texte = message.get_body(("plain",)).get_content()
    # Septembre 2026 : 22 jours ouvrés, du 1er au 30, aucun férié.
    assert "22 jour(s)" in texte
    assert "30/09" in texte
    assert "salaires" in texte


def test_preferences_par_defaut(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    prefs = client.get("/notifications/prefs", headers=entetes_consultant).json()
    assert prefs["daily_digest"] is True
    assert prefs["closing_reminder"] is True


def test_configuration_reservee_a_l_admin(
    client: TestClient, entetes_consultant: dict[str, str]
) -> None:
    assert (
        client.get("/notifications/config", headers=entetes_consultant).status_code
        == 403
    )


def test_configuration_ne_renvoie_pas_le_mot_de_passe(
    client: TestClient, entetes_admin: dict[str, str], mail_actif
) -> None:
    config = client.get("/notifications/config", headers=entetes_admin).json()
    assert "password" not in config
    assert "secret" not in str(config)
    assert config["missing"] == []


def test_envoi_d_essai(
    client: TestClient, entetes_admin: dict[str, str], mail_actif
) -> None:
    reponse = client.post("/notifications/digest/test", headers=entetes_admin)
    assert reponse.status_code == 200
    assert reponse.json()["status"] == "sent"
    assert len(FauxSMTP.envoyes) == 1


def test_envoi_d_essai_ne_consomme_pas_le_recap_du_jour(
    client: TestClient, entetes_admin: dict[str, str], admin_id: int, mail_actif
) -> None:
    """Un essai ne doit pas empêcher le vrai récap de partir."""
    client.post("/notifications/digest/test", headers=entetes_admin)
    with Session(engine) as session:
        traces = session.exec(select(EmailLog)).all()
    assert traces == []


def test_recap_ignore_les_feries(mail_actif) -> None:
    import job_digest

    # 11 novembre 2026, un mercredi.
    assert job_digest.run(date(2026, 11, 11)) == {"ferie": 1}


def test_le_rappel_glisse_apres_un_week_end_ou_un_ferie() -> None:
    from job_closing_reminder import jour_de_rappel, periode_a_rappeler

    # 20 septembre 2026 est un dimanche : le rappel part le lundi 21.
    assert jour_de_rappel(2026, 9, set()) == date(2026, 9, 21)
    assert periode_a_rappeler(date(2026, 9, 20)) is None
    assert periode_a_rappeler(date(2026, 9, 21)) == "2026-09"

    # 20 mai 2027 tombe un jeudi de l'Ascension (Pâques le 28 mars 2027 + 39) :
    # on glisse au vendredi 21.
    assert jour_de_rappel(2027, 5, {date(2027, 5, 6)}) == date(2027, 5, 20)
    assert jour_de_rappel(2027, 5, {date(2027, 5, 20)}) == date(2027, 5, 21)



def test_recap_assigne_et_rapporteur(
    client: TestClient,
    entetes_admin: dict[str, str],
    entetes_consultant: dict[str, str],
    admin_id: int,
    consultant_id: int,
    mail_actif,
) -> None:
    """L'assigné voit ce qu'il a à faire ; le rapporteur, ce qu'il doit relire."""
    import job_digest

    # L'admin ouvre un ticket pour le consultant, qui le met en cours puis
    # le soumet ; un second reste à faire.
    confie = client.post(
        "/tickets", json={"title": "À relire", "assignee_id": consultant_id},
        headers=entetes_admin,
    ).json()
    client.post(f"/tickets/{confie['id']}/move", json={"status": "to_validate"},
                headers=entetes_consultant)
    client.post(
        "/tickets", json={"title": "Encore à faire", "assignee_id": consultant_id,
                          "due_date": "2026-01-01"},
        headers=entetes_admin,
    )

    job_digest.run(date(2026, 9, 15))
    par_destinataire = {m["To"]: m.get_body(("plain",)).get_content() for m in FauxSMTP.envoyes}

    consultant = par_destinataire["consultant@test.co"]
    assert "À FAIRE" in consultant
    assert "Encore à faire" in consultant
    assert "EN RETARD" in consultant
    assert "À relire" not in consultant  # soumis : plus dans sa liste

    admin = par_destinataire["admin@test.co"]
    assert "À VALIDER" in admin
    assert "À relire" in admin
    assert "Encore à faire" not in admin  # pas assigné à lui


def test_recap_sans_section_echeances() -> None:
    contenu = mail_content.digest("A", {"À faire": ["x"]}, "url")
    assert "aujourd" not in contenu["text"].lower()
