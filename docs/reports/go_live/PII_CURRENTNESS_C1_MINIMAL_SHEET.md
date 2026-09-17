# Chemin minimal pour débloquer C1 — vue de lecture

Document dérivé (`scripts/go_live/build_pii_currentness_decision_packet.py`). Ne pas éditer à la main.
Les décisions se saisissent dans `docs/reports/go_live/pii_currentness_c1_minimal_sheet.tsv`, jamais ici. **Aucune décision n'est pré-remplie.**

- contenus d'actualité : **3**
- contenus PII promus : **23**, findings : **49**

## 1. Actualité — la source déclare ces documents archivés

| # | Document | Déclaré | Empreinte |
|---|---|---|---|
| A1 | `glossaire--174f273ff2.pdf` | ARCHIVE_DECLARED | `174f273ff258…` |
| A2 | `pour-la-voie-technologique--ccffe628bb.pdf` | ARCHIVE_DECLARED | `ccffe628bbd6…` |
| A3 | `pour-la-voie-generale--dc58fcc42e.pdf` | ARCHIVE_DECLARED | `dc58fcc42ef9…` |

## 2. PII — contenus promus, dans l'ordre de revue du tableau de pilotage

| # | Risque | Document | Classes | Findings | Pages | Décision V1 (non étendue) | Paquet hors dépôt |
|---|---|---|---|---|---|---|---|
| P1 | ELEVE | `le-paradigme-fonctionnel-pdf-404-66-ko--703cbd7598` | french_ssn, phone_french | 6 | 4 | APPROVED / TECHNICAL_FALSE_POSITIVE | `703cbd759841…` |
| P2 | MOYEN | `la-conservation-des-genomes-stabilite-genetique-et-evolution-clonale-remobiliser-des-prerequis-et-presentation-orale-pdf-1-19-mo--04bf557a57` | postal_address | 1 | 9 | APPROVED / TECHNICAL_FALSE_POSITIVE | `04bf557a574c…` |
| P3 | MOYEN | `former-les-eleves-a-des-techniques-de-biologie-moleculaire-et-de-bioinformatique-et-apprehender-le-concept-d-holobionte-pdf-5-31-m--0dda163a79` | phone_french | 1 | 4 | APPROVED / TECHNICAL_FALSE_POSITIVE | `0dda163a7922…` |
| P4 | MOYEN | `modele-d-architecture-de-von-neumann-pdf-243-56-ko--28c92cd742` | phone_french | 4 | 5 | APPROVED / TECHNICAL_FALSE_POSITIVE | `28c92cd742c6…` |
| P5 | MOYEN | `ecriture-de-tests-pdf-543-48-ko--28f92cfe1c` | postal_address | 1 | 7 | APPROVED / TECHNICAL_FALSE_POSITIVE | `28f92cfe1c81…` |
| P6 | MOYEN | `des-ressources-numeriques-pour-accompagner-l-etude-des-uvres-au-programme-le-roman-et-le-recit-du-moyen-age-au-xxie-siecle-pdf-177--2d0745ca84` | phone_french | 2 | 5 | APPROVED / TECHNICAL_FALSE_POSITIVE | `2d0745ca845f…` |
| P7 | MOYEN | `variation-genetique-et-sante-risque-de-transmission-de-la-mucoviscidose-chez-un-couple-dont-l-homme-est-heterozygote-composite-pdf--3f1ab328a0` | postal_address | 2 | 8, 9 | APPROVED / PUBLIC_OFFICIAL_PUBLICATION | `3f1ab328a0c1…` |
| P8 | MOYEN | `types-construits-en-python-pdf-159-07-ko--447bdee89a` | phone_french | 1 | 3 | APPROVED / TECHNICAL_FALSE_POSITIVE | `447bdee89af9…` |
| P9 | MOYEN | `manipulation-de-tables-pdf-144-44-ko--461e89b1b1` | postal_address | 3 | 1 | APPROVED / PEDAGOGICAL_EXAMPLE | `461e89b1b1a2…` |
| P10 | MOYEN | `dossier-de-presse-eutrophisation-pdf-1-54-mo--5a8d69d488` | email_address, phone_french | 3 | 17 | APPROVED / INSTITUTIONAL_CONTACT | `5a8d69d488b3…` |
| P11 | MOYEN | `qu-est-ce-que-la-monnaie-et-comment-est-elle-creee-pdf-531-52-ko--62d9ac2834` | postal_address | 1 | 8 | APPROVED / INSTITUTIONAL_CONTACT | `62d9ac283408…` |
| P12 | MOYEN | `la-question-de-grammaire-de-l-epreuve-anticipee-orale-de-francais-precisions-sur-sa-definition--6a7942128b` | postal_address | 1 | 3 | APPROVED / TECHNICAL_FALSE_POSITIVE | `6a7942128b84…` |
| P13 | MOYEN | `les-circuits-pdf-4-51-mo--936c1e54b1` | postal_address, student_name_pattern | 2 | 12, 14 | APPROVED / TECHNICAL_FALSE_POSITIVE | `936c1e54b109…` |
| P14 | MOYEN | `diversite-et-unite-des-langages-de-programmation-pdf-161-08-ko--93b7e44627` | postal_address | 1 | 5 | APPROVED / TECHNICAL_FALSE_POSITIVE | `93b7e446273c…` |
| P15 | MOYEN | `securisation-des-communications-pdf-874-59-ko--d05da0bb13` | postal_address | 3 | 7 | APPROVED / TECHNICAL_FALSE_POSITIVE | `d05da0bb13bd…` |
| P16 | MOYEN | `trajectoires-et-strategies-d-attenuation-pdf-1-43-mo--e1309f6255` | phone_french | 1 | 9 | APPROVED / INSTITUTIONAL_CONTACT | `e1309f6255fb…` |
| P17 | MOYEN | `representation-des-entiers-naturels-pdf-167-2-ko--e20b73d10c` | phone_french, postal_address | 5 | 2, 4, 5, 6 | APPROVED / TECHNICAL_FALSE_POSITIVE | `e20b73d10c46…` |
| P18 | MOYEN | `reglement-2026-2027-pdf-202-78-ko--ebe2d96d24` | email_address, postal_address | 2 | 1, 3 | APPROVED / INSTITUTIONAL_CONTACT | `ebe2d96d2460…` |
| P19 | MOYEN | `manipulation-de-tables-avec-la-bibliotheque-pandas-pdf-146-17-ko--f21c80ab3a` | postal_address | 2 | 3 | APPROVED / PEDAGOGICAL_EXAMPLE | `f21c80ab3aaa…` |
| P20 | MOYEN | `calculabilite-et-decidabilite-pdf-433-14-ko--f636ef6038` | phone_french | 2 | 7 | APPROVED / TECHNICAL_FALSE_POSITIVE | `f636ef6038c2…` |
| P21 | A_QUALIFIER | `la-definition-des-epreuves-anticipees-de-francais-du-baccalaureat-general-et-technologique--157309db13` | student_name_pattern | 1 | 8 | APPROVED / PEDAGOGICAL_EXAMPLE | `157309db13b6…` |
| P22 | A_QUALIFIER | `mutations-de-l-adn-et-variabilite-genetique-alterations-du-genome-et-cancerisation-presentation-orale-d-une-strategie-de-resolutio--39c50431bf` | student_name_pattern | 3 | 7, 8, 9 | APPROVED / PEDAGOGICAL_EXAMPLE | `39c50431bf6b…` |
| P23 | A_QUALIFIER | `placer-les-eleves-en-demarche-de-projet-pour-comprendre-et-evaluer-une-action-climatique-pdf-333-91-ko--96e887c34c` | student_name_pattern | 1 | 10 | APPROVED / PEDAGOGICAL_EXAMPLE | `96e887c34c0d…` |
