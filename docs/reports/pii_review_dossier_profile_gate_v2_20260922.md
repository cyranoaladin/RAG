# Dossier de revue PII — release `profile_gate_v2`, mesure du 2026-09-22

> **Ce document est expurgé.** Il ne contient aucune correspondance brute :
> ni extrait, ni valeur détectée, ni ligne de document. La mesure dont il
> découle n'en transporte aucune non plus (`raw_pii_in_output: false`). Ce
> qu'il porte : des références, des empreintes, des classes de signal, des
> numéros de page, et une hypothèse de qualification assortie de la
> question qui la tranche. **La lecture des pages elles-mêmes appartient à
> la revue**, sur le support contrôlé, jamais à ce dépôt.

## Ce que ce dossier est, et ce qu'il n'est pas

C'est une **mesure datée**, pas une décision d'admission. La politique n'a
pas changé ; le texte lu est identique à celui qu'avait lu la preuve
scellée (`characters_scanned` identique pour 315/315). **Le scanner, lui, a changé** : la preuve scellée déclare
avoir été produite par `8ec8af5510a734c6…`
(`production-profile-gate-v1`), alors que le fichier
courant — celui de cette mesure — hache `388e3ed475625bc4…`.

Une incohérence d'autorité s'y ajoute, et elle doit être traitée avec la
release candidate : le manifeste déclare
`authorities.pii_scanner_sha256 = 388e3ed475625bc4…`
— le scanner **courant** — pour une preuve produite par un autre. Rien au
runtime ne confronte ces deux valeurs : le worker ne vérifie que
l'empreinte de la preuve et celle de la politique.

Un verdict différent rendu par un scanner différent est une nouvelle
mesure, jamais une correction rétroactive de l'ancienne. Et une mention
`CLEARED` antérieure ne permet pas d'ignorer une information nouvelle.

**Un signal n'est pas une donnée personnelle problématique.** Il peut
demander une qualification de contexte — c'est l'objet de ce dossier.

## Règles de décision (ADR-0047)

- Aucune admission **en bloc** des 22, aucune conversion automatique en
  exclusions définitives.
- Tant qu'un signal obligatoire reste non résolu, **le contenu concerné
  n'est pas autorisé à la nouvelle publication**.
- Une décision antérieure n'est reconduite que si ses conditions de
  reconduction sont **réellement** satisfaites — le changement de scanner
  n'en est pas une.
- Les 293 contenus sans signal **ne sont pas publiables pour autant** :
  les autres autorités et conditions restent applicables.
- Une correction documentaire produit de **nouveaux octets**, donc une
  nouvelle identité et tous les contrôles correspondants.

## Références de la mesure

| Élément | Valeur |
|---|---|
| Artefact | `docs/reports/evidence-index/pii_rescan_profile_gate_v2_315_20260922.json` |
| Empreinte | `f449a2b8b1eba58e4083b0224ed2a557823e64e54cf48f334535310371d32030` |
| Mesuré le | 2026-09-22T08:17:53.024623+00:00 |
| Ensemble mesuré | `04b731e20a9ebd9dcd08f00fe5164891…` |
| Politique | `services/rag-pedago/configs/pii_gate_policy.yml` — `d09cbfd23a4fcc3a…` |
| Scanner | `services/rag-pedago/rag_pedago/imports/pii_scanner.py` — `388e3ed475625bc4…` |
| Foyer de pages | NEXUS-PDF-PAGE-POLICY-V1 — `82e1de44719bf06b…` |
| Runtime | python 3.12.3, pypdf 6.14.2 |
| Comptes | 315 mesurés, 293 sans signal, 22 signalés, 0 en erreur d'extraction |

Index lisible par machine : `docs/reports/evidence-index/pii_review_dossier_profile_gate_v2_20260922.json`

## Vue d'ensemble des 22 contenus signalés

