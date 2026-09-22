# Dossier PII — release `profile_gate_v2` : reconduction, non réouverture

> **Ce document est expurgé.** Aucune correspondance brute : ni extrait, ni
> valeur détectée, ni ligne de document. La mesure dont il découle n'en
> transporte aucune (`raw_pii_in_output: false`), et chaque justification
> humaine reproduite ici est contractuellement exempte de citation
> (`raw_pii_quoted: false`, vérifié par `nexus_contracts`).

## Ce que la mesure a réellement établi

Le scanner canonique signale **22 contenus, 48 signaux** sur les 315 du
candidat. Le croisement avec la gouvernance versionnée montre que **ces 22
contenus ont déjà été examinés et décidés**, un par un, par
`abenrhouma` le 2026-09-03, dans un ensemble de décisions
scellé par un reçu ADR-0035 qui se vérifie hors ligne.

Ce dossier ne rouvre donc pas 22 décisions. Il démontre que leurs
**conditions de reconduction sont satisfaites**, et isole le seul défaut
réel, qui n'est pas dans la revue mais dans l'attestation du candidat.

## Le défaut : une attestation aveugle, pas une attestation propre

`services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/pii_evidence.json`
déclare **486/486 `CLEARED`** et
`pii_detected: false` pour **tous** ses contenus — y compris les 22 que le
scanner canonique signale. Elle a été produite par un artefact différent :

| | Artefact | Empreinte | Verdict sur les 22 |
|---|---|---|---|
| Producteur de l'attestation | `production-profile-gate-v1` | `8ec8af5510a734c6…` | 22 × `CLEARED` |
| Scanner canonique | `services/rag-pedago/rag_pedago/imports/pii_scanner.py` | `388e3ed475625bc4…` | 22 signalés, 48 signaux |
| Déclaré par le manifeste du candidat | *(le canonique)* | `388e3ed475625bc4…` | — |
| Déclaré par les décisions humaines | *(le canonique)* | `388e3ed475625bc4…` | 22 × `APPROVED` |

Le manifeste du candidat et la revue humaine s'accordent sur le scanner
canonique. **Seule l'attestation scellée nomme l'autre artefact**, et c'est
elle qui sous-déclare. Le statut correct pour ces 22 contenus n'est pas
`CLEARED` mais `DETECTED_REVIEWED_ACCEPTED`, adossé à `decision_set_id` et
`review_bundle_sha256` — la voie qu'ADR-0047 prévoit exactement pour ce cas.

Une admission n'efface jamais la détection : `pii_detected` doit rester
`true`. C'est ce que `_require_admission_is_founded` impose au runtime.

## La revue antérieure, et sa vérification

| Élément | Valeur |
|---|---|
| Ensemble de décisions | `governance/pii-review-decisions/pii-review-2026-09-03-final.json` |
| Empreinte | `2b1974259b1ac4a2a21766b71f3ed586df22722cb969f07bdb3fb0bdaafda469` |
| Décisions | 23, toutes `APPROVED` — couvrant les 22 signalés |
| Reçu | `governance/pii-review-bindings/pii-review-2026-09-03-final.json` |
| Vérifié hors ligne | oui, contre l'ancre de production `review-binding-v1-2026-08-25` |
| Relecteur | `abenrhouma` (permission `write`) — PR #143, head `957e2c6d5775` |
| Révoqué | non (`pii-review-2026-09-03-final.json` absent des révocations) |
| **Expire le** | **2026-10-03T22:02:48.263884+00:00** |

Les octets du jeu de décisions sur disque sont **exactement** ceux
qu'exige le reçu, et leur relecture canonique stricte passe.

> ⚠️ **La seule contrainte temporelle du dossier.** Le reçu expire le
> 2026-10-03. Une publication postérieure à cette date exige une
> **nouvelle signature**, pas une nouvelle revue : les décisions, elles,
> ne portent pas d'échéance.

## Conditions de reconduction — vérifiées contenu par contenu

Le mandat ne permet de réutiliser une décision antérieure que si ses
conditions de reconduction sont **réellement** satisfaites. Chacune est
évaluée sur chacun des 22, contre la mesure du jour :

