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

Les deux motifs de blocage sur chaque dérivé sont `DERIVATIVE_PII_REVIEW_MISSING` et `REVOCATION_UNPROVEN` au niveau de la qualification indépendante successeur. Le checkpoint #300 prouve un état source à sa date ; il ne doit pas être converti implicitement en revue PII et révocation actuelle du texte dérivé. Sans accès aux checkpoints privés, le contrôle ajoute `CURRENTNESS_CHECKPOINT_MISSING=253` et refuse aussi le PASS ; le chemin local n'est donc pas une autorité.

Le rejeu exact utilise le venv isolé de ce worktree :

```bash
python scripts/go_live/student_derivative_pii_currentness_gate.py \
  --private-root "$NEXUS_STUDENT_PUBLIC_PRIVATE_ROOT" \
  --source-checkpoint-root "$NEXUS_PR300_CHECKPOINT_ROOT"
```

**TEST.** `python -m pytest -q scripts/tests/test_student_derivative_pii_currentness_gate.py` : 14 réussis. Les tests couvrent le cas positif synthétique et les refus sur le texte muté, le reçu muté, les pages exclues, un chunk sur page exclue, la preuve PII sur un autre SHA, la date absente, la révocation absente, le SHA de preuve #300 changé, un nombre de pages invalide et un index de preuves non scellé. `ruff check` sur les deux fichiers Python et `git diff --check` passent. Le cas positif synthétique prouve uniquement la logique du vérificateur, pas la disponibilité d'une vraie revue sur les 253 textes.

## Suite conditionnelle

Pour lever ce blocage, produire un contrôle PII indépendant sur les **253 textes exacts** et une attestation d'actualité/révocation de qualification qui relie chaque `source_pdf_sha256`, `derivative_content_sha256`, reçu de dérivation et les deux SHA de checkpoint. Toute modification d'octets exige un nouvel artefact, un nouveau SHA et une nouvelle qualification. Les preuves devront ensuite être scellées et soumises à l'autorité de publication successeur ; ce lot ne les invente pas. Aucun statut `PRODUCTION_READY` ou `GO_LIVE_READY` n'est établi ici.

## Écran PII déterministe et projection d'exclusion

**LOCAL READ-ONLY, 2026-10-10 13:36 UTC.** Le reçu [student_derivative_pii_pattern_screen_20261010.json](go_live/student_derivative_pii_pattern_screen_20261010.json) et son fichier `.sha256` scellent 253 textes exacts, soit 21 468 584 octets, avec la politique `pii_gate_policy.yml` SHA-256 `d09cbfd23a4fcc3a744cdaeddf60a22863dfe64e0cc4c26e375309b21984e484`. Le SHA-256 du reçu JSON est `7f5aeb26ee25d48e1d0abbdec2d3aeb2cc2ae6b975099177ea5d10ba1a18a40a`. Le reçu lie aussi le code du producteur et du scanner, le manifeste #300 et le registre #312. Aucun match ni contexte brut n'y figure.

Les 253 PDF du miroir privé ont été relus par SHA. Les 19 388 blocs textuels natifs retenus ont été comparés aux blocs exacts des PDF ; leurs octets et empreintes concordent avec les reçus #300. Les preuves #300 de scan complet du PDF et de ses annexes portent les mêmes SHA de source. Le scanner applique les **sept motifs** de la politique à tout le texte dérivé, y compris les métadonnées, sans allowlist générique. Il a trouvé 677 occurrences `phone_french` dans 12 artefacts ; chacune se situe intégralement dans la valeur `source_pdf_sha256` d'un en-tête ou d'une citation canoniques. Aucune occurrence n'est dans un bloc pédagogique natif ; aucun autre motif n'est déclenché. Ces 677 alertes sont donc des sous-chaînes numériques d'empreintes cryptographiques, pas des numéros de téléphone issus des passages. Les 12 artefacts ne sont pas exclus sur cette seule base.

Pour les 241 artefacts sans signal initial et les 12 dont tous les signaux sont structurellement expliqués, le reçu atteste uniquement `PATTERN_SCREEN_CLEAR_ONLY`. Il ne prouve pas qu'aucune donnée personnelle non couverte par ces regex n'existe, ni que la révocation est encore absente au moment d'une future publication. Le gate PII indépendant et l'attestation de révocation successeur restent donc **bloquants sur 253/253**. Le reçu ne porte aucun `pii_status=PASS`.

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

Le producteur rejette un match hors des plages SHA canoniques, une citation altérée, un PDF ou bloc source divergent. Son test ciblé couvre aussi un numéro placé dans un passage natif ou hors citation : ces cas restent non résolus. `pytest -q scripts/tests/test_scan_student_derivative_pii.py` : 6 réussis ; Ruff passe. Le rejeu des 253 PDF réels avec PyMuPDF 1.27.2.3 est sorti avec code 0, sans écrire dans le miroir.