| Classe de signal | Contenus | Hypothèse par défaut |
|---|---|---|
| `postal_address` | 12 | PUBLIC_INSTITUTIONAL_DATA |
| `phone_french` | 9 | FALSE_POSITIVE_TECHNICAL |
| `student_name_pattern` | 3 | SYNTHETIC_EXAMPLE |
| `email_address` | 2 | PUBLIC_INSTITUTIONAL_DATA |
| `french_ssn` | 1 | **aucune — inspection exigée** |

## Dossier par contenu

### `703cbd759841…` — Le paradigme fonctionnel PDF - 404.66 Ko

- **Contenu** : `703cbd759841b016d5acac15df02a3c17ef273430e28f46fd5d9498b0606d3f5`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/NSI/04_EVALUATIONS_EXAMENS/2021/le-paradigme-fonctionnel-pdf-404-66-ko--703cbd7598.pdf`
- **Type documentaire** : `modalite_examen` — 17 pages, 17 scannées
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 6

  - `french_ssn` — page(s) **4**
    - Hypothèse : **aucune par défaut**
    - À trancher : GRAVITÉ MAXIMALE — aucune hypothèse par défaut. Le motif capture-t-il un numéro de sécurité sociale réel, ou une suite de chiffres du document (identifiant, code, exemple) ? Cette page doit être ouverte avant toute décision.
  - `phone_french` — page(s) **4**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `e20b73d10c46…` — Représentation des entiers naturels PDF - 167.2 Ko

- **Contenu** : `e20b73d10c46a2e681422756b7f981911d752fe8ae3721db4c0156a099070bdc`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/representation-des-entiers-naturels-pdf-167-2-ko--e20b73d10c.pdf`
- **Type documentaire** : `diaporama` — 8 pages, 8 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 5

  - `phone_french` — page(s) **4, 5, 6**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?
  - `postal_address` — page(s) **2**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `28c92cd742c6…` — Modèle d'architecture de von Neumann PDF - 243.56 Ko

- **Contenu** : `28c92cd742c6bc29890360b79d2518ae1960076b8512e5ccfe40fd0fe3572f32`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/07_DIAPORAMAS_SUPPORTS/2019/modele-d-architecture-de-von-neumann-pdf-243-56-ko--28c92cd742.pdf`
- **Type documentaire** : `diaporama` — 8 pages, 8 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 4

  - `phone_french` — page(s) **5**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `39c50431bf6b…` — Mutations de l’ADN et variabilité génétique - altérations du génome et cancérisation : présentation orale d’une stratégie de résolution de problème (sans support écrit, individuelle) PDF - 164.19 Ko

- **Contenu** : `39c50431bf6b80c403d253eaf48e95b3644b2c80e0e8decb928a53c6117141a1`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2021/mutations-de-l-adn-et-variabilite-genetique-alterations-du-genome-et-cancerisation-presentation-orale-d-une-strategie-de-resolutio--39c50431bf.pdf`
- **Type documentaire** : `modalite_examen` — 9 pages, 9 scannées
- **Collections** : `rag_nexus_svt_premiere_specialite`
- **Signaux** : 3

  - `student_name_pattern` — page(s) **7, 8, 9**
    - Hypothèse : `SYNTHETIC_EXAMPLE`
    - À trancher : Les noms sont-ils ceux d'élèves fictifs d'un scénario pédagogique, ou ceux d'élèves réels apparaissant dans une copie ou une liste ?

### `461e89b1b1a2…` — Manipulation de tables PDF - 144.44 Ko

- **Contenu** : `461e89b1b1a24a83a1598fe3d55a1aa040d9e305f63b8348bc6042ce96d5687b`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/manipulation-de-tables-pdf-144-44-ko--461e89b1b1.pdf`
- **Type documentaire** : `diaporama` — 5 pages, 5 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 3

  - `postal_address` — page(s) **1**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `5a8d69d488b3…` — dossier de presse « eutrophisation » PDF - 1.54 Mo

- **Contenu** : `5a8d69d488b341c6d82e0bafbef8fc8ce920392681548e209532021684907f54`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/09_AUTRES/2014/dossier-de-presse-eutrophisation-pdf-1-54-mo--5a8d69d488.pdf`
- **Type documentaire** : `autre` — 17 pages, 17 scannées
- **Collections** : `rag_nexus_svt_premiere_specialite`, `rag_nexus_svt_terminale_specialite`
- **Signaux** : 3

  - `email_address` — page(s) **17**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle un contact institutionnel publié (rédaction, service, académie), ou l'adresse d'une personne identifiable ?
  - `phone_french` — page(s) **17**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `d05da0bb13bd…` — Sécurisation des communications PDF - 874.59 Ko