| Condition | Satisfaite |
|---|---|
| aucune justification ne cite de donnée brute | **22/22** |
| une décision existe pour ces octets exacts, et elle est `APPROVED` | **22/22** |
| aucune disposition `PERSONAL_DATA_PRESENT` | **22/22** |
| le nombre de signaux est identique | **22/22** |
| même politique de pages | **22/22** |
| même `policy_sha256` | **22/22** |
| la décision nomme le scanner qui a produit la mesure du jour | **22/22** |
| les classes de signal sont identiques | **22/22** |
| les pages signalées aujourd'hui sont celles qui ont été examinées | **22/22** |

**Aucune condition en défaut.** Le scanner n'a pas changé entre la revue et
la mesure : c'est le même fichier, au même SHA. Ce qui avait été lu comme
un « changement de scanner » était la divergence entre l'attestation
aveugle et tout le reste de la chaîne.

## Ce que l'humain avait tranché

| Disposition | Signaux |
|---|---|
| `FALSE_POSITIVE_TECHNICAL` | 18 |
| `SYNTHETIC_EXAMPLE` | 7 |
| `PUBLIC_INSTITUTIONAL_DATA` | 7 |

| Catégorie de justification | Contenus |
|---|---|
| `TECHNICAL_FALSE_POSITIVE` | 13 |
| `PEDAGOGICAL_EXAMPLE` | 4 |
| `INSTITUTIONAL_CONTACT` | 4 |
| `PUBLIC_OFFICIAL_PUBLICATION` | 1 |

Le signal le plus grave — l'unique `french_ssn` — a été examiné et
qualifié `FALSE_POSITIVE_TECHNICAL`, sur une page ouverte par le
relecteur. Il n'est pas laissé à une hypothèse.

## Ce qui reste vrai malgré la reconduction

- Les **293 contenus sans signal ne sont pas publiables pour autant** :
  les autres autorités et conditions restent applicables.
- La reconduction n'admet **rien en bloc** : elle s'appuie sur 22
  décisions individuelles, rendues sur 22 paquets de revue distincts.
- Tant que l'attestation du candidat n'est pas corrigée, les 22 contenus
  **ne sont pas autorisés à la nouvelle publication** : leur admission
  n'est fondée nulle part dans les octets qui seraient publiés.
- Une correction documentaire produirait de **nouveaux octets**, donc une
  nouvelle identité — et sortirait ces contenus du périmètre de la
  décision. Aucune n'est proposée ici.

## Dossier par contenu

### `703cbd759841…` — Le paradigme fonctionnel PDF - 404.66 Ko

- **Contenu** : `703cbd759841b016d5acac15df02a3c17ef273430e28f46fd5d9498b0606d3f5`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/NSI/04_EVALUATIONS_EXAMENS/2021/le-paradigme-fonctionnel-pdf-404-66-ko--703cbd7598.pdf`
- **Type documentaire** : `modalite_examen` — 17 pages
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 6 — pages 4
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `f07fae2c022e82c6…`
- **Énoncé** : Adresses mémoire internes Python générées par la fonction id() dans un cours didactique.
- **Dispositions** :
  - `french_ssn` page 4 → `FALSE_POSITIVE_TECHNICAL`
  - `phone_french` page 4 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `e20b73d10c46…` — Représentation des entiers naturels PDF - 167.2 Ko

- **Contenu** : `e20b73d10c46a2e681422756b7f981911d752fe8ae3721db4c0156a099070bdc`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/representation-des-entiers-naturels-pdf-167-2-ko--e20b73d10c.pdf`
- **Type documentaire** : `diaporama` — 8 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 5 — pages 2, 4, 5, 6
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `730e55cfcf0cc4a0…`
- **Énoncé** : Suite de chiffres décimaux et conversions en base octale dans un algorithme.
- **Dispositions** :
  - `phone_french` page 4 → `FALSE_POSITIVE_TECHNICAL`
  - `phone_french` page 5 → `FALSE_POSITIVE_TECHNICAL`
  - `phone_french` page 6 → `FALSE_POSITIVE_TECHNICAL`
  - `postal_address` page 2 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `28c92cd742c6…` — Modèle d'architecture de von Neumann PDF - 243.56 Ko

