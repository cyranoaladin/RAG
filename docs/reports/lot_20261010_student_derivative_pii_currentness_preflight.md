# Lot 2026-10-10 — préqualification PII et actualité des dérivés étudiants

## Périmètre

**STATIC.** Ce lot ajoute un vérificateur en lecture seule des 253 textes de la candidate #312, basé sur le `main` `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`. Il ne modifie ni le pack #300, ni la candidate, ni les PDF, ni staging, ni production. Le verdict ne remplace pas l'approbation exacte de #312, l'autorisation de scope ou une release publique successeur. Aucun texte privé ou checkpoint n'est copié dans Git.

Le vérificateur distingue trois identités : le SHA du PDF source, le SHA logique interne du checkpoint de provenance et le SHA des octets du fichier checkpoint. Le texte dérivé a son propre `content_sha256`. Le reçu #300 relie ces identités ; le SHA du téléchargement PDF n'est jamais comparé comme s'il était le SHA du texte. Le contrôle relit aussi la feuille candidate scellée par #300, le manifeste #312, les octets privés du texte, le reçu de dérivation, les pages et blocs retenus ou exclus, les groupes textuels, les pages des chunks, les champs d'attribution et les constats de révocation du checkpoint source.

Une décision PII sur le PDF source, y compris `PASS_BY_PR300_FULL_DOCUMENT_GATE`, ne donne pas un PASS sur le dérivé. Le PASS de cette porte exige une preuve indépendante sur l'intégralité des octets du texte dérivé, liée à son SHA et au reçu, ainsi qu'une attestation d'actualité et de révocation liée au checkpoint vérifié. Le lecteur refuse un dossier de preuves indépendant si son index et ses 253 empreintes ne sont pas liés à l'agrégat de release ; cet ancrage n'existe pas dans la candidate. Les entrées absentes ou incohérentes bloquent. Le vérificateur est pur au niveau de `assess_derivative` ; le lecteur de dépôt ne fait qu'ouvrir les fichiers et transmettre leurs octets.

## Résultat rejoué

**SEALED.** L'approbation #300 lie `index.json` à `ce7431919764fdf71fbcef90021c3adea365500e371e9d81594255188fecbfe7` et son manifeste candidat à `eb39f6cd0423e184e0932196770ee7ffeb24d1aecb915a526ccad67206a11d17`. L'agrégat #312 lie le registre de ses 253 artefacts à `9c402d143616b12049e3078252a763a359667d80adae9b3a8053fd213398126d`. Ces empreintes ont été recalculées sur les fichiers du worktree.

**LOCAL READ-ONLY, 2026-10-10 13:29 UTC.** Avec les 253 `.txt` du magasin privé #312 et les checkpoints privés #300 lus dans leur worktree d'origine, le contrôle retrouve 253/253 textes, reçus, décisions #300, dates d'attribution, exclusions de pages et lignages cohérents. Les 253 checkpoints source ont leurs deux empreintes concordantes ; les constats source portent `EXACT_CURRENT_SOURCE`, `currentness_status=PASS` et `revocation_status=PASS_CURRENT_OFFICIAL_PUBLICATION`, liés au SHA du PDF et à l'URL citée. Aucun checkpoint ni texte n'a été déplacé.

La sortie reste volontairement :

```text
ARTIFACT_COUNT=253
STRUCTURAL_PASS_COUNT=253
MISSING_CURRENTNESS_CHECKPOINT_COUNT=0
MISSING_DERIVATIVE_PII_REVIEW_COUNT=253
PUBLICATION_PASS_COUNT=0
PUBLICATION_BLOCKED_COUNT=253
VERDICT=BLOCKED
```

Les deux motifs de blocage sur chaque dérivé sont `DERIVATIVE_PII_REVIEW_MISSING` et `REVOCATION_UNPROVEN` au niveau de la qualification **dans la candidate #312**. Le checkpoint #300 prouve un état source à sa date ; il ne doit pas être converti implicitement en revue PII et révocation actuelle du texte dérivé. Sans accès aux checkpoints privés, le contrôle ajoute `CURRENTNESS_CHECKPOINT_MISSING=253` et refuse aussi le PASS ; le chemin local n'est donc pas une autorité. Les deux reçus indépendants produits ci-dessous ne modifient pas cet agrégat et restent à lier à un **nouveau manifeste successeur**.

Le rejeu exact utilise le venv isolé de ce worktree :

```bash
python scripts/go_live/student_derivative_pii_currentness_gate.py \
  --private-root "$NEXUS_STUDENT_PUBLIC_PRIVATE_ROOT" \
  --source-checkpoint-root "$NEXUS_PR300_CHECKPOINT_ROOT"
```

