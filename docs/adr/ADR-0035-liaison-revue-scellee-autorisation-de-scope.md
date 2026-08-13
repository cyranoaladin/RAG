# ADR-0035 — Liaison de revue scellée d'une autorisation de scope

- **Statut** : Proposé — **non Accepté**. Une acceptation exige une review
  humaine `APPROVED` du Code Owner `@abenrhouma` sur le HEAD exact de la PR
  d'implémentation.
- **Date** : 2026-08-10
- **Décideur proposé** : à confirmer par `@abenrhouma`.
- **Périmètre** : passerelle additive entre l'autorité en ligne (ADR-0025 /
  ADR-0032 / ADR-0034) et le gate final hors ligne du plan de contrôle
  pédagogique. Ce document n'autorise aucun corpus et n'active aucune
  ingestion.
- **S'appuie sur** : ADR-0001, ADR-0025, ADR-0032, ADR-0033, ADR-0034.
- **Ne supersede rien** : les protocoles `NEXUS-TRUSTED-REVIEW-V1` et
  `LOT41A-V1/V2` conservent leur sens et leur représentation exacts.
  `LOT42-V1` conserve lui aussi sa représentation exacte — il n'est jamais
  réécrit — mais **perd toute capacité d'autorisation** (§ 6 ci-dessous).
- **Amendé le 2026-08-11** en réponse aux constats F1, F2 et F3 de la
  review Codex `4904995785` sur `b595fd9`. Les sections 5, 6 et 7 sont
  nouvelles ; la section « Ancre de confiance » est resserrée. Le statut
  reste **Proposé**.

## Contexte

Le gate final H2-B/H2-F (`rag_pedago.imports.h2b_coverage_report`) doit
prouver qu'une autorisation `ScopeAuthorizationArtifactV2` a réellement été
approuvée par un humain habilité, distinct de son auteur, sur un HEAD exact.

Trois faits rendent cette preuve impossible en l'état :

1. `rag-pedago` n'appelle jamais le réseau. C'est une propriété voulue du
   plan de contrôle pédagogique, pas une limitation à contourner : un gate
   qui dépendrait de la disponibilité de GitHub deviendrait vert ou rouge
   pour des raisons étrangères au corpus.
2. `rag-pedago` n'importe jamais `rag-engine` (AGENTS.md, ADR-0001). La
   vérification live d'ADR-0025 (`verify_review`,
   `evaluate_trusted_review`) vit dans le plan de données et l'outillage de
   gouvernance ; elle ne peut pas être appelée depuis le plan de contrôle.
3. Un JSON d'autorisation, même canonique, ne porte **aucune** trace de sa
   revue. Sa validation structurelle et sémantique — protocole, décision,
   scope, allowlist, fenêtre de validité, digest — est entièrement
   satisfaisable par un fichier fabriqué localement. `rag-pedago` pouvait
   donc rendre `coverage_complete=true` sur une autorisation que personne
   n'avait jamais relue.

Le troisième point est le défaut réel : ce n'est pas une dette, c'est un
gate vert non démontré au sens de la règle « Qualité des métriques »
d'AGENTS.md.

## Décision

Introduire un **reçu de liaison de revue** canonique et signé,
`ScopeAuthorizationReviewBindingV1`, qui transporte hors ligne le résultat
d'une vérification en ligne déjà effectuée par le vérificateur canonique
d'ADR-0025.

```text
GitHub live review
  → vérificateur en ligne d'ADR-0025 (verify_review / evaluate_trusted_review)
  → reçu de liaison canonique signé (producteur, plan de données)
  → preuve scellée versionnée (fichier JSON, commitée avec le corpus)
  → vérificateur hors ligne (packages/contracts, appelé par rag-pedago)
  → gate final H2-B/H2-F
```

### Responsabilités

| Composant | Rôle |
|---|---|
| `scripts/github/trusted_human_review.py` (ADR-0025) | seule autorité de décision sur une review GitHub. Inchangé. |
| `rag-engine` — `ingestion_control.github_authority.verify_review` | seule frontière réseau. Inchangée. |
| `rag-engine` — `ingestion_worker.issue_review_binding_cli` | **producteur** : réexécute la vérification live, relit le blob d'autorisation au HEAD approuvé, puis émet et signe le reçu. |
| `packages/contracts` — `nexus_contracts.review_binding` | contrat partagé : modèle, canonicalisation, digest, signature, vérification, ancre de confiance. Aucun réseau, aucune E/S. |
| `rag-pedago` — `imports.h2b_coverage_report` | **consommateur** : vérifie le reçu hors ligne et le confronte octet à octet à l'autorisation qu'il valide. |

