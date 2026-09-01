# ADR-0047 — Décisions humaines de revue PII, par contenu, scellées et liées à la revue

- Statut : Proposé (2026-09-02). Devient Accepté par une review humaine
  `APPROVED` du Code Owner selon ADR-0025, sur le HEAD exact de la PR qui le
  porte, avec le challenge `NEXUS-TRUSTED-REVIEW-V1` sur une ligne autonome.
- Périmètre : chaîne PII producteur de release → preuve scellée → worker
  d'ingestion ; contrat `nexus-contracts` 0.15.0 (additif) ; gouvernance des
  décisions par contenu. Ce document n'approuve aucun contenu, n'active
  aucune ingestion et ne lève aucun verrou (`pii_absence_required` reste
  `true` sur tous les cas d'autorisation : la présence attestée d'une
  donnée personnelle reste bloquante ; ce que ce contrat rend admissible est
  une DÉTECTION revue et jugée non personnelle ou publique et licite).
- S'appuie sur : ADR-0025 (autorité de revue humaine GitHub), ADR-0035
  (liaison de revue scellée), ADR-0046 (foyer unique du prédicat de page),
  `services/rag-pedago/configs/pii_gate_policy.yml` (`gate_behavior.pii_detected
  → QUARANTINE`, `human_review_required: true`).

## Contexte

La politique PII scellée `pii_gate_policy_h2b_v5` exige une revue humaine pour
tout contenu où le scanner trouve une correspondance. Cette revue n'a jamais
été exécutée : le 29 août 2026, le producteur de release a été modifié pour
écrire `CLEARED / pii_detected=false` quelles que soient les correspondances
(« décision opérateur » inscrite en commentaire de code), et 23 contenus
détectés sous v5 sont servis aujourd'hui sous cette preuve. Le producteur
corrigé au LOT 1.2 écrit honnêtement `DETECTED_RECORDED` ; le worker
(`VerifiedPIIEvidenceRegistry.verify_content_clearance`) n'accepte que
`CLEARED / false`. Il n'existe aucun contrat pour un contenu détecté.

La décision de gouvernance du 2 septembre 2026 retient l'option PII-2 :
`DETECTED + HUMAN_REVIEW_APPROVED → admissible`, sous un statut explicite,
sans grandfathering des contenus servis, avec des décisions INDIVIDUELLES
liées au SHA, à la politique, au scanner, au paquet de revue, au reviewer
autorisé et à une justification structurée. L'autorité humaine est celle que
le mécanisme existant désigne ; aucun nouveau rôle n'est créé.

## Décision

### 1. Un ensemble de décisions par contenu, canonique et versionné

`nexus_contracts.pii_review_decisions` définit
`NEXUS-PII-REVIEW-DECISIONS-V1` :

- `PiiReviewDecisionV1` : `content_sha256`, `policy_id`, `policy_sha256`,
  `scanner_sha256`, `page_policy_id`, `page_policy_sha256`,
  `review_bundle_sha256`, `signal_classes` (triées, uniques, non vides),
  `signal_count > 0`, `pages` (strictement croissantes, ≥ 1), `decision ∈
  {APPROVED, REJECTED}`, `justification {category, statement, raw_pii_quoted
  = false}`, `reviewer_login`, `decided_at` (UTC, aware).
  Un `APPROVED` ne peut pas porter la catégorie `PERSONAL_DATA_PRESENT`. Une
  justification qui cite la matière brute est refusée.
- `PiiReviewDecisionSetV1` : `decision_set_id` (identifiant canonique),
  `corpus_manifest_sha256`, les instruments communs (politique, scanner,
  foyer de pages), `review_index_sha256` (empreinte de l'index des paquets),
  `decisions` triées par SHA, uniques, toutes liées aux mêmes instruments,
  chaque paquet de revue lié à un seul contenu.
- Chemin canonique dérivé de l'identifiant seul :
  `governance/pii-review-decisions/<decision_set_id>.json` ; forme canonique
  (`indent=2, sort_keys`, `\n` final) ; parse strict avec égalité octet à
  octet, comme les artefacts d'autorité.

Aucune décision n'est dérivable d'un compte de faux positifs, d'une
catégorie de triage, ni d'un titre de document : chaque décision est un
enregistrement individuel, rédigé par le reviewer.

### 2. Le paquet de revue, hors dépôt, figé par empreinte

Le reviewer statue sur un paquet généré depuis les octets exacts du PDF
(`NEXUS-PII-REVIEW-BUNDLE-V1`, `preparer_paquets_revue_pii.py`) : manifeste
nommant le contenu, la politique, le scanner, le foyer de pages et le
runtime ; chaque correspondance avec sa page, sa longueur et son contexte ;
le texte des pages concernées ; le PDF complet. Le paquet vit hors Git parce
qu'il porte la matière brute. Son empreinte est celle de son manifeste, qui
épingle chaque fichier : toute modification après décision l'invalide. Le
dépôt garde l'index des paquets (`pii_review_index_<date>.json`, sans
matière brute) et l'empreinte de chaque paquet dans la décision.