**TEST.** `python -m pytest -q scripts/tests/test_student_derivative_pii_currentness_gate.py` : 14 réussis. Les tests couvrent le cas positif synthétique et les refus sur le texte muté, le reçu muté, les pages exclues, un chunk sur page exclue, la preuve PII sur un autre SHA, la date absente, la révocation absente, le SHA de preuve #300 changé, un nombre de pages invalide et un index de preuves non scellé. `ruff check` sur les deux fichiers Python et `git diff --check` passent. Le cas positif synthétique prouve uniquement la logique du vérificateur, pas la disponibilité d'une vraie revue sur les 253 textes.

## Suite conditionnelle

Toute modification d'octets exige un nouvel artefact, un nouveau SHA et une nouvelle qualification. Les reçus PII et actualité ci-dessous sont préparatoires : leurs digests devront être ancrés et déréférencés par le vérificateur du **successeur public**, puis soumis à l'autorité de publication exacte. Le test `test_unsealed_independent_packets_are_rejected` garde #312 rouge si l'on tente de lui présenter un index indépendant sans ancrage. Aucun statut `PRODUCTION_READY` ou `GO_LIVE_READY` n'est établi ici.

## Écran PII déterministe et projection d'exclusion

**LOCAL READ-ONLY, 2026-10-10.** Le reçu [student_derivative_pii_pattern_screen_20261010.json](go_live/student_derivative_pii_pattern_screen_20261010.json) et son fichier `.sha256` scellent 253 textes exacts, soit 21 468 584 octets, avec la politique `pii_gate_policy.yml` SHA-256 `d09cbfd23a4fcc3a744cdaeddf60a22863dfe64e0cc4c26e375309b21984e484`. Le SHA-256 du reçu JSON final est `1a8a06a5e8d73fa4e7ae92c43dabb65744ecb0562384d72dd50a640af9f1e7a8`. Le reçu lie aussi le code du producteur et du scanner, le manifeste #300 et le registre #312. Aucun match ni contexte brut n'y figure.

Les 253 PDF du miroir privé ont été relus par SHA. Les 19 388 blocs textuels natifs retenus ont été comparés aux blocs exacts des PDF ; leurs octets et empreintes concordent avec les reçus #300. **Tous les autres octets** du dérivé ont été recoupés avec la disposition canonique des en-têtes, étiquettes de page, citations et séparateurs ; toute insertion libre bloque. Les preuves #300 de scan complet du PDF et de ses annexes portent les mêmes SHA de source. Le scanner applique les **sept motifs** de la politique à tout le texte dérivé, y compris les métadonnées, sans allowlist générique. Il a trouvé 677 occurrences `phone_french` dans 12 artefacts ; chacune se situe intégralement dans la valeur `source_pdf_sha256` d'un en-tête ou d'une citation canoniques. Aucune occurrence n'est dans un bloc pédagogique natif ; aucun autre motif n'est déclenché. Ces 677 alertes sont donc des sous-chaînes numériques d'empreintes cryptographiques, pas des numéros de téléphone issus des passages. Les 12 artefacts ne sont pas exclus sur cette seule base.

Pour les 241 artefacts sans signal initial et les 12 dont tous les signaux sont structurellement expliqués, ce premier reçu atteste uniquement `PATTERN_SCREEN_CLEAR_ONLY`. Il ne prouve pas qu'aucune donnée personnelle non couverte par ces regex n'existe, ni que la révocation sera encore absente au moment d'une future publication. Il ne porte aucun `pii_status=PASS`.

Si, par hypothèse prudente, les 12 artefacts initialement signalés étaient exclus sans tenir compte de la preuve structurelle, les comptes réels de cette projection seraient 11 collections non vides, 241 artefacts, 360 placements et 3 870 chunks ; elle n'a pas été appliquée. Le nombre d'artefacts signalés par collection égale ici le nombre de placements retirés dans cette collection ; un artefact peut contribuer à deux collections, de sorte que la somme de la colonne dépasse 12. La répartition serait :

| Collection | Placements retirés | Placements restants |
| --- | ---: | ---: |
| DGEMC terminale option | 0 | 6 |
| HGGSP première spécialité | 1 | 31 |
| HGGSP terminale spécialité | 1 | 27 |
| HLP première spécialité | 4 | 94 |
| HLP terminale spécialité | 3 | 70 |
| NSI première spécialité | 0 | 20 |
| NSI terminale spécialité | 2 | 32 |
| SES première spécialité | 2 | 24 |
| SES terminale spécialité | 2 | 23 |
| SVT première spécialité | 2 | 8 |
| SVT terminale spécialité | 0 | 25 |