- **Contenu** : `d05da0bb13bdad4745e0310f24bdab1bcd7df5bfa0a99fbc7ae4238898e220b2`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/03_RESSOURCES_ACCOMPAGNEMENT/2021/securisation-des-communications-pdf-874-59-ko--d05da0bb13.pdf`
- **Type documentaire** : `ressource_officielle` — 12 pages, 12 scannées
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 3

  - `postal_address` — page(s) **7**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `2d0745ca845f…` — Des ressources numériques pour accompagner l’étude des œuvres au programme, Le roman et le récit du Moyen Age au XXIe siècle PDF - 177.98 Ko

- **Contenu** : `2d0745ca845f8e30192d5c59aacb9fd6f60bcdb27007b00155107aa65c25e120`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/_MULTI_DISCIPLINES/01_PROGRAMMES_OFFICIELS/2023/des-ressources-numeriques-pour-accompagner-l-etude-des-uvres-au-programme-le-roman-et-le-recit-du-moyen-age-au-xxie-siecle-pdf-177--2d0745ca84.pdf`
- **Type documentaire** : `ressource_officielle` — 5 pages, 5 scannées
- **Collections** : `rag_nexus_hlp_premiere_specialite`, `rag_nexus_hlp_terminale_specialite`
- **Signaux** : 2

  - `phone_french` — page(s) **5**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `3f1ab328a0c1…` — Variation génétique et santé - Risque de transmission de la mucoviscidose chez un couple dont l'homme est hétérozygote composite PDF - 2.13 Mo

- **Contenu** : `3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/09_AUTRES/2020/variation-genetique-et-sante-risque-de-transmission-de-la-mucoviscidose-chez-un-couple-dont-l-homme-est-heterozygote-composite-pdf--3f1ab328a0.pdf`
- **Type documentaire** : `autre` — 13 pages, 13 scannées
- **Collections** : `rag_nexus_svt_premiere_specialite`
- **Signaux** : 2

  - `postal_address` — page(s) **8, 9**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `936c1e54b109…` — Les circuits PDF - 4.51 Mo

- **Contenu** : `936c1e54b1099bfb06a30ed68c743c9e3d1b51db4158ef7e5a4ae786caad080a`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/09_AUTRES/2021/les-circuits-pdf-4-51-mo--936c1e54b1.pdf`
- **Type documentaire** : `autre` — 39 pages, 39 scannées
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 2

  - `postal_address` — page(s) **14**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?
  - `student_name_pattern` — page(s) **12**
    - Hypothèse : `SYNTHETIC_EXAMPLE`
    - À trancher : Les noms sont-ils ceux d'élèves fictifs d'un scénario pédagogique, ou ceux d'élèves réels apparaissant dans une copie ou une liste ?

### `ebe2d96d2460…` — Règlement 2026-2027 PDF - 202.78 Ko

- **Contenu** : `ebe2d96d24600df85e16b67f7185657026e4b1c59010216cbfd99bf657048544`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/20_TRANSITION_OU_ACTUEL/DGEMC/09_AUTRES/2026/reglement-2026-2027-pdf-202-78-ko--ebe2d96d24.pdf`
- **Type documentaire** : `autre` — 4 pages, 4 scannées
- **Collections** : `rag_nexus_dgemc_terminale_option`
- **Signaux** : 2

  - `email_address` — page(s) **3**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle un contact institutionnel publié (rédaction, service, académie), ou l'adresse d'une personne identifiable ?
  - `postal_address` — page(s) **1**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `f21c80ab3aaa…` — Manipulation de tables avec la bibliothèque Pandas PDF - 146.17 Ko

