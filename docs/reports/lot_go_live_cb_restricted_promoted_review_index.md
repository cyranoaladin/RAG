# Lot CB — Index de revue restreint aux contenus promus bloquants

- Lot : `LOT_GO_LIVE_FINAL_CB_RESTRICTED_PROMOTED_PII_REVIEW_INDEX`
- Branche : `go-live/restricted-promoted-pii-review-index` — base `960a6b86cbbfcca9f8b9262bdb50b23e53ea2e53`
- **Décision : `GO_LIVE_CB_RESTRICTED_REVIEW_INDEX_PR_OPEN`**
- Index scellé : `docs/reports/evidence/promoted_pii_currentness_restricted_review_index.json` (`447545a33999a94087c04f2bbbc1c413bd20d8bac97912f197c795867ef4bf60`)
- Aucune décision PII, aucune décision préremplie, aucun compteur modifié, aucune release, C1 non fermé, matrice non touchée.

## Pourquoi ce lot était nécessaire — deux défauts, dont un que personne n'avait vu

1. **Portée.** `sceller_decisions_pii.py` (ADR-0047) exige une décision pour chaque contenu de l'index qu'on lui donne.
   Contre l'index V2 (149 contenus), décider les 23 promus seuls n'est pas scellable.
2. **Le scelleur gouverné ne s'exécutait pas du tout sur l'index V2.** Il lit `finding["page"]` ; l'index V2 nomme cette
   clé `page_number`. Résultat : `KeyError: 'page'` dès la génération du brouillon. Même en tranchant les 149 contenus,
   aucune décision de la campagne V2 n'aurait pu être scellée. Une épreuve le fige (`pytest.raises(KeyError)` sur l'index V2).

## Ce que fait l'index restreint

Une **dérivation**, sans nouveau scan ni nouvelle mesure :

| Élément | Origine |
|---|---|
| périmètre | `release_promoted_refused_content_ids` du readiness, recoupé avec `currentness_release_impact.json` (tous `promoted: true`) |
| 23 paquets PII | ceux de l'index V2, **repris à l'identique** (même `bundle_sha256`, mêmes 49 findings, mêmes empreintes) |
| clé `page` | ajoutée à chaque finding, égale à `page_number` : celle que lisent le scelleur, le contrat de décisions et la projection de release |
| instruments | politique, scanner, foyer de pages, run, OCR : repris de l'index V2, jamais réécrits |
| 3 contenus d'actualité | lignes de l'impact de release, **hors** `bundles` (sinon le scelleur PII exigerait une décision PII sur des contenus sans PII) |
| protocole | `NEXUS-PII-REVIEW-INDEX-V1` : **le scelleur gouverné n'est pas modifié** |

Il est **stable** : ni date, ni empreinte du readiness (régénéré à chaque lot). Le jeu de décisions épinglera l'empreinte
de ce fichier (`review_index_sha256`) ; elle ne doit pas bouger d'un lot à l'autre. Le lien au readiness est tenu par
l'empreinte de l'**ensemble** des 26 identifiants, revérifiée à chaque validation. Il ne lit pas la matrice de servabilité.

Vérifié aussi avec l'outil gouverné existant : les 23 paquets présents sur disque correspondent à l'index restreint
(`preparer_paquets_revue_pii.py --verifier` → `intact: true`).

## Validateur fail-closed — `build_promoted_restricted_review_index.py --verify-only`

Refuse : index absent ; index altéré (empreinte) ; contenu non promu ; contenu promu manquant ; finding PII manquant, en
trop ou modifié ; paquet différent de celui de l'index V2 ; contenu d'actualité manquant ; instrument réécrit ; décision
préremplie (toute clé de décision, à toute profondeur) ; matière PII brute (`match_text`, `context`, …) ; secret apparent ;
chemin absolu personnel ; index qui n'est plus celui que les autorités donnent aujourd'hui.

## Passage suivant, préparé et éprouvé — mais non exécuté

```
feuille remplie ──validate_pii_currentness_review_sheet──▶ convert_review_sheet_to_sealer_draft (hors dépôt)
   ──▶ sceller_decisions_pii.py sceller --index <index restreint> ──▶ governance/pii-review-decisions/<id>.json (PR, revue épinglée)
   ──▶ lot BW : projection de release, réduction ciblée des 26, rescellement, C1
```

- Le convertisseur **transcrit**, il ne décide pas : `PII_CLEARED → APPROVED`, les deux rejets → `REJECTED` (leur nuance est
  conservée à part pour BW, le contrat ne la porte pas) ; `COMMENT` devient `justification.statement`. Il refuse une
  feuille invalide, incomplète ou vierge, une date sans fuseau, et toute sortie **dans** le dépôt.
- Épreuve de bout en bout : feuille de décisions **fictives** (toutes `REJECTED`, le sens qui n'admet aucun contenu) →
  brouillon → scelleur gouverné → jeu de 23 décisions lié à l'empreinte de l'index restreint. Le tout dans un répertoire
  temporaire ; une assertion vérifie que rien n'est apparu sous `governance/`.
- Validateur de feuille aligné sur le contrat : motif obligatoire (20 à 1000 caractères), reviewer unique, et
  `sealable` ne porte plus que sur les lignes PII (l'actualité n'entre pas dans le jeu PII).
- Restent à BW, sous votre revue : le câblage des décisions scellées vers la matrice (elle n'en lit aucune), la forme
  scellée des décisions d'actualité (aucun protocole n'existe → ADR), et la capacité d'exclusion du constructeur de release.

## Écart de CI constaté (non corrigé ici, à arbitrer)

La CI GitHub ne lance pas `pytest scripts/tests/` : elle nomme ses épreuves une à une. Les épreuves de
`test_qualification_blockers_producer.py` — donc tous les tests de refus des vérificateurs de blockers — **ne tournent
qu'en local**. Les épreuves de ce lot sont placées sous `scripts/qualification/tests/`, que la CI exécute. Étendre la CI aux
épreuves des vérificateurs renforcerait un garde-fou ; je ne touche pas à `ci.yml` sans votre accord.

## Tests

`scripts/qualification/tests/test_promoted_restricted_review_index.py` : 20 épreuves (dérivation, identité des paquets,
instruments, stabilité, artefact versionné à jour, scelleur gouverné compatible, 9 refus du validateur, cohérence avec la
feuille minimale, conversion + scellement de bout en bout, refus de conversion). Validateur de feuille : 10 épreuves.

## Readiness

Inchangé : `GO_LIVE_READY=false`, `--assert-ready=1`, `go_live_qualification_blockers=4`, `pii_undecided=149`,
`release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