`rag-pedago` importe `nexus_contracts`, jamais `rag-engine` : la séparation
d'ADR-0001 est préservée. Le contrat partagé est la seule chose qui traverse
la frontière, comme pour le contrat de retrieval.

### Liaison

Le reçu est inutilisable ailleurs que là où il a été produit. Il nomme, et
le vérificateur hors ligne recompare :

- le dépôt, la PR, la `base_ref`, le `base_sha` et le `head_sha` exacts ;
- le chemin Git canonique de l'autorisation, dérivé de son identifiant ;
- le SHA-256 des octets canoniques de l'autorisation **et** le SHA-1
  d'objet blob Git de ces mêmes octets — deux identités indépendantes des
  mêmes octets ;
- l'identifiant et la décision de l'autorisation ;
- l'identifiant de review, le login du relecteur, sa permission vérifiée et
  le login de l'auteur — l'égalité auteur/relecteur est un refus ;
- le protocole et le digest du challenge `NEXUS-TRUSTED-REVIEW-V1`, lui-même
  dérivé du couple (dépôt, PR, base_ref, base_sha, head_sha, auteur,
  relecteur) : un challenge ne peut donc pas être recyclé d'un HEAD à un
  autre ;
- l'instant de vérification, la version du vérificateur et une date
  d'expiration : une preuve de revue vieillit.

Changer un seul de ces champs change le digest canonique, donc invalide la
signature.

### Ancre de confiance

Aucun mécanisme de signature de gouvernance n'existe dans le dépôt.
`nexus_contracts.profile_auth` signe des jetons de profil élève en HMAC —
un **secret partagé**, structurellement inadapté ici : le vérificateur hors
ligne pourrait alors forger les reçus qu'il vérifie.

Décision : **Ed25519**, via `cryptography` (déjà présent dans
`services/rag-engine`, ajouté explicitement aux dépendances de
`packages/contracts` et `services/rag-pedago`). Aucune primitive
cryptographique artisanale : la canonicalisation réutilise celle
d'`authority_artifacts`, la signature est celle de la bibliothèque.

- La clé privée n'est fournie au producteur que par la variable
  d'environnement `NEXUS_REVIEW_BINDING_SIGNING_KEY` (secret CI), jamais
  lue depuis un fichier du dépôt, jamais générée automatiquement, jamais
  imprimée.
- La clé publique est déclarée dans un fichier d'ancre de confiance
  versionné, lu au **chemin canonique gouverné** (§ 5) — jamais passé en
  argument en production.
- Chaque clé porte un `environment` explicite (`production` ou `test`).
  **Le mode production refuse toute clé `test`**, et le mode test refuse
  toute clé `production` : une clé de fixture ne peut jamais valider un
  gate final, et la barrière est mesurée par un test dédié.
- Aucune clé publique de production fictive n'est écrite dans ce dépôt.
  L'ancre de production reste à provisionner ; tant qu'elle ne l'est pas,
  le gate final ne peut pas être vert en mode production. C'est une
  barrière de go-live explicite, distincte de la complétude du code.

### Mode final et mode répétition

Le gate expose deux modes explicitement nommés :

- `production` — exige l'autorisation, le reçu, l'ancre de confiance et le
  registre de révocation. Seul mode capable de produire
  `coverage_complete=true`.
- `rehearsal` — accepte une ancre de test, et **ne peut jamais** produire
  un verdict final vert : le rapport porte `binding_environment="test"` et
  la complétude reste refusée.

## 5. Chemins gouvernés — ancre et registre de révocation

*Amendement du 2026-08-11, constats F1 et F2.*

