# Wave 0 — Français d'abord, Maths en revue contrôlée

## Statut et objectif

Conception approuvée par l'instruction Nexus Réussite du 12 août 2026.
Le minimum livrable est la publication du PDF Français 3e scellé dans un
PostgreSQL/pgvector staging réel. La quarantaine du PDF Maths original reste
immuable et ne participe à aucune décision sur le SHA Français.

## Architecture retenue

Un `VerifiedPedagogicalPlacementResolver` charge le catalogue H2-E existant,
la preuve currentness Wave 0 et les profils Nexus versionnés. Il exige un SHA,
un chemin physique et un placement logique uniques, puis rend un
`VerifiedPedagogicalPlacement` immuable avec les digests du catalogue, du
manifest, de la preuve currentness et du profil.

Le même résultat gouverne la conformité du Classifier, le `source_path` des
droits dans Worker A, la construction de l'`EligiblePlacement` et le
`source_path` des droits dans Worker B. Sans résultat exact, le Classifier
conserve ses trois valeurs non vérifiées et le QualityAgent refuse le routage.

La preuve PII originale est chargée sans modification. Sa table par SHA rend
`CLEARED` pour Français et `QUARANTINED_PII` pour le Maths original ; aucune
agrégation de batch ne peut transformer la seconde ligne en refus de la
première.

## Phase B

Le job `publication_resume` nomme l'attestation LOT42 exacte. Cette identité
est confrontée dans `verify_publication_attestation` avant le premier CAS
`NEEDS_REVIEW -> REVIEWED`, puis propagée à l'ancre
`attempt_retrieval_eligible_transition`. Les lectures/preflights sont committés
avant le publisher afin que les connexions control et produit soient idle.

Le staging utilise `LocalGitHub`, les protocoles LOT41A-V2/LOT42-V2 et un
embedder déterministe. Cela ne fabrique aucune approbation de production.

## Maths

Deux flux de lecture bornés tournent en parallèle : reproduction et
classification locale du signal sans divulgation, et sélection/scan d'au plus
trois alternatives officielles. La preuve originale n'est jamais éditée. Une
éventuelle décision `FALSE_POSITIVE` est consignée dans une nouvelle preuve
liée au scan source ; `TRUE_PII` ou `UNCERTAIN` maintient la quarantaine et
fait basculer sur l'alternative la mieux classée et PII-cleared.

## Tests et limites

TDD couvre le mapping externe `3e -> Niveau.troisieme`, les dérives
SHA/path/manifest/année, l'ambiguïté de placement, le défaut fermé du
Classifier, la provenance `CLASSIFIED`, les chemins de droits A/B, le mauvais
UUID d'attestation sans transition, les états de transaction et la
déduplication. Aucun modèle réel ni `/search/v2` n'est entrepris avant le
premier chunk Français.