- **Contenu** : `28c92cd742c6bc29890360b79d2518ae1960076b8512e5ccfe40fd0fe3572f32`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/07_DIAPORAMAS_SUPPORTS/2019/modele-d-architecture-de-von-neumann-pdf-243-56-ko--28c92cd742.pdf`
- **Type documentaire** : `diaporama` — 8 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 4 — pages 5
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `335c057c87ef6ab8…`
- **Énoncé** : Représentation binaire d’instructions dans l’architecture de Von Neumann.
- **Dispositions** :
  - `phone_french` page 5 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `39c50431bf6b…` — Mutations de l’ADN et variabilité génétique - altérations du génome et cancérisation : présentation orale d’une stratégie de résolution de problème (sans support écrit, individuelle) PDF - 164.19 Ko

- **Contenu** : `39c50431bf6b80c403d253eaf48e95b3644b2c80e0e8decb928a53c6117141a1`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2021/mutations-de-l-adn-et-variabilite-genetique-alterations-du-genome-et-cancerisation-presentation-orale-d-une-strategie-de-resolutio--39c50431bf.pdf`
- **Type documentaire** : `modalite_examen` — 9 pages
- **Collections** : `rag_nexus_svt_premiere_specialite`
- **Signaux** : 3 — pages 7, 8, 9
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `PEDAGOGICAL_EXAMPLE`
- **Paquet de revue** : `166d1afe6ad92ba0…`
- **Énoncé** : En-têtes de grille pédagogique d’évaluation didactique sans identité réelle.
- **Dispositions** :
  - `student_name_pattern` page 7 → `SYNTHETIC_EXAMPLE`
  - `student_name_pattern` page 8 → `SYNTHETIC_EXAMPLE`
  - `student_name_pattern` page 9 → `SYNTHETIC_EXAMPLE`
- **Reconductible** : oui

### `461e89b1b1a2…` — Manipulation de tables PDF - 144.44 Ko

- **Contenu** : `461e89b1b1a24a83a1598fe3d55a1aa040d9e305f63b8348bc6042ce96d5687b`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/manipulation-de-tables-pdf-144-44-ko--461e89b1b1.pdf`
- **Type documentaire** : `diaporama` — 5 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 3 — pages 1
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `PEDAGOGICAL_EXAMPLE`
- **Paquet de revue** : `3e3c5d7d9679a68a…`
- **Énoncé** : Données tabulaires CSV didactiques de populations d’exemple international.
- **Dispositions** :
  - `postal_address` page 1 → `SYNTHETIC_EXAMPLE`
- **Reconductible** : oui

### `5a8d69d488b3…` — dossier de presse « eutrophisation » PDF - 1.54 Mo

- **Contenu** : `5a8d69d488b341c6d82e0bafbef8fc8ce920392681548e209532021684907f54`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/09_AUTRES/2014/dossier-de-presse-eutrophisation-pdf-1-54-mo--5a8d69d488.pdf`
- **Type documentaire** : `autre` — 17 pages
- **Collections** : `rag_nexus_svt_premiere_specialite`, `rag_nexus_svt_terminale_specialite`
- **Signaux** : 3 — pages 17
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `INSTITUTIONAL_CONTACT`
- **Paquet de revue** : `f4723015f6364a74…`
- **Énoncé** : Contacts presse officiels de l’Agence de l’eau Seine-Normandie dans un dossier de presse.
- **Dispositions** :
  - `email_address` page 17 → `PUBLIC_INSTITUTIONAL_DATA`
  - `phone_french` page 17 → `PUBLIC_INSTITUTIONAL_DATA`
- **Reconductible** : oui

### `d05da0bb13bd…` — Sécurisation des communications PDF - 874.59 Ko

