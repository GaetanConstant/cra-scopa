# Changelog

Historique des versions du **CRA SCOPA**, de la plus récente à la plus ancienne.
Ce fichier et `VERSION` sont la source de vérité du numéro affiché sur la page
de connexion. Les entrées décrivent le changement pour l'utilisateur.

Format d'une entrée : `## vX.Y.Z — <date ISO> — <titre>`.

## v2.2.1 — 2026-09-18 — Page de connexion
### Modifié
- La page de connexion affiche « CRA — Compte Rendu d'Activité » sous le logo, avec l'année et la version.

## v2.2.0 — 2026-09-15 — Le rapporteur suit ce qui est en cours
### Ajouté
- Chaque matin, le rapporteur d'un ticket voit ce qui est en cours chez les autres dans son récap.

## v2.1.1 — 2026-09-15 — Échéances hors année
### Corrigé
- Les emails affichent l'année d'une échéance quand elle tombe hors de l'année en cours.

## v2.1.0 — 2026-09-15 — Rappels de clôture et tickets plus stricts
### Ajouté
- Rappels de clôture du CRA le 18 et le 20 du mois, et notifications associées.
- Le rapporteur d'un ticket est modifiable, par l'administrateur.
### Modifié
- Sur un ticket, l'assigné et le rapporteur sont obligatoires ; un ticket terminé est verrouillé.

## v2.0.0 — 2026-09-13 — Refonte du socle
Refonte complète, base migrée et accès sécurisés : c'est un nouveau palier.
### Ajouté
- Connexion protégée par jeton et rôles (consultant, administrateur) ; la lecture de l'équipe est réservée à l'administrateur.
- Référentiel des clients et des missions facturables, avec affectation des consultants.
- Écran Congés : demandes, décompte, validation et soldes ; les congés validés apparaissent comme une ligne du CRA.
- Jours fériés français calculés et stockés.
- Saisie contrainte du CRA, plusieurs missions possibles sur une même journée, clôture mensuelle.
- Tickets : kanban avec glisser-déposer, étiquettes, commentaires, journal, rattachement aux projets et aux missions affectées.
- Mesure de l'activité des consultants et export.
- Emails : récap matinal, rappel de clôture, décisions de congés, gabarit à la charte.
- Vue semaine du CRA et navigation utilisables sur mobile.
### Modifié
- Interface refondue sur la charte Plouf (tokens de couleur, typographie), actions du CRA regroupées sur une seule ligne, tickets cloisonnés, Congés et Activité fondus dans l'écran.
- Base de données migrée sous Alembic ; la base sort du dépôt.
- Image Docker du serveur complète (tous les modules), timers systemd calés sur l'heure de Paris.

## v1.1.0 — 2026-04-27 — Jours fériés
### Ajouté
- Prise en compte des jours fériés dans la saisie.
### Supprimé
- Suppression d'un projet depuis l'interface.

## v1.0.1 — 2026-03-19 — Demi-journées
### Corrigé
- Saisie des demi-journées et décompte du nombre de jours du CRA.
- Ergonomie du champ de saisie du CRA ; vue bilan du scopeur.

## v1.0.0 — 2026-03-18 — Mise en production
- Saisie du CRA par mission et par jour, bilan global, API derrière le domaine de production.
