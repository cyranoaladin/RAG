# Décisions PII — tableau de pilotage

Document dérivé. Ne pas éditer à la main :
`scripts/go_live/build_pii_decision_dashboard.py` le régénère.

**Aucune décision n'est prise ici. Aucune PII n'est écrite ici** :
le dépôt ne reçoit que des empreintes, des classes de signal et des comptes.

- paquets en attente : **149**
- dont **déjà dans la release promue** : **23**
- autres : 126

## Pourquoi l'ordre compte

Présentés en vrac, les paquets se valent tous. Ceux qui portent sur des
contenus déjà promus ne sont pas en attente de promotion : ils sont déjà
dans la release. Ils passent donc en premier.

Le niveau de risque **ordonne** la revue ; il ne la remplace pas. Un
contenu à faible risque reste indécis tant qu'un humain ne l'a pas tranché.

## Répartition

| risque | paquets |
| --- | ---: |
| A_QUALIFIER | 37 |
| ELEVE | 6 |
| MOYEN | 106 |

| catégorie relevée | contenus |
| --- | ---: |
| date_of_birth | 1 |
| email_address | 42 |
| french_ssn | 6 |
| phone_french | 46 |
| postal_address | 50 |
| student_name_pattern | 42 |

## Décisions recevables

- `PII_CLEARED`
- `PII_REDACTION_REQUIRED`
- `EXCLUDE_FROM_SERVABLE_SET`
- `HUMAN_REVIEW_REQUIRED`

## Effet de chaque décision

Pour un contenu **déjà promu** :

- `PII_CLEARED` — sort de `pii_undecided` et de l'incohérence de release ;
  la release garde le contenu ;
- `EXCLUDE_FROM_SERVABLE_SET` — sort aussi, mais **exige un reseal** sous
  une identité neuve, puisque le contenu quitte la release ;
- `PII_REDACTION_REQUIRED` — le contenu doit être repris avant toute
  décision de servabilité ;
- `HUMAN_REVIEW_REQUIRED` — reste indécis, et le reste tant que personne
  ne tranche.

## Ce que fermer la PII ne fait pas

trancher les 149 ferme pii_undecided et une partie de l incoherence de release ; la recherche, la qualification et les PR bloquantes restent ouvertes, et le corpus reste sans vecteurs.

## À revoir en premier

| ordre | contenu | risque | catégories | signalements |
| ---: | --- | --- | --- | ---: |
| 1 | `703cbd759841b016…` | ELEVE | french_ssn, phone_french | 6 |
| 2 | `04bf557a574c4d55…` | MOYEN | postal_address | 1 |
| 3 | `0dda163a792284e1…` | MOYEN | phone_french | 1 |
| 4 | `28c92cd742c6bc29…` | MOYEN | phone_french | 4 |
| 5 | `28f92cfe1c81f2a4…` | MOYEN | postal_address | 1 |
| 6 | `2d0745ca845f8e30…` | MOYEN | phone_french | 2 |
| 7 | `3f1ab328a0c11f40…` | MOYEN | postal_address | 2 |
| 8 | `447bdee89af9f0ab…` | MOYEN | phone_french | 1 |
| 9 | `461e89b1b1a24a83…` | MOYEN | postal_address | 3 |
| 10 | `5a8d69d488b341c6…` | MOYEN | email_address, phone_french | 3 |
| 11 | `62d9ac2834082bce…` | MOYEN | postal_address | 1 |
| 12 | `6a7942128b8404ac…` | MOYEN | postal_address | 1 |
| 13 | `936c1e54b1099bfb…` | MOYEN | postal_address, student_name_pattern | 2 |
| 14 | `93b7e446273c0d36…` | MOYEN | postal_address | 1 |
| 15 | `d05da0bb13bdad47…` | MOYEN | postal_address | 3 |
| 16 | `e1309f6255fbbc93…` | MOYEN | phone_french | 1 |
| 17 | `e20b73d10c46a2e6…` | MOYEN | phone_french, postal_address | 5 |
| 18 | `ebe2d96d24600df8…` | MOYEN | email_address, postal_address | 2 |
| 19 | `f21c80ab3aaa9084…` | MOYEN | postal_address | 2 |
| 20 | `f636ef6038c23795…` | MOYEN | phone_french | 2 |
| 21 | `157309db13b674ff…` | A_QUALIFIER | student_name_pattern | 1 |
| 22 | `39c50431bf6b80c4…` | A_QUALIFIER | student_name_pattern | 3 |
| 23 | `96e887c34c0d7db5…` | A_QUALIFIER | student_name_pattern | 1 |
