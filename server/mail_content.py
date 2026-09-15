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

# Tokens de la charte, repris de client/src/theme.css. Les emails ne peuvent
# pas charger de feuille de style : les valeurs sont donc écrites en dur ici,
# et c'est le seul endroit du code serveur où c'est le cas.
BLEU = "#6186EA"
BLEU_PALE = "#eef2fd"
ENCRE = "#1a1a1a"
GRIS = "#6b7280"
CORAIL = "#ef4444"
VERT = "#22c55e"
FOND = "#EDECEA"
CARTE = "#ffffff"
TRAIT = "#e8e7e5"

# Le logo est joint au message, pas chargé depuis un serveur : voir mailer.py.
LOGO_CID = "scopa-logo"

POLICE = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
)


def _echapper(texte: str) -> str:
    return (
        str(texte)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _coquille(titre: str, corps_html: str, lien: str, accroche: str = "") -> str:
    """Gabarit commun : bandeau au logo, carte blanche, bouton, pied de page.

    Mise en page en tableaux et styles en ligne. Ce n'est pas du HTML qu'on
    écrirait pour un navigateur, mais les clients de messagerie ignorent les
    feuilles de style et rendent mal flexbox et grid : le tableau reste la
    seule structure qui tient de Gmail à Outlook.
    """
    sous_titre = (
        f'<p style="margin:6px 0 0;font-family:{POLICE};font-size:13px;color:{GRIS}">'
        f"{_echapper(accroche)}</p>"
        if accroche
        else ""
    )

    return f"""\
<div style="margin:0;padding:0;background:{FOND}">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{FOND};padding:28px 12px">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:560px;background:{CARTE};border-radius:20px;
                    border:1px solid {TRAIT};overflow:hidden">

        <tr><td style="padding:24px 28px 0">
          <img src="cid:{LOGO_CID}" width="52" alt="SCOPA"
               style="display:block;border:0;width:52px;height:auto" />
        </td></tr>

        <tr><td style="padding:18px 28px 0">
          <h1 style="margin:0;font-family:{POLICE};font-size:20px;
                     font-weight:800;color:{ENCRE};letter-spacing:-0.3px">
            {_echapper(titre)}</h1>
          {sous_titre}
        </td></tr>

        <tr><td style="padding:20px 28px 4px;font-family:{POLICE};
                       font-size:14px;line-height:1.55;color:{ENCRE}">
          {corps_html}
        </td></tr>

        <tr><td style="padding:8px 28px 30px">
          <a href="{_echapper(lien)}"
             style="display:inline-block;background:{BLEU};color:#ffffff;
                    text-decoration:none;padding:13px 26px;border-radius:9999px;
                    font-family:{POLICE};font-size:12px;font-weight:800;
                    text-transform:uppercase;letter-spacing:0.08em">
            Ouvrir le CRA</a>
        </td></tr>

        <tr><td style="padding:16px 28px;background:{BLEU_PALE};
                       font-family:{POLICE};font-size:11px;color:{GRIS}">
          CRA SCOPA — message automatique, ne pas répondre.<br />
          Pour ne plus recevoir ces messages, décochez-les dans votre profil.
        </td></tr>

      </table>
    </td></tr>
  </table>
</div>"""


def _liste_html(items: Sequence[str], couleur: str = ENCRE) -> str:
    """Liste en lignes de tableau plutôt qu'en <ul> : les puces et les marges
    des listes varient trop d'un client à l'autre."""
    lignes = "".join(
        f'<tr><td style="padding:5px 0;font-family:{POLICE};font-size:14px;'
        f'color:{couleur};vertical-align:top">'
        f'<span style="color:{couleur};font-weight:700">•</span>&nbsp;&nbsp;'
        f"{_echapper(i)}</td></tr>"
        for i in items
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" style="margin:0 0 14px">{lignes}</table>'
    )


def _section_html(titre: str, items: Sequence[str], couleur: str = ENCRE) -> str:
    if not items:
        return ""
    return (
        f'<p style="margin:18px 0 6px;font-family:{POLICE};font-size:11px;'
        f"font-weight:800;text-transform:uppercase;letter-spacing:0.1em;"
        f'color:{couleur}">{_echapper(titre)}</p>' + _liste_html(items, couleur)
    )


def _encadre(texte: str, couleur: str = BLEU) -> str:
    """Bandeau d'accroche, pour ce qui doit être lu même en diagonale."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:0 0 16px"><tr><td style="background:{BLEU_PALE};'
        f"border-left:3px solid {couleur};border-radius:8px;padding:12px 14px;"
        f'font-family:{POLICE};font-size:13px;color:{ENCRE}">'
        f"{_echapper(texte)}</td></tr></table>"
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
        bas = titre.lower()
        couleur = CORAIL if "retard" in bas else BLEU if "valider" in bas else ENCRE
        corps_html += _section_html(titre, items, couleur)

    lignes_texte.append(lien)
    return {
        "subject": sujet,
        "text": "\n".join(lignes_texte),
        "html": _coquille(
            f"Bonjour {nom}",
            corps_html,
            lien,
            accroche=f"{total} point{'s' if total > 1 else ''} à regarder ce matin",
        ),
    }


def closing_reminder(
    nom: str, periode: str, jours_manquants: Sequence[date], lien: str
) -> dict:
    """Rappel de clôture, le 18 puis le 20, motivé par la paie.

    Le motif est dit explicitement : « clôturez votre CRA » sans raison se
    range dans les tâches qu'on remet à demain, « les salaires en dépendent »
    beaucoup moins.
    """
    urgence = "Les salaires du mois sont établis à partir des CRA clôturés."
    consigne = (
        "Une fois le mois complet, cliquez sur « Clôturer le mois » "
        "en haut de votre CRA."
    )

    if jours_manquants:
        sujet = f"CRA {periode} — {len(jours_manquants)} jour(s) à compléter avant clôture"
        detail = [j.strftime("%d/%m") for j in jours_manquants]
        corps_html = (
            _encadre(urgence, CORAIL)
            + _section_html("Jours ouvrés non couverts sur le mois", detail, CORAIL)
            + f'<p style="margin:0 0 16px">{consigne}</p>'
        )
        texte = (
            f"Bonjour {nom},\n\n{urgence}\n\n"
            f"Il reste {len(jours_manquants)} jour(s) ouvré(s) sans saisie ni "
            f"absence sur {periode} :\n"
            + "\n".join(f"  - {d}" for d in detail)
            + f"\n\n{consigne}"
        )
    else:
        sujet = f"CRA {periode} — à clôturer"
        corps_html = _encadre(urgence) + (
            f'<p style="margin:0 0 16px">Votre CRA est complet : {consigne}</p>'
        )
        texte = (
            f"Bonjour {nom},\n\n{urgence}\n\n"
            f"Votre CRA de {periode} est complet : {consigne}"
        )

    return {
        "subject": sujet,
        "text": f"{texte}\n\n{lien}",
        "html": _coquille(
            f"CRA {periode}", corps_html, lien, accroche=f"Bonjour {nom}"
        ),
    }


def month_closed_notice(nom: str, periode: str, lien: str) -> dict:
    """Un consultant a clôturé son mois, envoyé aux administrateurs."""
    sujet = f"CRA {periode} clôturé — {nom}"
    texte = f"{nom} a clôturé son CRA de {periode}."
    corps_html = _encadre(texte, VERT)
    return {
        "subject": sujet,
        "text": f"{texte}\n\n{lien}",
        "html": _coquille(f"CRA {periode} clôturé", corps_html, lien),
    }


def leave_decision(
    nom: str, type_absence: str, debut: date, fin: date, jours: float,
    approuve: bool, commentaire: str | None, lien: str,
) -> dict:
    """Décision sur une demande de congé, envoyée au demandeur."""
    verdict = "approuvée" if approuve else "refusée"
    sujet = f"Demande de congé {verdict} — {debut:%d/%m} au {fin:%d/%m}"
    couleur = VERT if approuve else CORAIL

    texte = (
        f"Bonjour {nom},\n\n"
        f"Votre demande de {type_absence} du {debut:%d/%m/%Y} au {fin:%d/%m/%Y} "
        f"({jours} jour(s)) a été {verdict}."
    )
    if commentaire:
        texte += f"\n\nCommentaire : {commentaire}"

    corps_html = _encadre(f"Demande {verdict}", couleur) + (
        f'<p style="margin:0 0 12px">'
        f"<strong>{_echapper(type_absence)}</strong> du "
        f"{debut:%d/%m/%Y} au {fin:%d/%m/%Y} — {jours} jour(s).</p>"
    )
    if commentaire:
        corps_html += (
            f'<p style="margin:0 0 12px;color:{GRIS};font-style:italic">'
            f"« {_echapper(commentaire)} »</p>"
        )

    return {
        "subject": sujet,
        "text": f"{texte}\n\n{lien}",
        "html": _coquille("Demande de congé", corps_html, lien, accroche=f"Bonjour {nom}"),
    }


def leave_request_notice(
    demandeur: str, type_absence: str, debut: date, fin: date, jours: float, lien: str
) -> dict:
    """Nouvelle demande, envoyée aux administrateurs."""
    sujet = f"Congé à valider — {demandeur}, {debut:%d/%m} au {fin:%d/%m}"
    corps_html = _encadre(f"{demandeur} attend votre décision") + (
        f'<p style="margin:0 0 12px">'
        f"<strong>{_echapper(type_absence)}</strong> du {debut:%d/%m/%Y} au "
        f"{fin:%d/%m/%Y} — {jours} jour(s).</p>"
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
