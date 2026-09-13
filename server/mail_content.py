"""Contenu des emails : titre, version texte, version HTML.

Fonctions pures, sans base ni SMTP : c'est ce qui permet de vérifier les
règles de contenu — un récap vide ne part pas, une échéance dépassée est
signalée — sans monter de serveur de messagerie.

Le HTML est en styles en ligne, sans image ni police distante. Les clients
de messagerie ignorent les feuilles de style externes et bloquent les
images par défaut ; un message qui en dépend arrive illisible.
"""

import logging
from datetime import date
from typing import Mapping, Sequence

logger = logging.getLogger(__name__)

BLEU = "#6186EA"
ENCRE = "#1a1a1a"
GRIS = "#6b7280"
CORAIL = "#ef4444"


def _echapper(texte: str) -> str:
    return (
        str(texte)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _coquille(titre: str, corps_html: str, lien: str) -> str:
    return (
        f'<div style="font-family:Helvetica,Arial,sans-serif;color:{ENCRE};'
        f'max-width:600px;margin:0 auto;padding:24px">'
        f'<h1 style="font-size:18px;margin:0 0 20px">{_echapper(titre)}</h1>'
        f"{corps_html}"
        f'<p style="margin-top:28px">'
        f'<a href="{_echapper(lien)}" style="background:{BLEU};color:#fff;'
        f'text-decoration:none;padding:12px 20px;border-radius:9999px;'
        f'font-weight:bold;font-size:13px">Ouvrir le CRA</a></p>'
        f'<p style="color:{GRIS};font-size:11px;margin-top:24px">'
        f"CRA SCOPA — message automatique, ne pas répondre.</p>"
        f"</div>"
    )


def _liste_html(items: Sequence[str], couleur: str = ENCRE) -> str:
    lignes = "".join(
        f'<li style="margin-bottom:6px;color:{couleur}">{_echapper(i)}</li>'
        for i in items
    )
    return f'<ul style="padding-left:18px;margin:0 0 16px">{lignes}</ul>'


def _section_html(titre: str, items: Sequence[str], couleur: str = ENCRE) -> str:
    if not items:
        return ""
    return (
        f'<h2 style="font-size:13px;text-transform:uppercase;letter-spacing:1px;'
        f'color:{GRIS};margin:20px 0 8px">{_echapper(titre)}</h2>'
        + _liste_html(items, couleur)
    )


def digest(nom: str, sections: Mapping[str, Sequence[str]], lien: str) -> dict | None:
    """Récap matinal. Renvoie `None` si rien à dire.

    Un email qui annonce qu'il n'y a rien à signaler apprend à l'ignorer :
    au bout de deux semaines, plus personne ne lit les autres non plus.
    """
    remplies = {titre: items for titre, items in sections.items() if items}
    if not remplies:
        return None

    total = sum(len(items) for items in remplies.values())
    sujet = f"CRA SCOPA — {total} point{'s' if total > 1 else ''} à regarder"

    lignes_texte = [f"Bonjour {nom},", ""]
    corps_html = ""
    for titre, items in remplies.items():
        lignes_texte.append(f"{titre.upper()}")
        lignes_texte.extend(f"  - {i}" for i in items)
        lignes_texte.append("")
        couleur = CORAIL if "retard" in titre.lower() else ENCRE
        corps_html += _section_html(titre, items, couleur)

    lignes_texte.append(lien)
    return {
        "subject": sujet,
        "text": "\n".join(lignes_texte),
        "html": _coquille(f"Bonjour {nom}", corps_html, lien),
    }


def closing_reminder(
    nom: str, periode: str, jours_manquants: Sequence[date], lien: str
) -> dict:
    """Rappel de clôture. Part même sans trou : c'est la clôture qu'on réclame."""
    if jours_manquants:
        sujet = f"CRA {periode} — {len(jours_manquants)} jour(s) à compléter"
        detail = [j.strftime("%d/%m") for j in jours_manquants]
        corps_html = _section_html("Jours ouvrés non couverts", detail, CORAIL)
        texte = (
            f"Bonjour {nom},\n\n"
            f"Votre CRA de {periode} n'est pas clôturé et il reste "
            f"{len(jours_manquants)} jour(s) ouvré(s) sans saisie ni absence :\n"
            + "\n".join(f"  - {d}" for d in detail)
        )
    else:
        sujet = f"CRA {periode} — à clôturer"
        corps_html = (
            f'<p style="margin:0 0 16px">Votre CRA est complet, '
            f"il ne reste qu'à le clôturer.</p>"
        )
        texte = (
            f"Bonjour {nom},\n\nVotre CRA de {periode} est complet, "
            f"il ne reste qu'à le clôturer."
        )

    return {
        "subject": sujet,
        "text": f"{texte}\n\n{lien}",
        "html": _coquille(f"CRA {periode}", corps_html, lien),
    }


def leave_decision(
    nom: str, type_absence: str, debut: date, fin: date, jours: float,
    approuve: bool, commentaire: str | None, lien: str,
) -> dict:
    """Décision sur une demande de congé, envoyée au demandeur."""
    verdict = "approuvée" if approuve else "refusée"
    sujet = f"Demande de congé {verdict} — {debut:%d/%m} au {fin:%d/%m}"
    couleur = "#22c55e" if approuve else CORAIL

    texte = (
        f"Bonjour {nom},\n\n"
        f"Votre demande de {type_absence} du {debut:%d/%m/%Y} au {fin:%d/%m/%Y} "
        f"({jours} jour(s)) a été {verdict}."
    )
    if commentaire:
        texte += f"\n\nCommentaire : {commentaire}"

    corps_html = (
        f'<p style="margin:0 0 12px">Votre demande de '
        f"<strong>{_echapper(type_absence)}</strong> du "
        f"{debut:%d/%m/%Y} au {fin:%d/%m/%Y} ({jours} jour(s)) a été "
        f'<strong style="color:{couleur}">{verdict}</strong>.</p>'
    )
    if commentaire:
        corps_html += (
            f'<p style="margin:0 0 12px;color:{GRIS}">'
            f"« {_echapper(commentaire)} »</p>"
        )

    return {
        "subject": sujet,
        "text": f"{texte}\n\n{lien}",
        "html": _coquille("Demande de congé", corps_html, lien),
    }


def leave_request_notice(
    demandeur: str, type_absence: str, debut: date, fin: date, jours: float, lien: str
) -> dict:
    """Nouvelle demande, envoyée aux administrateurs."""
    sujet = f"Congé à valider — {demandeur}, {debut:%d/%m} au {fin:%d/%m}"
    corps_html = (
        f'<p style="margin:0 0 12px"><strong>{_echapper(demandeur)}</strong> '
        f"demande {_echapper(type_absence)} du {debut:%d/%m/%Y} au "
        f"{fin:%d/%m/%Y}, soit {jours} jour(s).</p>"
    )
    texte = (
        f"{demandeur} demande {type_absence} du {debut:%d/%m/%Y} "
        f"au {fin:%d/%m/%Y}, soit {jours} jour(s)."
    )
    return {
        "subject": sujet,
        "text": f"{texte}\n\n{lien}",
        "html": _coquille("Congé à valider", corps_html, lien),
    }
