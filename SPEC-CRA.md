# SPEC — Application CRA & gestion de projet

> Spécification destinée à Claude Code.
> **L'application existe déjà.** Ce document décrit la cible complète, pas un projet neuf :
> une partie est en place, une partie est à construire. Le §0 est obligatoire avant toute ligne de code.
> Les zones marquées `@decision` sont des choix par défaut à confirmer.

---

## 0. Cadrage préalable — obligatoire

Avant d'écrire quoi que ce soit, lire le code existant et produire un **tableau de couverture** :
pour chaque module du §2, indiquer `existant` / `partiel` / `absent`, avec les fichiers et tables concernés.

Relever en particulier :

1. Table des utilisateurs : nom, clé primaire, champ d'affichage, gestion admin/simple, dépendance FastAPI qui protège les routes.
2. Référentiel clients / projets : existe-t-il ? quels champs ? une saisie de temps s'impute sur quoi aujourd'hui ?
3. Table des temps : granularité (heures ? demi-journées ?), unicité par jour, contraintes existantes.
4. Couche d'envoi d'emails et configuration SMTP éventuelles.
5. Conventions du projet : nommage des tables, style des routers, outil de migration, organisation du front, bibliothèque de composants et de styles.

**Règles absolues :**

- Ne rien réécrire de ce qui fonctionne. Si un module est `existant`, on l'étend, on ne le remplace pas.
- Suivre les conventions du code en place, y compris si elles diffèrent de ce document.
- Toute modification d'une table existante passe par une migration additive (colonne nullable, jamais de suppression ni de renommage sans validation explicite).
- Signaler tout écart entre la spec et l'existant plutôt que de trancher seul.

Livrable de cette étape : le tableau de couverture + la liste des questions ouvertes. **Attendre les réponses avant de coder.**

---

## 1. Objectif

Outil interne unique pour une coopérative de 5 personnes :

- saisir l'activité des consultants jour par jour,
- gérer congés et absences, qui conditionnent la saisie,
- piloter les missions et l'activité (occupation, facturation, CA),
- suivre le travail en cours dans un kanban de tickets.

Pas de facturation dans cette version (voir §11), mais le modèle de données doit permettre de l'ajouter plus tard sans refonte.

---

## 2. Modules

| # | Module | Contenu |
|---|---|---|
| A | Référentiel | Clients, missions, affectations des consultants |
| B | Temps | Saisie mensuelle, copie de semaine, clôture et verrouillage |
| C | Absences | Congés, RTT, demande et validation, soldes, jours fériés |
| D | Tickets | Kanban 4 colonnes, tags, commentaires, historique |
| E | Pilotage | Occupation, taux de facturation, CA réalisé et prévisionnel |
| F | Notifications | Récap matinal, rappel de clôture, décisions de congés |

---

## 3. Stack

Celle de l'existant : React + Vite, FastAPI, SQLite, nginx sur Infomaniak, déploiement GitHub Actions.

Ajouts autorisés :

| Besoin | Choix |
|---|---|
| Drag & drop kanban | `@dnd-kit/core` + `@dnd-kit/sortable` |
| Envoi email | `smtplib` + `email.message` (stdlib), pas de dépendance externe |
| Planification | timer systemd appelant un script CLI, pas de scheduler dans le process web |
| Jours fériés | calcul interne (algorithme de Butcher pour Pâques) + table en base, pas de dépendance |
| Migration | l'outil déjà en place |

---

## 4. Rôles

Deux profils :

- **admin** : référentiel, affectations, taux, validation des congés, clôture des mois, pilotage, suppression de tickets.
- **consultant** : saisit ses temps, demande ses congés, voit et gère les tickets, consulte ses propres indicateurs.

`@decision` : un consultant voit-il les temps et les indicateurs de ses collègues ? Par défaut **oui en lecture** — coopérative, transparence assumée — sauf les taux journaliers, réservés à l'admin.

---

## 5. Modèle de données

Nommage indicatif : **l'existant fait foi**. Les tables déjà présentes ne sont pas recréées, seules les colonnes manquantes sont ajoutées.

### A — Référentiel