- **Contenu** : `f21c80ab3aaa9084fe631f7c38d6ca1451f77c529f8ab2d62296817741bf8963`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/manipulation-de-tables-avec-la-bibliotheque-pandas-pdf-146-17-ko--f21c80ab3a.pdf`
- **Type documentaire** : `diaporama` — 5 pages, 5 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 2

  - `postal_address` — page(s) **3**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `f636ef6038c2…` — Calculabilité et décidabilité PDF - 433.14 Ko

- **Contenu** : `f636ef6038c2379502bae01d5fdf06556aea70500a42b7adf9bd9f3996fe1d13`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/NSI/03_RESSOURCES_ACCOMPAGNEMENT/2020/calculabilite-et-decidabilite-pdf-433-14-ko--f636ef6038.pdf`
- **Type documentaire** : `ressource_officielle` — 7 pages, 7 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 2

  - `phone_french` — page(s) **7**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `04bf557a574c…` — La conservation des génomes - stabilité génétique et évolution clonale – remobiliser des prérequis et présentation orale PDF - 1.19 Mo

- **Contenu** : `04bf557a574c4d553fab35eb3175f6f638dd129ffa785ca640367ae5c109881c`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2021/la-conservation-des-genomes-stabilite-genetique-et-evolution-clonale-remobiliser-des-prerequis-et-presentation-orale-pdf-1-19-mo--04bf557a57.pdf`
- **Type documentaire** : `modalite_examen` — 9 pages, 9 scannées
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1

  - `postal_address` — page(s) **9**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `0dda163a7922…` — Former les élèves à des techniques de biologie moléculaire et de bioinformatique et appréhender le concept d'holobionte PDF - 5.31 Mo

- **Contenu** : `0dda163a792284e1e0df97c0ee72e8c04722bd145684db49a7095cb3b8e6ddc3`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/09_AUTRES/2020/former-les-eleves-a-des-techniques-de-biologie-moleculaire-et-de-bioinformatique-et-apprehender-le-concept-d-holobionte-pdf-5-31-m--0dda163a79.pdf`
- **Type documentaire** : `autre` — 43 pages, 43 scannées
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1

  - `phone_french` — page(s) **4**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `28f92cfe1c81…` — Écriture de tests PDF - 543.48 Ko

- **Contenu** : `28f92cfe1c81f2a4bab17aa2a9bff9a05f43a265ecad03214fe452a4ac53202d`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/NSI/03_RESSOURCES_ACCOMPAGNEMENT/2021/ecriture-de-tests-pdf-543-48-ko--28f92cfe1c.pdf`
- **Type documentaire** : `ressource_officielle` — 25 pages, 25 scannées
- **Collections** : `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 1

  - `postal_address` — page(s) **7**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `447bdee89af9…` — Types construits en Python PDF - 159.07 Ko

- **Contenu** : `447bdee89af9f0ab07460bd279f81647824c2d91ba7be1eff6daa133c5e8467d`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/NSI/07_DIAPORAMAS_SUPPORTS/2019/types-construits-en-python-pdf-159-07-ko--447bdee89a.pdf`
- **Type documentaire** : `diaporama` — 9 pages, 9 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 1

  - `phone_french` — page(s) **3**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

### `62d9ac283408…` — Qu'est-ce que la monnaie et comment est-elle créée ? PDF - 531.52 Ko

- **Contenu** : `62d9ac2834082bce93300fd19cc042595fcd506e94c9cabc80bb942c2d798380`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/SES/03_RESSOURCES_ACCOMPAGNEMENT/2019/qu-est-ce-que-la-monnaie-et-comment-est-elle-creee-pdf-531-52-ko--62d9ac2834.pdf`
- **Type documentaire** : `ressource_officielle` — 8 pages, 8 scannées
- **Collections** : `rag_nexus_ses_premiere_specialite`
- **Signaux** : 1

  - `postal_address` — page(s) **8**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `6a7942128b84…` — La question de grammaire de l’épreuve anticipée orale de français : précisions sur sa définition