### 3. L'autorité humaine : le mécanisme existant, sans nouveau rôle

La décision positive est portée par le Code Owner désigné par ADR-0025 et
`scripts/github/trusted-reviewers.json` (`abenrhouma`). L'ensemble de
décisions est commité par une PR dédiée ; la review `APPROVED` porte sur le
HEAD exact avec le challenge ADR-0025 ; le reçu de liaison ADR-0035 est émis
par l'opérateur détenteur de la clé `review-binding-v1-2026-08-25` et
vérifié hors ligne.

Le reçu `NEXUS-REVIEW-BINDING-V1` est étendu de façon additive : la valeur
`authorization_decision = "APPROVE_PII_REVIEW_DECISIONS"` désigne un
ensemble de décisions PII, dont le chemin doit vivre sous
`governance/pii-review-decisions/` ; `require_matches_pii_review_decision_set`
confronte le reçu aux octets exacts de l'ensemble, à son identifiant, au blob
Git, au dépôt, à l'allowlist de reviewers et interdit l'auto-approbation. Les
reçus existants (`AUTHORIZE_INGESTION_SCOPE`) gardent leur sens.

Limite héritée, nommée : la séparation auteur/reviewer est vérifiée sur des
logins GitHub, pas sur des identités physiques (ADR-0025 ne dit pas
autrement). Un seul reviewer, un seul reçu.

### 4. Le statut de preuve et le worker (mis en œuvre APRÈS les décisions)

Le producteur émet, par contenu détecté : `DETECTED_REVIEWED_ACCEPTED /
pii_detected=true` si et seulement si une décision `APPROVED` existe dans
l'ensemble scellé pour ce SHA exact, la même `policy_sha256`, le même
`scanner_sha256`, le même `page_policy_sha256` et le même
`review_bundle_sha256` que l'index ; sinon `DETECTED_RECORDED`. La preuve PII
porte l'empreinte de l'ensemble de décisions et celle du reçu ;
`authority_bindings.json` les épingle.

Le worker accepte `CLEARED / false` ou `DETECTED_REVIEWED_ACCEPTED / true`
**avec** vérification de l'ensemble scellé et de son reçu pour le SHA exact ;
tout le reste est refusé. Jamais de règle globale sur `DETECTED_RECORDED`.

Ordre imposé : contrat → schéma → scellement → paquets → décisions humaines →
tests RED du worker → worker. Tests négatifs obligatoires : détection sans
revue, revue absente, revue `REJECTED`, revue d'un autre SHA, autre politique,
autre scanner, paquet modifié après décision, décision non scellée, reviewer
non autorisé, décision expirée, puis `APPROVED` exact et scellé → PASS.

### 5. Cardinalité : une conséquence

Le périmètre admissible est calculé DEPUIS les décisions : `297 +
approuvés` contenus, `455 + placements des approuvés`. `320 / 488` n'est
qu'une vérification a posteriori si les 23 sont approuvés ; il ne gouverne
rien.

## Conséquences

- La preuve `pii_evidence.json` servie aujourd'hui (486 × `CLEARED`) est une
  dette nommée ; la prochaine release la remplace par des statuts vrais.
- Un changement de politique ou de scanner rend les décisions caduques pour
  les contenus concernés : les empreintes liées ne correspondent plus, le
  producteur retombe en `DETECTED_RECORDED`, le worker refuse.
- `packages/contracts` passe en 0.15.0 (additif) ; une réécriture du reçu
  serait un nouveau protocole, pas cette ADR.

## Preuves

- `packages/contracts/tests/test_pii_review_decisions_contract.py`.
- `services/rag-pedago/tests/test_preparer_paquets_revue_pii.py`.
- Procédure : `docs/reports/lot_1_2_procedure_revue_pii.md`.