```sql
clients(
  id, name, siren, contact_name, contact_email, is_active, created_at
)

missions(                          -- une mission = un engagement chez un client
  id,
  client_id REFERENCES clients(id),
  name,
  code TEXT UNIQUE,                -- court, pour l'affichage dans le calendrier
  billable INTEGER NOT NULL DEFAULT 1,   -- 0 = interne (R&D, admin, avant-vente, congés techniques)
  start_date, end_date,            -- end_date nullable = en cours
  sold_days REAL,                  -- jours vendus, nullable ; sert au prévisionnel
  status TEXT CHECK (status IN ('prospect','active','paused','closed')),
  created_at
)

mission_assignments(               -- qui travaille sur quoi, à quel taux
  id,
  mission_id REFERENCES missions(id) ON DELETE CASCADE,
  user_id REFERENCES users(id),
  daily_rate REAL,                 -- TJM, visible admin uniquement
  start_date, end_date,
  UNIQUE (mission_id, user_id, start_date)
)
```

`billable` et `daily_rate` ne sont pas de la facturation : ce sont les deux entrées indispensables du pilotage (§8). Sans elles, ni taux de facturation ni CA.

### B — Temps

```sql
time_entries(
  id,
  user_id REFERENCES users(id),
  mission_id REFERENCES missions(id),
  work_date TEXT NOT NULL,         -- ISO date
  quantity REAL NOT NULL,          -- en jours : 0.5 ou 1.0 (@decision : autoriser 0.25 ?)
  comment TEXT,
  ticket_id INTEGER REFERENCES tk_tickets(id) ON DELETE SET NULL,  -- nullable, voir §11
  created_at, updated_at
)

month_closures(
  user_id, period TEXT,            -- 'YYYY-MM'
  status TEXT CHECK (status IN ('open','closed')),
  closed_at, closed_by,
  PRIMARY KEY (user_id, period)
)
```

Contraintes : `quantity > 0` ; somme des `quantity` d'un utilisateur sur une même date ≤ 1.0 (validée en service, pas en SQL) ; aucune écriture possible sur une période `closed`.

`ticket_id` est nullable et inutilisé en v1 — colonne posée dès maintenant pour éviter une migration douloureuse plus tard.

### C — Absences

```sql
leave_types(
  id, code,                        -- 'CP','RTT','MALADIE','SANS_SOLDE','FORMATION'
  label, counts_against_balance INTEGER, color
)

leave_requests(
  id,
  user_id REFERENCES users(id),
  leave_type_id REFERENCES leave_types(id),
  start_date, end_date,
  start_half TEXT CHECK (start_half IN ('am','pm')),  -- nullable = journée entière
  end_half TEXT CHECK (end_half IN ('am','pm')),
  days REAL NOT NULL,              -- décompté, calculé hors week-ends et fériés
  reason TEXT,
  status TEXT CHECK (status IN ('pending','approved','rejected','cancelled')),
  decided_by, decided_at, decision_comment,
  created_at
)

leave_balances(
  user_id, year INTEGER, leave_type_id,
  acquired REAL NOT NULL DEFAULT 0,
  adjustment REAL NOT NULL DEFAULT 0,     -- reprise d'antériorité, correction manuelle admin
  PRIMARY KEY (user_id, year, leave_type_id)
)

public_holidays(
  date TEXT PRIMARY KEY, label TEXT
)
```

Solde restant = `acquired + adjustment − (somme des jours approuvés de l'année)`. Les demandes `pending` sont affichées séparément comme « en attente », jamais déduites du solde.

`@decision` : acquisition des CP à 2,08 j/mois travaillé (25 j/an), alimentée par un job mensuel ; RTT saisis manuellement par l'admin en début d'année.

`public_holidays` est alimentée par un script pour les années N-1 à N+2 : fériés fixes + lundi de Pâques, Ascension et lundi de Pentecôte calculés depuis Pâques. Pas de dépendance externe, pas d'appel réseau.

### D — Tickets

Tables préfixées `tk_`.

```sql
tk_tickets(
  id, title, description,
  status TEXT CHECK (status IN ('todo','in_progress','to_validate','done')) DEFAULT 'todo',
  priority TEXT CHECK (priority IN ('low','medium','high','urgent')) DEFAULT 'medium',
  assignee_id REFERENCES users(id) ON DELETE SET NULL,
  reporter_id REFERENCES users(id),
  position REAL NOT NULL,
  due_date, created_at, updated_at, closed_at
)

tk_tags(id, name UNIQUE, color, mission_id REFERENCES missions(id) ON DELETE SET NULL, archived_at)
tk_ticket_tags(ticket_id, tag_id, PRIMARY KEY(ticket_id, tag_id))
tk_events(id, ticket_id, user_id, kind, payload TEXT, created_at)
tk_comments(id, ticket_id, author_id, body, created_at, updated_at)
```