- **Contenu** : `6a7942128b8404ac0b98e819c0f1482a6bac353bd2ea5a6269f7081676a65150`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/PREMIERE/FRANCAIS/01_PROGRAMMES_OFFICIELS/2022/la-question-de-grammaire-de-l-epreuve-anticipee-orale-de-francais-precisions-sur-sa-definition--6a7942128b.pdf`
- **Type documentaire** : `modalite_examen` — 4 pages, 4 scannées
- **Collections** : `rag_nexus_hlp_premiere_specialite`
- **Signaux** : 1

  - `postal_address` — page(s) **3**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `93b7e446273c…` — Diversité et unité des langages de programmation PDF - 161.08 Ko

- **Contenu** : `93b7e446273c0d36863ab8f86a39fb91dccb920ebd00e5be020f559253f9a17d`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/NSI/07_DIAPORAMAS_SUPPORTS/2019/diversite-et-unite-des-langages-de-programmation-pdf-161-08-ko--93b7e44627.pdf`
- **Type documentaire** : `diaporama` — 9 pages, 9 scannées
- **Collections** : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`
- **Signaux** : 1

  - `postal_address` — page(s) **5**
    - Hypothèse : `PUBLIC_INSTITUTIONAL_DATA`
    - À trancher : L'adresse est-elle celle d'une institution (ministère, académie, éditeur) figurant en couverture ou en pied de page, et non celle d'une personne ?

### `96e887c34c0d…` — Placer les élèves en démarche de projet pour comprendre et évaluer une action climatique PDF - 333.91 Ko

- **Contenu** : `96e887c34c0d7db5500632090ee0119d1366d2667217818b65d00a316d3ae329`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2020/placer-les-eleves-en-demarche-de-projet-pour-comprendre-et-evaluer-une-action-climatique-pdf-333-91-ko--96e887c34c.pdf`
- **Type documentaire** : `modalite_examen` — 13 pages, 13 scannées
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1

  - `student_name_pattern` — page(s) **10**
    - Hypothèse : `SYNTHETIC_EXAMPLE`
    - À trancher : Les noms sont-ils ceux d'élèves fictifs d'un scénario pédagogique, ou ceux d'élèves réels apparaissant dans une copie ou une liste ?

### `e1309f6255fb…` — Trajectoires et stratégies d’atténuation PDF - 1.43 Mo

- **Contenu** : `e1309f6255fbbc93d554c71b0ab2e98d176d27870edd15432d1b48a614d57294`
- **Chemin scellé** : `01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/SVT/04_EVALUATIONS_EXAMENS/2020/trajectoires-et-strategies-d-attenuation-pdf-1-43-mo--e1309f6255.pdf`
- **Type documentaire** : `modalite_examen` — 17 pages, 17 scannées
- **Collections** : `rag_nexus_svt_terminale_specialite`
- **Signaux** : 1

  - `phone_french` — page(s) **9**
    - Hypothèse : `FALSE_POSITIVE_TECHNICAL`
    - À trancher : La suite de chiffres est-elle un numéro de téléphone, ou une valeur technique du document (exemple binaire ou décimal, référence, numéro de version) que le motif capture par ressemblance ?

## Ce qu'il reste à faire, et par qui

1. **Ouvrir les pages nommées** sur le support contrôlé, contenu par
   contenu, et répondre à la question de chaque signal.
2. **Rendre les décisions** au format ADR-0047 : un jeu de décisions
   signé, son reçu, son ancre et son index. Chaque décision nomme sa
   disposition, ses pages, ses classes et une justification qui ne cite
   aucune donnée brute (`raw_pii_quoted: false`).
3. **Rattacher le jeu de décisions à la release candidate** : ses quatre
   empreintes entrent alors dans la chaîne de revue que le manifeste
   déclare, et le worker les confronte au démarrage.

Aucune de ces trois étapes n'est automatisable : la première est un acte
de lecture, la deuxième une décision humaine signée, la troisième en
dépend.