La version initiale de cet ADR laissait l'opérateur **désigner** l'ancre de
confiance (`--authority-trust-anchor`) et le registre de révocation
(`--authority-revocations`). C'était le défaut résiduel : celui qui choisit
le fichier déclarant quelles clés sont dignes de confiance décide, de fait,
de la confiance elle-même. Une clé qui s'auto-déclare `environment:
"production"` dans un fichier arbitraire n'a aucune autorité — encore
faut-il que ce fichier ne soit jamais ouvert.

Deux chemins deviennent **canoniques et gouvernés**, versionnés dans Git et
donc eux-mêmes soumis à revue humaine :

```text
governance/trust-anchors/review-binding-v1.json
governance/trust-anchors/authorization-revocations-v1.json
```

Ils sont résolus depuis une racine dérivée **exclusivement de
l'emplacement du code** (`Path(__file__).resolve().parents[4]`). En mode
`production` :

- fournir `--authority-trust-anchor` ou `--authority-revocations` est un
  **refus explicite**, jamais une valeur ignorée en silence ;
- `NEXUS_REPOSITORY_ROOT` ne redirige rien. Cette variable existait déjà et
  était elle-même un vecteur de contournement : elle est désormais ignorée
  pour tout chemin gouverné ;
- un symlink est refusé, sur le fichier **comme sur chaque composant** du
  chemin sous la racine — un lien sur un répertoire intermédiaire redirige
  aussi efficacement qu'un lien sur le fichier ;
- le chemin résolu doit être exactement le chemin canonique attendu, et
  toute sortie de la racine gouvernée est refusée ;
- l'absence du fichier est un **refus**, jamais un défaut permissif.

**Garde de packaging.** La dérivation par remontée n'est vraie que dans un
checkout du dépôt. Installé en wheel, le même calcul désignerait un
répertoire arbitraire de `site-packages`, où une ancre déposée ferait
autorité. Le gate vérifie donc que la racine porte les marqueurs du dépôt
(`AGENTS.md`, `services/rag-pedago`, `docs/adr`) et refuse sinon. Ce gate
est un outil de checkout, pas un artefact déployable — et il le dit.

**Registre de révocation.** Schéma strict et versionné
(`NEXUS-AUTHORIZATION-REVOCATIONS-V1`), à deux clés : `protocol_version` et
`revoked_authorization_ids`. Une clé inconnue, un doublon d'identifiant ou
une version absente sont des refus. Un registre **gouverné vide est
valide** : « aucune autorisation révoquée » est une affirmation légitime, et
le fichier prouve que quelqu'un l'a affirmée. C'est l'*absence* de registre
qui ne l'est pas — elle ne distingue pas « rien n'est révoqué » de
« personne n'a regardé ». Le rapport publie donc
`AUTHORITY_REVOCATIONS_CHECKED=true|false`, et `coverage_complete` reste
faux quand la preuve manque.

En mode `rehearsal`, une fixture d'ancre et de registre reste autorisée ;
leur absence est visible (`false`) et ne peut jamais produire un verdict
final vert.

## 6. LOT42-V2 — la revue humaine désigne l'attribution publiée

*Amendement du 2026-08-11, constat F3.*

Un artefact de revue `LOT42-V1` ne nommait nulle part les quatre faits
d'attribution (`source_label`, `official`, `source_kind`, `type_doc`) qui
seraient effectivement publiés. L'humain approuvait donc une publication
sans jamais relire sa provenance. La migration 012 scellait bien ces faits
*après* attestation, mais rien ne prouvait que la valeur scellée était celle
qu'un humain avait vue.

`PublicationReviewArtifactV2` ajoute un champ **obligatoire** :

```python
attributed_facts_digest: StrictStr = Field(pattern=_HEX64)
```

Un artefact V2 sans ce champ n'est pas « invalide » : il est
**irreprésentable**. Le champ entre dans les octets canoniques, donc dans
le digest, donc dans le chemin canonique et dans le challenge soumis à
l'humain. Modifier l'attribution après la revue déplace le chemin canonique :
les octets approuvés ne sont plus là où l'attestation les cherche.

**Coexistence historique.** V1 n'est pas supprimé du contrat. Il reste
parsable pour l'audit, et il ne peut plus rien : ni être proposé à la revue,
ni produire une attestation, ni autoriser une publication. Il n'est **jamais
réétiqueté automatiquement** en V2, et aucun digest n'est fabriqué pour une
ligne V1. Une barrière unique, `require_publication_review_v2`, porte ce
refus pour tous les appelants qui autorisent quelque chose.

**Séquence transactionnelle** — writer et attestor partagent exactement la
même clé advisory et le même ordre de verrouillage :

```text
verrou advisory transactionnel de l'attribution
  → relecture de l'attribution sous ce verrou
  → égalité à trois voies :
        digest de l'artefact humainement revu
     == digest courant du plan de contrôle
     == digest enregistré dans publication_attestations
  → autres vérifications LOT42
  → INSERT de l'attestation V2
  → COMMIT (le verrou tombe implicitement)