- **Contenu** : `d05da0bb13bdad4745e0310f24bdab1bcd7df5bfa0a99fbc7ae4238898e220b2`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/03_RESSOURCES_ACCOMPAGNEMENT/2021/securisation-des-communications-pdf-874-59-ko--d05da0bb13.pdf`
- **Type documentaire** : `ressource_officielle` — 12 pages
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 3 — pages 7
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `c17aa1a59c3107f8…`
- **Énoncé** : Opérations binaires logiques de chiffrement avec l’opérateur booléen XOR.
- **Dispositions** :
  - `postal_address` page 7 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `2d0745ca845f…` — Des ressources numériques pour accompagner l’étude des œuvres au programme, Le roman et le récit du Moyen Age au XXIe siècle PDF - 177.98 Ko

- **Contenu** : `2d0745ca845f8e30192d5c59aacb9fd6f60bcdb27007b00155107aa65c25e120`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/_MULTI_DISCIPLINES/01_PROGRAMMES_OFFICIELS/2023/des-ressources-numeriques-pour-accompagner-l-etude-des-uvres-au-programme-le-roman-et-le-recit-du-moyen-age-au-xxie-siecle-pdf-177--2d0745ca84.pdf`
- **Type documentaire** : `ressource_officielle` — 5 pages
- **Collections** : `rag_nexus_hlp_premiere_specialite`, `rag_nexus_hlp_terminale_specialite`
- **Signaux** : 2 — pages 5
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `28c74f2a455497ef…`
- **Énoncé** : Identifiants et dates de textes réglementaires publiés au Journal Officiel.
- **Dispositions** :
  - `phone_french` page 5 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `3f1ab328a0c1…` — Variation génétique et santé - Risque de transmission de la mucoviscidose chez un couple dont l'homme est hétérozygote composite PDF - 2.13 Mo

- **Contenu** : `3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/09_AUTRES/2020/variation-genetique-et-sante-risque-de-transmission-de-la-mucoviscidose-chez-un-couple-dont-l-homme-est-heterozygote-composite-pdf--3f1ab328a0.pdf`
- **Type documentaire** : `autre` — 13 pages
- **Collections** : `rag_nexus_svt_premiere_specialite`
- **Signaux** : 2 — pages 8, 9
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `PUBLIC_OFFICIAL_PUBLICATION`
- **Paquet de revue** : `a34996923f487d8f…`
- **Énoncé** : Adresse publique institutionnelle du rectorat de Créteil et exemple didactique.
- **Dispositions** :
  - `postal_address` page 8 → `PUBLIC_INSTITUTIONAL_DATA`
  - `postal_address` page 9 → `SYNTHETIC_EXAMPLE`
- **Reconductible** : oui

### `936c1e54b109…` — Les circuits PDF - 4.51 Mo

- **Contenu** : `936c1e54b1099bfb06a30ed68c743c9e3d1b51db4158ef7e5a4ae786caad080a`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/09_AUTRES/2021/les-circuits-pdf-4-51-mo--936c1e54b1.pdf`
- **Type documentaire** : `autre` — 39 pages
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 2 — pages 12, 14
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `9880e8355dc85664…`
- **Énoncé** : En-tête de tableau descriptif de microprocesseurs et référence bibliographique.
- **Dispositions** :
  - `postal_address` page 14 → `FALSE_POSITIVE_TECHNICAL`
  - `student_name_pattern` page 12 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `ebe2d96d2460…` — Règlement 2026-2027 PDF - 202.78 Ko

- **Contenu** : `ebe2d96d24600df85e16b67f7185657026e4b1c59010216cbfd99bf657048544`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/20_TRANSITION_OU_ACTUEL/DGEMC/09_AUTRES/2026/reglement-2026-2027-pdf-202-78-ko--ebe2d96d24.pdf`
- **Type documentaire** : `autre` — 4 pages
- **Collections** : `rag_nexus_dgemc_terminale_option`
- **Signaux** : 2 — pages 1, 3
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `INSTITUTIONAL_CONTACT`
- **Paquet de revue** : `d195310a5cb08428…`
- **Énoncé** : Coordonnées publiques de l’Ordre des Avocats de Paris figurant au règlement officiel.
- **Dispositions** :
  - `email_address` page 3 → `PUBLIC_INSTITUTIONAL_DATA`
  - `postal_address` page 1 → `PUBLIC_INSTITUTIONAL_DATA`
- **Reconductible** : oui

### `f21c80ab3aaa…` — Manipulation de tables avec la bibliothèque Pandas PDF - 146.17 Ko