Les tags projet sont adossés au référentiel missions via `mission_id` : un tag est soit lié à une mission, soit libre (thème, catégorie). Pas de second référentiel parallèle.

### E — Notifications

```sql
notification_prefs(user_id PRIMARY KEY, daily_digest INTEGER DEFAULT 1, closing_reminder INTEGER DEFAULT 1)
email_log(id, user_id, kind, ref_date TEXT, status, error, created_at,
          UNIQUE (user_id, kind, ref_date))
```

### Index

`time_entries(user_id, work_date)`, `time_entries(mission_id, work_date)`, `leave_requests(user_id, start_date)`, `leave_requests(status)`, `tk_tickets(status, position)`, `tk_tickets(assignee_id, status)`.

### Ordre des cartes kanban

`position` en `REAL`. Insertion entre deux cartes = moyenne des voisines ; en tête `min − 1000` ; en queue `max + 1000`. Si l'écart passe sous `0.0001`, rééquilibrage de toute la colonne dans la même transaction.

---

## 6. Règles métier

### Saisie des temps

- Unité : la demi-journée. Une journée pleine vaut 1.0, une demi-journée 0.5.
- Le total d'une journée ne peut pas dépasser 1.0, absences comprises. Une demi-journée de congé laisse 0.5 disponible.
- Un jour couvert par un congé approuvé est **pré-rempli et non saisissable** sur la part absente.
- Week-ends et jours fériés sont grisés mais saisissables (astreinte, rush) avec confirmation.
- On ne peut imputer que sur une mission où l'utilisateur est affecté et dont la date est dans la fenêtre d'affectation. L'admin peut imputer partout.
- « Copier la semaine précédente » recopie les lignes des 5 jours ouvrés précédents, en ignorant les jours d'absence et les missions terminées.

### Clôture

- Le consultant clôture son mois. Après clôture : lecture seule pour lui.
- Seul l'admin peut rouvrir une période, avec une trace (`closed_at` remis à `NULL`, log applicatif).
- Un mois ne peut pas être clôturé s'il reste un jour ouvré ni saisi ni couvert par une absence : l'écran liste les trous avant de laisser valider. `@decision` — blocage dur ou simple avertissement ?

### Absences

- Demande sur une plage de dates, avec demi-journées possibles aux deux bornes.
- Décompte automatique hors week-ends et fériés.
- Chevauchement avec une demande existante non annulée : refusé.
- Demande sur une période clôturée : refusée.
- Validation par l'admin. Une demande approuvée puis annulée exige l'accord de l'admin si la date est passée.
- Un calendrier d'équipe montre qui est absent quand, sur le mois en cours et le suivant.

### Tickets

- Toutes les transitions sont permises, retours en arrière compris.
- Passage en `done` → `closed_at` ; sortie de `done` → `closed_at` remis à `NULL`.
- Création, changement de statut, d'assigné, de tags et édition écrivent dans `tk_events`.
- Suppression réservée à l'admin ; un tag utilisé s'archive, ne se supprime pas.

---

## 7. API

Routers montés dans l'app FastAPI existante, sous le préfixe en vigueur, protégés par la dépendance d'auth existante.

```
# Référentiel (écriture : admin)
GET/POST/PATCH   /clients, /clients/{id}
GET/POST/PATCH   /missions, /missions/{id}
GET              /missions/{id}/assignments
POST/PATCH/DELETE /assignments

# Temps
GET   /time?user_id&period=YYYY-MM   → lignes + absences + fériés + état de clôture
POST  /time                          {mission_id, work_date, quantity, comment?}
PATCH /time/{id}
DELETE /time/{id}
POST  /time/copy-week                {target_week_start}
POST  /time/close                    {period}
POST  /time/reopen                   {user_id, period}   (admin)

# Absences
GET   /leaves?user_id&from&to&status
POST  /leaves                        {leave_type_id, start_date, end_date, start_half?, end_half?, reason?}
POST  /leaves/{id}/decide            {approve|reject, comment?}   (admin)
POST  /leaves/{id}/cancel
GET   /leaves/balances?year
GET   /leaves/team-calendar?from&to
GET   /holidays?year

# Tickets
GET   /tickets/board                 filtres : assignee_id, tag_id, q, priority, mine
GET   /tickets/{id}
POST  /tickets
PATCH /tickets/{id}
POST  /tickets/{id}/move             {status, before_id?, after_id?}
DELETE /tickets/{id}                 (admin)
POST  /tickets/{id}/comments
GET/POST/PATCH /tickets/tags

# Pilotage
GET   /reporting/utilization?from&to&user_id?
GET   /reporting/revenue?year
GET   /reporting/missions?status
GET   /reporting/export?type&from&to   → CSV

# Préférences
GET/PATCH /notifications/prefs
POST  /notifications/digest/test       (admin)
```