```

Une mutation concurrente n'a donc que deux issues : elle précède la
relecture, et l'attestation est refusée pour digest divergent ; ou elle la
suit, et le trigger de la migration 012 refuse la mutation.

## 7. Migration 013 et versionnement du contrat partagé

*Amendement du 2026-08-11.*

La migration `013_lot42_v2_attribution_bound_reviews` remplace les
contraintes qui n'acceptaient que `LOT42-V1` dans
`publication_attestations` et `publication_commit_pins`, et impose
l'invariant propre à V2 :

- V2 ⇒ `attributed_facts_digest` présent ;
- V1 ⇒ `attributed_facts_digest` absent.

La colonne reste **nullable** : c'est le couple (version, digest) qui porte
l'invariant, pas la colonne seule. Une contrainte `NOT NULL` serait fausse —
elle invaliderait les lignes V1 historiques et ferait échouer la migration
sur une base peuplée. Le refus des *nouvelles* écritures V1 est donc une
règle applicative, pas un CHECK : une contrainte ne distingue pas une ligne
ancienne d'une ligne neuve.

**Rollback fail-closed.** S'il existe des lignes V2, revenir en arrière
n'aurait que trois issues, dont deux interdites : les supprimer (destruction
de preuve), les réétiqueter en V1 (mensonge), ou refuser. Le rollback
refuse, verrou pris avant toute modification, et ne change pas un octet.

**`nexus-contracts` passe de `0.7.0` à `0.8.0`.** Cette version contient :

1. l'ajout du protocole `review_binding` (additif) ;
2. l'ajout de la dépendance `cryptography` ;
3. une **rupture** du contrat `PublicationReviewArtifact` — champ
   obligatoire nouveau ;
4. le passage de LOT42-V1 à LOT42-V2.

Un incrément mineur suffit malgré la rupture : le paquet est en `0.x`, où
SemVer autorise les mineures à rompre, et ses seuls consommateurs sont les
services de ce monorepo, mis à jour dans le même changement. `1.0.0`
signifierait une stabilité d'API que ce contrat n'a pas encore.

`review_binding` n'est **pas** réexporté depuis `nexus_contracts.__init__` :
un consommateur qui n'utilise pas la gouvernance ne doit pas payer l'import
de `cryptography`.

## 8. Trois états distincts, jamais confondus

*Amendement du 2026-08-11.*

| État | Signification | Aujourd'hui |
|---|---|---|
| **Code ready** | Le code, les migrations et les tests sont complets et verts. | Atteint sous réserve de l'audit pré-commit. |
| **Provisioning ready** | La clé privée de production est provisionnée, l'ancre publique et le registre de révocation sont commités aux chemins gouvernés. | **Non atteint** — aucun de ces fichiers n'existe, et ce lot n'a pas le droit de les créer. |
| **Go-live ready** | Cet ADR est `Accepted`, et un corpus réel est autorisé. | **Non atteint.** |

Conséquence directe et voulue : tant que « provisioning ready » n'est pas
atteint, **aucun run en mode `production` ne peut être vert**. Ce n'est pas
une régression, c'est la barrière rendue effective.

## Conséquences

**Positives.** Le gate final ne peut plus devenir vert sur une autorisation
jamais relue. La vérification reste entièrement hors ligne et déterministe.
La frontière réseau reste unique (ADR-0025). Le reçu est rejouable et
auditable : il nomme tout ce sur quoi il s'appuie.

**Négatives, assumées.** Une nouvelle dépendance (`cryptography`) entre dans
`packages/contracts` et `services/rag-pedago`. Un secret de signature de
production doit être provisionné avant tout go-live — sans lui, aucune
preuve valide ne peut être émise. Un reçu expiré doit être réémis, ce qui
suppose que la PR d'autorisation reste approuvée à son HEAD.

**Non traité ici.** La rotation de clé et la révocation d'une clé
compromise se font en retirant l'entrée du fichier d'ancre de confiance,
qui est versionné et donc lui-même soumis à revue. Un mécanisme de
transparence (log append-only des reçus émis) n'est pas retenu à ce stade.

## Alternatives écartées

- **Appeler GitHub depuis `rag-pedago`** — viole la séparation d'ADR-0001 et
  rend le gate dépendant d'un service externe.
- **Importer `rag-engine` depuis `rag-pedago`** — interdit par AGENTS.md.
- **Copier les colonnes de `publication_attestations` dans un YAML** — une
  copie non signée est falsifiable par quiconque édite le fichier ; c'est
  exactement le défaut corrigé.
- **HMAC avec un secret partagé** — le vérificateur pourrait forger ce
  qu'il vérifie.
- **Signer avec la clé GPG d'un commit** — lie la preuve à un commit, pas à
  la review, à son relecteur ni à sa permission.
