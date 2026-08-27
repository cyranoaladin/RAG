# ADR-0049 — Activation de sept collections lycée général après revue humaine dédiée

- **Statut** : **Acceptée** — décision opérateur du 2026-08-27
- **Date** : 2026-08-27
- **Décideur** : Nexus Réussite (opérateur humain)
- **S'appuie sur** : ADR-0013, ADR-0036, ADR-0038, ADR-0039, ADR-0041, ADR-0044, ADR-0048

## Contexte

La construction de la première release servable (`FIRST_SERVABLE_RELEASE`) a gelé un ensemble éligible de 18 collections, 26 artefacts, 26 placements et 730 chunks portant le sceau de contenu :

```text
FINAL_SET_SHA256 = fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
```

Dans cet ensemble, sept collections de la voie générale disposaient de l'ensemble complet des preuves techniques (autorisations LOT41A-V2, profils de production, allowlists scellées, droits, PII, currentness primaire, programmes officiels) mais étaient jusqu'ici restées dormantes (`instanciee: false`) au catalogue, en attente d'une revue humaine dédiée à leur activation.

Conformément au cadre de gouvernance Nexus, `instanciee: true` ne découle jamais automatiquement de l'extension de périmètre produit fixée par l'ADR-0048, ni d'un calcul d'artefacts. L'activation exige une revue technique préalable fail-closed et une décision humaine formelle.

## Dossier technique de revue d'activation

Le dossier technique a établi pour chacune des sept collections la satisfaisabilité exhaustive des critères de certification :

```text
TECHNICAL_ACTIVATION_REVIEW = PASS (7/7 collections)
```

| Collection | Autorisation LOT41A-V2 | Profil production & Fingerprint | Artefacts / Placements / Chunks | Allowed Content SHA256 | Droits / PII / Currentness | Programme officiel |
|---|---|---|:---:|---|---|---|
| `rag_nexus_dgemc_terminale_option` | `prerentree-2026-2027-rag_nexus_dgemc_terminale_option-v1` | `dgemc_terminale_option_profile_gate_v1` (`685dac09...4f00`) | 1 / 1 / 44 | `e591a87aee...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A` |
| `rag_nexus_hlp_premiere_specialite` | `prerentree-2026-2027-rag_nexus_hlp_premiere_specialite-v1` | `hlp_premiere_specialite_profile_gate_v1` (`48d961d2...bc35`) | 4 / 4 / 56 | `4433fee9...`, `60eeb7dd...`, `64f5b342...`, `9357dfde...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_1_2019-01-22` |
| `rag_nexus_pc_premiere_specialite` | `prerentree-2026-2027-rag_nexus_pc_premiere_specialite-v1` | `pc_premiere_specialite_profile_gate_v1` (`ca2fb2d2...22c5`) | 1 / 1 / 39 | `db43d342ed...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_1_2019-01-22` |
| `rag_nexus_ses_premiere_specialite` | `prerentree-2026-2027-rag_nexus_ses_premiere_specialite-v1` | `ses_premiere_specialite_profile_gate_v1` (`b9aa5b13...8eaa`) | 1 / 1 / 16 | `06e491d369...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_1_2019-01-22` |
| `rag_nexus_ses_terminale_specialite` | `prerentree-2026-2027-rag_nexus_ses_terminale_specialite-v1` | `ses_terminale_specialite_profile_gate_v1` (`41ab4497...3256`) | 1 / 1 / 18 | `2f1035c74d...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_8_2019-07-25` |
| `rag_nexus_svt_premiere_specialite` | `prerentree-2026-2027-rag_nexus_svt_premiere_specialite-v1` | `svt_premiere_specialite_profile_gate_v1` (`de3a4b05...409d`) | 1 / 1 / 57 | `8eb0e41f95...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_1_2019-01-22` |
| `rag_nexus_svt_terminale_specialite` | `prerentree-2026-2027-rag_nexus_svt_terminale_specialite-v1` | `svt_terminale_specialite_profile_gate_v1` (`223c6a49...1f58`) | 1 / 1 / 72 | `d2cbd06f2e...` | `officiel_public` / Attested / `EXACT_SCOPE_GROUNDED` (`PRIMARY_SCOPE_PROVEN`) | `BOEN_special_8_2019-07-25` |

Totaux exacts vérifiés : **10 artefacts**, **10 placements**, **302 chunks attendus**.

## Décision Opérateur

Sur la base du dossier technique ci-dessus, l'opérateur humain prononce explicitement :

```text
HUMAN_ACTIVATION_DECISION = APPROVED
```

pour les sept collections nommées :
1. `rag_nexus_dgemc_terminale_option` ;
2. `rag_nexus_hlp_premiere_specialite` ;
3. `rag_nexus_pc_premiere_specialite` ;
4. `rag_nexus_ses_premiere_specialite` ;
5. `rag_nexus_ses_terminale_specialite` ;
6. `rag_nexus_svt_premiere_specialite` ;
7. `rag_nexus_svt_terminale_specialite`.

Ces sept collections passent de :
`declared + authorized + profiled + release_member + instanciee: false`
à :
`declared + authorized + profiled + reviewed + release_member + instanciee: true`.

Leur autorité d'activation normative est désormais consignée sous la référence `ADR-0049` dans `activation_authorities.yml`.

## Invariant de Jalon

Cette activation consolide la première release servable :

```text
FIRST_SERVABLE_RELEASE = 18 collections, 26 artefacts, 26 placements, 730 chunks
```

**Rappel impératif : `FIRST_SERVABLE_RELEASE != GO_LIVE_READY`**.

Conformément à l'ADR-0048, le jalon `GO_LIVE_READY` exige la couverture structurelle complète et l'ingestion gouvernée de l'ensemble du périmètre cible :
- Collège (6e, 5e, 4e, 3e) ;
- Lycée général (2de, 1re, Tle) ;
- STMG (1re, Tle) ;
- Comptabilisation et ingestion exhaustive des 2 584 ressources du Drive officiel.

L'activation des sept collections ne dispense en rien de l'exécution intégrale de la roadmap GO-LIVE.