---

## 8. Pilotage — définitions de calcul

À implémenter exactement comme suit, dans un service dédié et couvert par des tests. Ce sont les définitions qui font débat, pas le code.

- **Jours ouvrés** d'une période = jours du lundi au vendredi, moins les jours de `public_holidays`.
- **Jours disponibles** d'un consultant = jours ouvrés − jours d'absence approuvés.
- **Jours produits** = somme des `quantity` sur des missions `billable = 1`.
- **Jours saisis** = somme de toutes les `quantity`, missions internes comprises.
- **Taux d'occupation** = jours saisis ÷ jours disponibles. Mesure le remplissage du CRA, doit tendre vers 100 %.
- **Taux de facturation (TACE)** = jours produits ÷ jours disponibles. C'est l'indicateur économique.
- **CA réalisé** d'un mois = Σ (jours produits × `daily_rate` de l'affectation correspondante). Si aucun taux n'est renseigné sur l'affectation, la mission est comptée à 0 et **signalée** dans le rapport : un CA faux et silencieux est pire que pas de CA.
- **CA prévisionnel** = sur chaque mission `active`, jours vendus restants (`sold_days` − jours déjà produits) × taux, étalés linéairement sur les mois ouvrés restants jusqu'à `end_date`. Missions sans `sold_days` ou sans `end_date` exclues et listées à part. `@decision` — méthode volontairement grossière ; un vrai plan de charge serait un module à lui seul.

Écrans : un tableau de bord admin (TACE de l'équipe, CA réalisé vs prévisionnel sur 12 mois, missions dont le budget est consommé à plus de 80 %), et une vue personnelle pour chaque consultant (son occupation, ses jours produits, son solde de congés).

---

## 9. Frontend

### 9.0 Identité visuelle — reprise de la charte Plouf

Objectif : homogénéiser les outils internes sur la charte déjà définie pour **Plouf**. La source de vérité est le `DESIGN.md` du dépôt Plouf, pas ce document — **lire les valeurs exactes (hex, tailles, espacements) dans ce fichier et le code de Plouf, ne rien réinventer.**

À transposer :

- **Palette** : bleu Plouf, vert perroquet, jaune tropical, corail pour les alertes, neutres chauds. Reprendre les hex exacts.
- **Typographie** : Fraunces en display, Inter pour le corps, JetBrains Mono pour les données — donc pour tous les chiffres du CRA : quantités, totaux, TJM, soldes. Polices **auto-hébergées** (packages `@fontsource/*`), jamais servies depuis le CDN Google : RGPD et pas de dépendance réseau externe.
- **Symboles** : la goutte d'eau et le perroquet, à l'exclusion de tout autre.
- **Anti-patterns à respecter** : pas de dark mode, pas de dégradés violets, pas d'illustrations Corporate Memphis, pas d'emojis hors contextes définis, pas de langage infantilisant.

Mise en œuvre : extraire les tokens dans un `theme.css` unique (variables CSS pour couleurs, rayons, ombres, typographie) importé à la racine du front, puis reconstruire les composants de base (boutons, champs, cartes, badges) dessus. Ne pas empiler la nouvelle charte sur les styles existants : remplacer les valeurs en dur au fur et à mesure, module par module, en commençant par le login.

**Attention si Plouf est en Streamlit** : le code de la page n'est pas réutilisable tel quel dans un front React. On transpose le rendu visuel, pas le code. Reprendre les hex, les polices, les proportions et l'illustration du perroquet — l'illustration elle-même, elle, se récupère à l'identique si c'est un SVG ou un PNG.

### 9.1 Page de connexion — refonte

Refaire la page de login du CRA sur le modèle de celle de Plouf : même mise en page, même illustration de perroquet, mêmes couleurs et typographie.

- Ne toucher **que la présentation**. La mécanique d'authentification existante (endpoint, session/JWT, gestion des erreurs) reste strictement inchangée.
- Adapter le texte au contexte interne : nom de l'outil côté SCOPA, pas la baseline commerciale de Plouf.
- Messages d'erreur non discriminants (« identifiants incorrects », jamais « ce compte n'existe pas »), et conserver le comportement actuel en cas d'échec.
- Responsive : l'illustration passe en second plan ou disparaît sous 768 px, le formulaire reste centré et utilisable au pouce.
- Accessibilité : contrastes AA vérifiés sur la palette reprise, labels réels sur les champs (pas de simple placeholder), focus visible.

