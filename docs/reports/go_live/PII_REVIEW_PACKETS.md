# Paquets de revue PII

Document dérivé. Ne pas éditer à la main :
`scripts/go_live/export_pii_review_packets.py` le régénère.

Aucune décision n'est prise ici. Aucune PII n'est écrite ici :
le dépôt ne reçoit que des empreintes, des classes de signal et des comptes.

- paquets exportés : **149**
- dont déjà promus : **23**
- textes de revue divergents (refusés) : **0**
- absents de la base (refusés) : **0**
- décisions prises par ce script : **0**

## Catégories relevées

| catégorie | contenus |
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

## Ce que ce document ne change pas

- la matrice de servabilité
- le compteur pii_undecided
- l'ensemble promu

## À revoir en premier — contenus déjà dans la release

| contenu | catégories | signalements |
| --- | --- | ---: |
| `6a7942128b8404ac…` | postal_address | 1 |
| `f21c80ab3aaa9084…` | postal_address | 2 |
| `461e89b1b1a24a83…` | postal_address | 3 |
| `e20b73d10c46a2e6…` | phone_french, postal_address | 5 |
| `447bdee89af9f0ab…` | phone_french | 1 |
| `96e887c34c0d7db5…` | student_name_pattern | 1 |
| `e1309f6255fbbc93…` | phone_french | 1 |
| `04bf557a574c4d55…` | postal_address | 1 |
| `39c50431bf6b80c4…` | student_name_pattern | 3 |
| `5a8d69d488b341c6…` | email_address, phone_french | 3 |
| `0dda163a792284e1…` | phone_french | 1 |
| `3f1ab328a0c11f40…` | postal_address | 2 |
| `f636ef6038c23795…` | phone_french | 2 |
| `28f92cfe1c81f2a4…` | postal_address | 1 |
| `703cbd759841b016…` | french_ssn, phone_french | 6 |
| `ebe2d96d24600df8…` | email_address, postal_address | 2 |
| `d05da0bb13bdad47…` | postal_address | 3 |
| `93b7e446273c0d36…` | postal_address | 1 |
| `28c92cd742c6bc29…` | phone_french | 4 |
| `936c1e54b1099bfb…` | postal_address, student_name_pattern | 2 |
| `62d9ac2834082bce…` | postal_address | 1 |
| `2d0745ca845f8e30…` | phone_french | 2 |
| `157309db13b674ff…` | student_name_pattern | 1 |
