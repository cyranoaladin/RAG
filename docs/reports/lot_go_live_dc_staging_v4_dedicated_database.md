# Lot DC — publier V4 sur une base staging dédiée, `ragdb` intacte

- Branche : `go-live/dc-staging-v4-dedicated-database`
- Base : `578fa3d1e3b24a993efd3032537bb976b674124f` (main après #253, lot DB)
- Décision du propriétaire (2026-09-24) : base staging neuve et dédiée à V4,
  prise après l'investigation en lecture seule du staging.

## 1. Pourquoi

Le pré-vol du lot DB s'est arrêté sur deux constats. D'abord, six fichiers
d'environnement par rôle manquaient. Ensuite, `ragdb` n'était pas vierge.

Mesures en lecture seule du 2026-09-24 :

| Élément de `ragdb` | État |
|---|---|
| Acquisition V2 (`production-profile-gate-2026-2027-v2`, `e9506f5a…`) | 479 ressources, 479 artefacts, `NEEDS_REVIEW`, sous les r2 ; aucun job, aucune attestation, aucune attribution |
| Placements produit | 26, du corpus pilote de pré-rentrée (27/08, autorisations `prerentree-2026-2027-*-v1`, dont #134), en `internal`, actualité `current`, 730 chunks, sans lien avec le contrôle actuel ; 7 collections en commun avec V4, dont 13 contenus identiques |
| Têtes | produit 4, contrôle 15 |

Qualifier V4 dans `ragdb` aurait servi les placements pilotes **mêlés** à V4,
car le retrieval filtre par programme et visibilité. Reprendre les lignes V2
n'aurait rien apporté.

La décision retenue est donc une base dédiée. `ragdb` y gagne un statut de
preuve intangible.

## 2. Ce que la PR change

| Pièce | Changement |
|---|---|
| `staging_v4_publication_authorization.json` | remplace celle de DB (`amends: DC`, `supersedes` = `745cd79c…`, non consommée) ; base `ragdb_profile_gate_v4` ; `ragdb` nommée `untouched` ; jeton GitHub spécifié ; quatre nouveaux interdits et cinq mentions |
| `check_staging_authorization.py` | quinze opérations. Nouvelles : `database_creation` (additive, `createdb -T template0`, `refuse_if_exists`) et `role_env_derivation` (sans nouveau secret). La sauvegarde vise `ragdb` en **lecture**. Les migrations vont de `000` à `005` et de `000` à `019`. |
| `staging_v4_publication.sh` | base dédiée partout ; référence d'intangibilité de `ragdb` au pré-vol, revérifiée après chaque étape qui écrit ; `decision_prevol` testable ; conteneurs limités aux fichiers par rôle ; jeton contrôlé sans être lu ; expurgation des mots de passe libpq ; `PYTHON` local explicite ; mode bibliothèque pour les tests |
| `staging_v4_role_env.py` (nouveau) | dérive les cinq fichiers par rôle des secrets existants : valeurs par l'environnement, écriture atomique, 0600 sous 0700, jamais d'écrasement, aucune valeur affichée |
| plan d'exécution | réécrit pour la base dédiée |

## 3. Opérations nouvellement autorisées (sur la base dédiée seulement)

1. **Création additive** de `ragdb_profile_gate_v4` : UTF8, locale C,
   `template0`, identique à `ragdb`. Une base existante est refusée, hors
   reprise constatée vierge.
2. **Provisionnement des rôles existants** sur cette base, par les runners
   canoniques :
   - `rag_reader`, `rag_reviewer` et `rag_publisher`, via
     `apply_pgvector_migrations.sh` ;
   - les quatre rôles `ingestion_control_*`, via
     `provision_and_bootstrap_ingestion_control.sh`.

   Aucun superutilisateur n'est concédé, et aucun mot de passe n'est changé :
   le pré-vol exige que chaque valeur source authentifie déjà son rôle.
3. **Migrations produit** de 001 à 005, et **migrations de contrôle** de 001 à
   019. La tête doit être 0 avant, puis 5 ou 19 après.
4. **Dérivation des fichiers par rôle.**
5. **Installation du modèle E5 de V4** (`58ad18db…`), vérifiée avant et après
   copie.
6. Puis, à l'identique du lot DB :
   - enregistrement des r4 (#252) ;
   - ingestion V4 (exige une base dédiée vierge) ;
   - revue batch ;
   - Worker B qualifié ;
   - vérification indépendante ;
   - sonde de retrieval.

**Toujours interdits :**
- modifier ou supprimer `ragdb` ;
- supprimer les données V2 ;
- réutiliser les 26 placements pilotes ;
- toute écriture en production ;
- une exposition publique, ou une bascule du service API.

## 4. Choix techniques

- **Nom de la base :** `ragdb_profile_gate_v4`. Il est explicite (famille de
  release, version) et stable.
- **Création :** `createdb` dans le conteneur, le procédé du dépôt
  (`test_hybrid_integration.sh`). Aucun SQL improvisé.
- **Garde `infra/.env` :** le runner produit source ce fichier **avant** ses
  valeurs par défaut. Un `.env` serveur qui fixerait `PGVECTOR_DB`
  redirigerait la migration vers `ragdb`. Le pré-vol le détecte (absent sur
  l'hôte le 2026-09-24), et la commande revérifie juste avant.
- **Rôle superutilisateur :** il est lu dans le conteneur (`POSTGRES_USER`).
  `staging.env` ne définit pas `PGVECTOR_USER`, que l'ancien plan supposait.
- **Format des DSN :** libpq à mots-clés, avec mot de passe entre apostrophes
  échappées. `conninfo_to_dict` les lit, et `docker --env-file` les prend
  littéralement.
- **Jeton GitHub :** chemin `/srv/nexus-staging/secrets/github-read-token/token`,
  0600 sous 0700, droits `contents:read` et `metadata:read` sur
  `cyranoaladin/RAG`. Il n'est **pas** créé : c'est au propriétaire de le
  faire, après approbation. Chaque conteneur qui le monte en vérifie la
  présence et les modes, sans jamais le lire.

## 5. Épreuves

| Épreuve | Résultat |
|---|---|
| `test_staging_v4_publication_authorization.py` | base dédiée, `ragdb` en lecture seule, création additive, migrations depuis zéro, dérivation sans secret, jeton en lecture, remplacement de DB, nouveaux interdits ; plus toutes les épreuves du lot DB |
| `test_staging_v4_role_env.py` | 20 : cinq fichiers, 0600/0700, aucun secret en sortie, aucun secret global dans un fichier de rôle, échappement libpq, rejeu identique, refus d'écraser, source absente, base `ragdb` refusée, répertoire trop ouvert refusé |
| `test_staging_v4_orchestrator.py` | 35. Essai à blanc hors ligne jusqu'au premier verrou humain. Chaque écriture vise la base dédiée ; chaque accès à `ragdb` est en lecture seule ou `pg_dump` ; `ragdb` est revérifiée après chaque étape qui écrit ; seuls des fichiers par rôle sont montés ; la base doit être vierge avant l'ingestion ; le jeton est exigé sans être lu ; l'expurgation est testée. `decision_prevol` : 2 cas acceptés, 11 refus. Intangibilité : 1 cas accepté, 3 variations refusées. |
| Total des fichiers V4 | 192 réussis |
| `scripts/qualification/tests` | 613 réussis, 4 ignorés |
| `scripts/tests` | 541 réussis ; seuls les 4 échecs de readiness go-live, dus au disque de la machine (40 Go exigés), hors lot |
| Unicité des autorités, verrous de gouvernance, `ruff` | conformes |
| Essai à blanc avec le vrai vérificateur | onze contrôles, un seul écart : « l'autorisation V4 n'est pas sur origin/main » |
| Requêtes de mesure contre le serveur réel (lecture seule) | valides. Référence de `ragdb` : têtes 4 et 15 ; 479 ressources, 479 artefacts, 26 placements, 730 chunks, 22 autorisations, avec leurs empreintes ; base dédiée absente |

## 6. Rien n'a été écrit sur le serveur

Toutes les lectures ont été faites avec `default_transaction_read_only=on`.
Aucune base n'a été créée, aucune migration appliquée, aucun fichier ni
secret créé ou modifié, et aucun jeton créé.

## 7. Risques résiduels

1. **Changement du cluster.** La création d'une base et l'octroi de droits
   sur celle-ci changent le cluster, pas `ragdb`. Les `ALTER ROLE` des
   runners de contrôle s'appliquent au niveau du cluster ; ils réimposent
   des attributs et des mots de passe identiques, vérifiés au pré-vol.
2. **Service API inchangé.** Il continue de servir `ragdb`, donc les
   placements pilotes en `current`. Le basculer vers la base dédiée est une
   décision distincte, pour la recette.
3. **Escalades du lot CZ, hors lot, toujours ouvertes :**
   - refus dense sur les doublons à la frontière du pool ;
   - `hnsw.ef_search` non fixé sur le chemin servi.
4. **Expiration du reçu PII** le 2026-10-23.