`@decision` : le perroquet est, dans Plouf, un **assistant conversationnel** avec un rôle précis (commenter les imports, signaler les anomalies). Dans le CRA il serait purement décoratif. Soit on l'assume comme un simple élément de marque maison, soit on lui donne plus tard un rôle cohérent ici — par exemple le rappel de clôture ou la signalisation des jours manquants. Par défaut : décoratif sur le login uniquement, pas de perroquet ailleurs dans l'app.

### 9.2 Écrans

Onglets : **Mon CRA** · **Congés** · **Tickets** · **Missions** (admin) · **Pilotage**.

**Mon CRA** — calendrier mensuel, une ligne par mission affectée, une colonne par jour. Clic = journée, double-clic ou demi-cellule = demi-journée. Colonne de total par jour et par mission, total du mois en pied. Absences pré-remplies et verrouillées, fériés grisés. Boutons « Copier la semaine précédente » et « Clôturer le mois ». Bandeau d'alerte tant qu'il reste des jours ouvrés vides.

**Congés** — formulaire de demande avec décompte calculé en direct, liste de ses demandes avec statut, soldes par type, calendrier d'équipe. Côté admin, une file de demandes en attente avec validation en un clic.

**Tickets** — 4 colonnes, drag & drop `@dnd-kit` (`PointerSensor` à 8 px d'activation, `KeyboardSensor` pour l'accessibilité), mise à jour optimiste avec rollback et toast. Carte : `#id`, titre sur 2 lignes, initiales de l'assigné, badge priorité, pastilles de tags, échéance en rouge si dépassée. Drawer latéral pour le détail, pas de page dédiée. Filtres : mes tickets, tags, recherche, priorité. Colonne `done` limitée aux 30 derniers jours avec bouton « voir tout ».

**Missions** — liste clients/missions, affectations, taux, jours vendus vs consommés avec barre de progression.

**Pilotage** — les écrans du §8, avec export CSV.

**Mobile (< 768 px)** — priorité à la saisie des temps : vue semaine plutôt que mois, gros boutons demi-journée. Kanban en colonne unique avec onglets de statut et menu « Déplacer vers… » au lieu du drag.

---

## 10. Emails (SMTP)

### Configuration

```
SMTP_HOST=ssl0.ovh.net          # boîte MX Plan OVH du domaine
SMTP_PORT=587                   # STARTTLS ; 465 en SSL si besoin
SMTP_USER=no-reply@scopa.co     # adresse complète = identifiant
SMTP_PASSWORD=...               # mot de passe de la boîte dédiée ; fichier .env en chmod 600
SMTP_FROM="CRA SCOPA <no-reply@scopa.co>"
APP_BASE_URL=https://...
MAIL_ENABLED=true
MAIL_DRY_RUN=false              # true = log sans envoi
```

`smtplib.SMTP` + `starttls()`, `EmailMessage` multipart texte + HTML, timeout 20 s, 2 tentatives espacées de 30 s puis abandon et log en `error`. HTML en styles inline, sans image ni web font, avec version texte systématique. SPF et DKIM doivent être en place sur le domaine expéditeur.

### Envois

Tous déclenchés par un **timer systemd** appelant un script CLI (`python -m app.jobs.<nom>`), jamais par un scheduler intégré au process web : un seul point d'exécution, pas de doublon avec plusieurs workers, relançable à la main. Chaque envoi passe par `email_log` avec sa contrainte d'unicité `(user_id, kind, ref_date)` : le job relancé deux fois n'envoie qu'une fois.

1. **`daily_digest`** — du lundi au vendredi à 8h. Par consultant : tickets en retard (échéance dépassée, statut ≠ `done`), tickets `in_progress` qui lui sont assignés avec leur ancienneté dans la colonne, tickets `to_validate`, échéances du jour et du lendemain. L'admin reçoit en plus les tickets `to_validate` de toute l'équipe. **Rien n'est envoyé si le récap est vide.**
2. **`closing_reminder`** — le dernier jour ouvré du mois, puis le 3 du mois suivant si la période est encore ouverte. Liste les jours ouvrés non couverts. L'admin reçoit la synthèse des CRA non clôturés.
3. **`leave_decision`** — immédiat, hors timer : email au demandeur à l'approbation ou au refus, email à l'admin à la création d'une demande. Envoi en `BackgroundTasks` FastAPI, échec loggué sans faire échouer la requête HTTP.