Le producteur rejette un match hors des plages SHA canoniques, une citation altérée, un PDF ou bloc source divergent. Son test ciblé couvre aussi un numéro placé dans un passage natif ou hors citation : ces cas restent non résolus. `pytest -q scripts/tests/test_scan_student_derivative_pii.py` : 7 réussis ; Ruff passe. Le rejeu des 253 PDF réels avec PyMuPDF 1.27.2.3 est sorti avec code 0, sans écrire dans le miroir.

## Décision PII déterministe propre aux dérivés

La politique [derivative_pii_adjudication_policy_v1.yml](../../governance/student_public_rights/derivative_pii_adjudication_policy_v1.yml) fixe une décision fail-closed distincte. Elle exige, pour chaque dérivé, le statut source PII `CLEARED` du paquet #300 approuvé, le scan intégral du PDF source et de ses annexes, le SHA des octets PDF exacts, tous les blocs inclus de classe `SAFE_TEXT_CANDIDATE` recomparés au PDF, zéro OCR/image/rendu copié, le contrôle de **tous** les octets du dérivé et zéro signal PII non expliqué. Le producteur rejoue le contrôle privé ; il ne convertit pas un simple champ source en preuve sur un dérivé arbitraire.

Le reçu [student_derivative_pii_adjudication_20261010.json](go_live/student_derivative_pii_adjudication_20261010.json), SHA-256 `7bf534b50a7eef90ca34d52daa22293a835273b0b2abf556d48e976721d05dd0`, contient **253 décisions PII PASS sur 253**, chacune avec `evidence_sha256`, source PDF SHA, dérivé SHA, reçu de dérivation SHA, référence à la preuve source et à la politique. Aucun texte, match ou contexte brut n'y figure. Le PASS a la portée définie par cette politique déterministe : revue source #300 plus motifs connus sur tous les octets exacts. Il ne promet pas la détection de toute donnée personnelle imaginable. Il ne prouve ni droits futurs ni absence de révocation future, et n'active pas le candidat #312.

Les sabotages ciblés bloquent le PASS lorsqu'un statut PII source ou scan complet manque, qu'un bloc natif n'est plus vérifié, qu'une image ou l'OCR apparaît, qu'un passage n'est plus `SAFE_TEXT_CANDIDATE`, qu'un motif sort des SHA canoniques, ou que le SHA dérivé diffère. Le reçu du balayage doit en outre correspondre octet pour octet au rejeu, hors horodatage. Voir les tests `test_adjudicate_student_derivative_pii.py` et `test_scan_student_derivative_pii.py`.

## Source actuelle et révocation, constat frais

Une nouvelle capture navigateur des **15 pages de listes** Éduscol a obtenu 15 HTTP 200, avec HTML, texte, captures d'écran et reçus datés gardés en privé. Le producteur canonique a réinterrogé **383 URL PDF** en HTTPS avec timeout 20 s et pool de six. L'index privé de ce constat porte le SHA logique `878e7249984bfecd511deeb59fa0d42eea5b772cb9de46b9866e065c0745dfa9`, daté `2026-10-10T13:43:39.206Z` ; la population complète #300 comprend 296 sources exactes et 19 non prouvées. **Dans les 253 sources du candidat**, les 253 sont `EXACT_CURRENT_SOURCE`, currentness `PASS`, révocation `PASS_CURRENT_OFFICIAL_PUBLICATION` ; les 19 non prouvées sont hors de ce sous-ensemble. Aucun HTTP 403 n'est assimilé à une absence de droit.

Le reçu [student_derivative_source_currentness_20261010.json](go_live/student_derivative_source_currentness_20261010.json), SHA-256 `4882c95b47e807f0efe55ee5768637b47907af4d5f91e331a0e273acf684e62d`, recoupe pour chaque dérivé le SHA PDF exact et son URI avec le GET HTTP 200 frais, le lien dans le listing navigateur (dont HTML, texte et capture d'écran sont re-hashés), les références de révocation, les digests des anciens et nouveaux checkpoints, et une observation postérieure à la date d'attribution du candidat. Verdict de **constat à cette date : 253 PASS sur 253**. Les captures/checkpoints complets restent privés dans le répertoire `.private-source-refresh/` du worktree ayant exécuté le constat, hors de cette PR ; le rapport versionné n'en contient que les identités, horodatages et empreintes nécessaires à leur vérification. Un transfert vers un CAS privé durable, suivi d'un nouveau contrôle des octets, reste requis avant toute activation.

Le champ `successor_release_binding=NOT_YET_SEALED` interdit de lire ce constat comme une autorisation autonome. Le constructeur du successeur doit déplacer/rejouer les preuves privées dans son CAS, ancrer les digests des deux reçus dans le manifeste d'inclusion, vérifier les 253 lignes individuellement, puis réévaluer la fraîcheur si la publication est différée. #312 reste une candidate non activable et son gate ancien refuse un index indépendant non scellé.