- **Contenu** : `f21c80ab3aaa9084fe631f7c38d6ca1451f77c529f8ab2d62296817741bf8963`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/manipulation-de-tables-avec-la-bibliotheque-pandas-pdf-146-17-ko--f21c80ab3a.pdf`
- **Type documentaire** : `diaporama` — 5 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 2 — pages 3
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `PEDAGOGICAL_EXAMPLE`
- **Paquet de revue** : `7f23560ce1202a29…`
- **Énoncé** : Données démographiques didactiques d’exercice d’analyse tabulaire avec Pandas.
- **Dispositions** :
  - `postal_address` page 3 → `SYNTHETIC_EXAMPLE`
- **Reconductible** : oui

### `f636ef6038c2…` — Calculabilité et décidabilité PDF - 433.14 Ko

- **Contenu** : `f636ef6038c2379502bae01d5fdf06556aea70500a42b7adf9bd9f3996fe1d13`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/NSI/03_RESSOURCES_ACCOMPAGNEMENT/2020/calculabilite-et-decidabilite-pdf-433-14-ko--f636ef6038.pdf`
- **Type documentaire** : `ressource_officielle` — 7 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 2 — pages 7
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `d1978234a97afdde…`
- **Énoncé** : Constantes numériques intervenant dans des équations de calculabilité et décidabilité.
- **Dispositions** :
  - `phone_french` page 7 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `04bf557a574c…` — La conservation des génomes - stabilité génétique et évolution clonale – remobiliser des prérequis et présentation orale PDF - 1.19 Mo

- **Contenu** : `04bf557a574c4d553fab35eb3175f6f638dd129ffa785ca640367ae5c109881c`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2021/la-conservation-des-genomes-stabilite-genetique-et-evolution-clonale-remobiliser-des-prerequis-et-presentation-orale-pdf-1-19-mo--04bf557a57.pdf`
- **Type documentaire** : `modalite_examen` — 9 pages
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1 — pages 9
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `45a43f576513c4ae…`
- **Énoncé** : Identifiant technique de ressource vidéo extrait d’une URL didactique.
- **Dispositions** :
  - `postal_address` page 9 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `0dda163a7922…` — Former les élèves à des techniques de biologie moléculaire et de bioinformatique et appréhender le concept d'holobionte PDF - 5.31 Mo

- **Contenu** : `0dda163a792284e1e0df97c0ee72e8c04722bd145684db49a7095cb3b8e6ddc3`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/09_AUTRES/2020/former-les-eleves-a-des-techniques-de-biologie-moleculaire-et-de-bioinformatique-et-apprehender-le-concept-d-holobionte-pdf-5-31-m--0dda163a79.pdf`
- **Type documentaire** : `autre` — 43 pages
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1 — pages 4
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `c4a49fa0b9580b34…`
- **Énoncé** : Format de date d’un texte réglementaire officiel sans caractère téléphonique.
- **Dispositions** :
  - `phone_french` page 4 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `28f92cfe1c81…` — Écriture de tests PDF - 543.48 Ko

- **Contenu** : `28f92cfe1c81f2a4bab17aa2a9bff9a05f43a265ecad03214fe452a4ac53202d`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/NSI/03_RESSOURCES_ACCOMPAGNEMENT/2021/ecriture-de-tests-pdf-543-48-ko--28f92cfe1c.pdf`
- **Type documentaire** : `ressource_officielle` — 25 pages
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 1 — pages 7
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `00111e8de5eb6d52…`
- **Énoncé** : Constante numérique issue d’un code source de test unitaire Python.
- **Dispositions** :
  - `postal_address` page 7 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `447bdee89af9…` — Types construits en Python PDF - 159.07 Ko

- **Contenu** : `447bdee89af9f0ab07460bd279f81647824c2d91ba7be1eff6daa133c5e8467d`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/types-construits-en-python-pdf-159-07-ko--447bdee89a.pdf`
- **Type documentaire** : `diaporama` — 9 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 1 — pages 3
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `0d43c4edc7a59f9f…`
- **Énoncé** : Coordonnées numériques d’exemple dans un script de calcul géométrique.
- **Dispositions** :
  - `phone_french` page 3 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `62d9ac283408…` — Qu'est-ce que la monnaie et comment est-elle créée ? PDF - 531.52 Ko