### Tests

Construction des contenus testée unitairement sans SMTP ; envoi testé contre `aiosmtpd` local ou MailHog ; `MAIL_DRY_RUN=true` pour un essai en production sans envoi ; `POST /notifications/digest/test` pour un envoi réel à l'admin seul.

---

## 11. Hors périmètre v1

**Facturation** : pas de génération de facture, pas de suivi d'encaissement, pas d'export comptable. Les champs `daily_rate`, `billable` et `sold_days` existent pour le pilotage uniquement — ils suffiront à brancher un module de facturation plus tard sans toucher au modèle.

Également exclus : notes de frais, plan de charge prévisionnel détaillé, Gantt et dépendances entre tickets, sous-tâches, pièces jointes, validation hiérarchique des temps, accès client, export PDF signé du CRA, mentions `@`, notifications push.

Portes laissées ouvertes, à ne pas fermer dans la modélisation : `time_entries.ticket_id` (imputer du temps depuis un ticket) et la facturation ci-dessus.

---

## 12. Critères d'acceptation

**Temps**
- [ ] Saisir une demi-journée sur deux missions le même jour fonctionne ; une troisième demi-journée est refusée.
- [ ] Un jour de congé approuvé apparaît pré-rempli et verrouillé dans le calendrier.
- [ ] « Copier la semaine précédente » ignore les jours d'absence.
- [ ] Après clôture, toute écriture sur le mois renvoie une erreur explicite ; seul l'admin peut rouvrir.
- [ ] Un consultant ne peut pas imputer sur une mission où il n'est pas affecté.

**Absences**
- [ ] Une demande du vendredi au lundi avec un férié compte le bon nombre de jours.
- [ ] Deux demandes qui se chevauchent : la seconde est refusée.
- [ ] Le solde ne bouge qu'à l'approbation, pas à la demande.
- [ ] Le calendrier d'équipe affiche les absences approuvées du mois.

**Tickets**
- [ ] Déplacement entre colonnes et réordonnancement dans une colonne persistent après rechargement.
- [ ] Un consultant reçoit un 403 sur la suppression d'un ticket.
- [ ] Les filtres « mes tickets » et tag se combinent.

**Pilotage**
- [ ] Sur un mois de 21 jours ouvrés avec 2 jours de congés et 15 jours produits, le TACE vaut 15 ÷ 19.
- [ ] Une mission sans taux renseigné apparaît dans la liste des anomalies du rapport CA.

**Identité visuelle**
- [ ] La page de connexion est visuellement cohérente avec celle de Plouf, sur un écran large comme sur mobile.
- [ ] Les polices sont servies depuis le serveur, aucune requête vers un domaine Google au chargement.
- [ ] Aucune couleur en dur hors `theme.css` dans les composants refondus.
- [ ] Le comportement de connexion (succès, échec, session) est identique à avant la refonte.

**Emails**
- [ ] Le job relancé deux fois n'envoie qu'un mail par personne et par jour.
- [ ] Un consultant sans tâche en cours ne reçoit pas de récap.
- [ ] La préférence décochée coupe l'envoi.

---

## 13. Ordre d'implémentation

0. Cadrage du §0 et réponses aux `@decision`. **Aucun code avant.**
0 bis. Tokens de la charte (`theme.css`, polices auto-hébergées, composants de base) puis refonte de la page de connexion. À faire tôt : tous les écrans suivants s'appuient dessus, et le faire après signifierait repasser sur chacun.
1. Compléter le référentiel : missions (`billable`, `sold_days`, dates, statut) et affectations avec taux.
2. Jours fériés : calcul, table, script d'alimentation, tests sur Pâques et Pentecôte.
3. Absences : modèle, décompte, API, validation admin, soldes.
4. Saisie des temps : contraintes, blocage par les absences, copie de semaine, clôture et réouverture.
5. Écran calendrier mensuel + écran congés.
6. Tickets : modèle, API board/move avec tests sur les positions, tags, commentaires, historique.
7. Onglet kanban, drag & drop, drawer, filtres.
8. Service de pilotage avec les définitions du §8, testé sur des jeux de données connus, puis écrans.
9. Emails : construction des contenus, tests, templates, timers systemd, préférences utilisateur.
10. Responsive mobile, polish, export CSV.

Chaque étape se termine par un commit fonctionnel, des tests verts, et une note sur ce qui a été repris de l'existant plutôt que reconstruit.
