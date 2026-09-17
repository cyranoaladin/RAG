# Lot CD — Proposition de décisions PII / actualité

- Lot : `LOT_GO_LIVE_FINAL_CD_PII_CURRENTNESS_DECISION_PROPOSAL`
- Branche : `go-live/pii-currentness-decision-proposal`
- Décision : `GO_LIVE_CD_PII_CURRENTNESS_DECISION_PROPOSAL_PR_OPEN`
- Proposition scellée : `docs/reports/evidence/pii_currentness_decision_proposal.json` (`785643053a75a9cdfd21a390d66f4950572fffc806d12c2e031bebf0a328d8fc`)
- Feuille proposée : `docs/reports/go_live/pii_currentness_decision_proposal.tsv` (631 lignes, 152 décisions)

**L'approbation de la PR de ce lot par abenrhouma vaut validation humaine explicite des décisions PII/currentness
proposées dans ce fichier.** Sans elle, aucune décision n'est effective : la proposition a le statut
`PROPOSED_NOT_EFFECTIVE`, rien n'est importé ni scellé, aucun compteur ne bouge, la matrice n'est pas touchée, aucune
release n'est produite.

## Ce qui est proposé

| Règle | Contenus | Décision proposée |
|---|---|---|
| Reconduction sur preuve identique | **23** (les 23 promus) | `PII_CLEARED`, avec **vos** dispositions, catégorie et motif de la revue V1 |
| Exclusion par précaution | **126** | `EXCLUDE_FROM_SERVABLE_SET` ; chaque finding `PERSONAL_DATA_PRESENT` |
| Actualité | **3** | `EXCLUDE_FROM_PROMOTED_RELEASE` |

### Reconduction — pourquoi elle est légitime, et où elle s'arrête

ADR-0047 interdit d'**étendre automatiquement** une décision V1 à la campagne V2, parce que le texte canonique a changé.
Ce lot n'étend rien : il **propose**, et c'est votre approbation qui décide. Mais il ne propose la reconduction que là où
la preuve est démontrée identique, mesure par mesure :

- mêmes instruments : `policy_sha256`, `scanner_sha256`, `page_policy_sha256` identiques entre le jeu V1 et l'index V2 ;
- pour chaque contenu, l'ensemble des findings V2 est **exactement** celui que vous aviez tranché : même motif, même page,
  même empreinte de la correspondance, même empreinte du contexte. 49 findings sur 49, 23 contenus sur 23.

Un seul finding différent, nouveau ou manquant, un instrument changé, ou une décision V1 `REJECTED` : la reconduction ne
s'applique pas (quatre épreuves). Dispositions reconduites : 30 `FALSE_POSITIVE_TECHNICAL`, 11 `SYNTHETIC_EXAMPLE`,
8 `PUBLIC_INSTITUTIONAL_DATA`.

Limite à connaître : l'empreinte de contexte couvre le voisinage de la correspondance, pas la page entière. Deux pages
différentes ailleurs mais identiques autour de chaque signalement donneraient la même preuve. Le scanner n'y ayant rien
relevé de plus (l'ensemble des findings est identique), le risque résiduel est faible, mais il existe.

### Exclusion par précaution — ce qu'elle dit vraiment

Le script ne lit **aucune** matière brute (épreuve : son source ne référence ni paquet de revue, ni page, ni PDF). Il ne
peut donc rien blanchir. Pour les 126 contenus jamais examinés, il propose la décision la plus protectrice, et le motif
l'écrit sans détour : « signalement(s) non examinés individuellement, présumés données personnelles ». La disposition
`PERSONAL_DATA_PRESENT` y est une **présomption**, pas un constat : le contrat n'a pas de valeur « non examiné ».

Coût : ces 126 contenus ne seront pas servis. Aucun n'est promu ni servable aujourd'hui (ils sont déjà bloqués) : le
corpus servable (2 264 contenus) et la release promue ne perdent rien de ce fait. Vous pouvez, avant d'approuver, changer
toute ligne que vous aurez examinée vous-même ; le validateur dira si la feuille reste recevable.

### Actualité

La source déclare les 3 documents archivés, ADR-0055 les refuse déjà ; aucune source en vigueur vérifiée n'est disponible,
donc `REPLACE_WITH_CURRENT_SOURCE` n'est pas proposable. Leur retrait change l'ensemble promu : nouvelle identité de
release (ADR-0050), outillage d'exclusion du constructeur (lot CF), rescellement (lot CG).

## Après approbation et merge — lot CE, puis CF et CG

1. `validate_pii_currentness_review_sheet.py` sur la feuille approuvée (déjà : 152 décidées, 0 invalide, scellable).
2. Index de revue complet compatible avec le scelleur gouverné (même dérivation que l'index restreint du lot CB).
3. `convert_review_sheet_to_sealer_draft.py` (hors dépôt) → `sceller_decisions_pii.py sceller` →
   `governance/pii-review-decisions/<id>.json`.
4. Câblage gouverné de la matrice de servabilité vers les décisions scellées.

Compteurs attendus **après** CE : `pii_undecided` 149 → 0 ; `release_promoted_refused_contents` 26 → 3 (les 23 promus
redeviennent admis ; les 3 d'actualité attendent le rescellement) ; puis 3 → 0 avec CF/CG. **Ce lot n'en change aucun.**

Conditions d'arrêt de CE : feuille modifiée non recevable, scellement refusé par le contrat, projection de release qui
refuse le jeu, compteur qui baisse plus que le nombre de décisions rendues (`READY_GATE_FALSE_POSITIVE`).

## Si la PR est refusée

Rien ne change : `pii_undecided=149`, 26 contenus promus refusés, C1 ouvert. Les feuilles de travail vierges restent
disponibles pour une revue manuelle.

## Garanties

9 épreuves sous `scripts/qualification/tests/` (exécutées en CI) : reconduction seulement sur preuve identique, aucune
reconduction si un instrument change, jamais de reconduction d'un rejet, rien d'admis hors reconduction, mots du reviewer
repris tels quels, couverture des 149 + 3 et passage du validateur, proposition sans effet et sans matière brute, feuilles
de travail vierges et aucun jeu de décisions apparu, artefacts à jour et scellés.

## Readiness

Inchangé : `GO_LIVE_READY=false`, `--assert-ready=1`, `go_live_qualification_blockers=4`, `pii_undecided=149`,
`release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