- **Contenu** : `62d9ac2834082bce93300fd19cc042595fcd506e94c9cabc80bb942c2d798380`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/SES/03_RESSOURCES_ACCOMPAGNEMENT/2019/qu-est-ce-que-la-monnaie-et-comment-est-elle-creee-pdf-531-52-ko--62d9ac2834.pdf`
- **Type documentaire** : `ressource_officielle` — 8 pages
- **Collections** : `rag_nexus_ses_premiere_specialite`
- **Signaux** : 1 — pages 8
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `INSTITUTIONAL_CONTACT`
- **Paquet de revue** : `9b4aa1a1da57b2fe…`
- **Énoncé** : Adresse postale publique de la Cité de l’économie Banque de France.
- **Dispositions** :
  - `postal_address` page 8 → `PUBLIC_INSTITUTIONAL_DATA`
- **Reconductible** : oui

### `6a7942128b84…` — La question de grammaire de l’épreuve anticipée orale de français : précisions sur sa définition

- **Contenu** : `6a7942128b8404ac0b98e819c0f1482a6bac353bd2ea5a6269f7081676a65150`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/FRANCAIS/01_PROGRAMMES_OFFICIELS/2022/la-question-de-grammaire-de-l-epreuve-anticipee-orale-de-francais-precisions-sur-sa-definition--6a7942128b.pdf`
- **Type documentaire** : `modalite_examen` — 4 pages
- **Collections** : `rag_nexus_hlp_premiere_specialite`
- **Signaux** : 1 — pages 3
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `b957f39fa3029dcb…`
- **Énoncé** : Numéro de référence didactique dans un exemple de question de grammaire.
- **Dispositions** :
  - `postal_address` page 3 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `93b7e446273c…` — Diversité et unité des langages de programmation PDF - 161.08 Ko

- **Contenu** : `93b7e446273c0d36863ab8f86a39fb91dccb920ebd00e5be020f559253f9a17d`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/07_DIAPORAMAS_SUPPORTS/2019/diversite-et-unite-des-langages-de-programmation-pdf-161-08-ko--93b7e44627.pdf`
- **Type documentaire** : `diaporama` — 9 pages
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 1 — pages 5
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `TECHNICAL_FALSE_POSITIVE`
- **Paquet de revue** : `5b3ebeb109d1f922…`
- **Énoncé** : Déclaration de constante et longueur de tableau dans un programme Cobol d’exemple.
- **Dispositions** :
  - `postal_address` page 5 → `FALSE_POSITIVE_TECHNICAL`
- **Reconductible** : oui

### `96e887c34c0d…` — Placer les élèves en démarche de projet pour comprendre et évaluer une action climatique PDF - 333.91 Ko

- **Contenu** : `96e887c34c0d7db5500632090ee0119d1366d2667217818b65d00a316d3ae329`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2020/placer-les-eleves-en-demarche-de-projet-pour-comprendre-et-evaluer-une-action-climatique-pdf-333-91-ko--96e887c34c.pdf`
- **Type documentaire** : `modalite_examen` — 13 pages
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1 — pages 10
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `PEDAGOGICAL_EXAMPLE`
- **Paquet de revue** : `5abcb75f70d1f822…`
- **Énoncé** : Désignation didactique générique des rôles pédagogiques élève et enseignant.
- **Dispositions** :
  - `student_name_pattern` page 10 → `SYNTHETIC_EXAMPLE`
- **Reconductible** : oui

### `e1309f6255fb…` — Trajectoires et stratégies d’atténuation PDF - 1.43 Mo

- **Contenu** : `e1309f6255fbbc93d554c71b0ab2e98d176d27870edd15432d1b48a614d57294`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2020/trajectoires-et-strategies-d-attenuation-pdf-1-43-mo--e1309f6255.pdf`
- **Type documentaire** : `modalite_examen` — 17 pages
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1 — pages 9
- **Attestation du candidat** : `CLEARED`, `pii_detected: false` → attendu `DETECTED_REVIEWED_ACCEPTED`
- **Décision du 2026-09-03** : **APPROVED** par `abenrhouma` — `INSTITUTIONAL_CONTACT`
- **Paquet de revue** : `89af2cfd443ce48c…`
- **Énoncé** : Numéro vert institutionnel gratuit d’information et d’orientation publique.
- **Dispositions** :
  - `phone_french` page 9 → `PUBLIC_INSTITUTIONAL_DATA`
- **Reconductible** : oui

---

Index lisible par machine : `docs/reports/evidence-index/pii_reconduction_dossier_profile_gate_v2_20260922.json`
