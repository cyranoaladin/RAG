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
- **Ne supersede rien** : les protocoles `NEXUS-TRUSTED-REVIEW-V1`,
  `LOT41A-V1/V2` et `LOT42-V1` conservent leur sens et leur représentation
  exacts.

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
  versionné, passé explicitement au gate.
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
