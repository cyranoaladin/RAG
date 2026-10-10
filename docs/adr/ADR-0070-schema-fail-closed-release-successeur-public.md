# ADR-0070 — Schéma fail-closed de la release successeur publique

- **Statut** : proposé, sans autorisation de promotion.
- **Date** : 2026-10-10.
- **Portée** : `packages/release-chain` ; complète ADR-0064, ADR-0068 et ADR-0069.

## Décision

`release_mode=public_successor` désigne une nouvelle identité de release, distincte du candidat #312, et seulement des artefacts textuels avec placements `public`. Le schéma fermé exige simultanément les digests du candidat source, de l'inventaire, de la sélection des dérivés, des preuves PII et d'actualité sur leurs nouvelles identités, des profils complets, des droits, des scopes et reviews exact-HEAD, des autorisations, de la revue batch, du transfert observé et des révocations. Les mêmes autorités doivent figurer dans chaque subject. Le profil de chaque subject doit nommer le digest du manifeste des profils publics complets. Aucun champ de l'ancienne autorité de candidat ne remplace ces nouvelles preuves.

La déclaration n'est acceptée qu'avec `PROMOTABLE`, `REVIEWED` et `PRODUCTION_ACTIVATION_ALLOWED`, mais **le lecteur la refuse toujours**, après contrôle de forme et de cardinalité, avec `public successor external evidence verification unavailable`. Un digest syntaxiquement correct, même lié à un fichier local, ne démontre ni une revue GitHub au HEAD exact, ni une autorisation LOT41A, ni une revue batch LOT42, ni la copie effective des 253 ou moins d'octets textuels, ni l'actualité des dérivés. Il est interdit de transformer ces déclarations en statut promotable par la seule présence de SHA.

La transition vers une release réellement promotable requerra un validateur indépendant qui ouvre les pièces scellées, vérifie leurs types, leur population exacte et leurs signatures/reviews, confronte chaque identité de contenu et de scope, et prouve les octets transférés. Worker A et le runtime devront consommer ce verdict lié au digest exact de la release. L'ADR de cette transition précisera les formats des reçus et les vérificateurs réels ; la présente ADR n'invente aucun reçu.

Le rapport `student_derivative_pii_pattern_screen_20261010.json` est seulement un dépistage de motifs (`PATTERN_SCREEN_ONLY_NOT_FULL_PII_ADJUDICATION`). Son SHA ne peut satisfaire une preuve PII d'inclusion ou la promotion. Les cas suspects demandent une adjudication complète liée aux octets exacts.

L'inventaire textuel du successeur porte l'empreinte du manifeste **préparatoire**,
pas celle du manifeste final : le manifeste final nomme le SHA de l'inventaire,
si bien qu'un pointeur inverse vers son SHA créerait un cycle. Deux autorités
supplémentaires et indivisibles scellent donc le manifeste préparatoire et son
`preparation-index.json`. Le paquet final doit embarquer sous
`source_preparation/` les octets exacts de ces deux fichiers et du
`candidate_inventory.json` préparatoire. Le lecteur vérifie les deux SHA
d'autorité, les liens index → manifeste/inventaire/registre, la référence au
candidat #312, puis les identités de release, d'artefact et les placements du
nouvel inventaire. Chaque placement final doit provenir du même dérivé, de la
même source et de la même collection préparatoires. Les SHA V4/V5 et le SHA du
manifeste des dérivés sont confrontés aux octets de cet inventaire source.
L'autorité `source_candidate_release_manifest_sha256` garde son sens distinct :
elle nomme #312 et ne peut servir de raccourci vers le préparatoire. En
l'absence des trois fichiers déréférençables ou d'un des deux nouveaux ancrages,
Worker A refuse avant le transfert et avant toute écriture.

## Compatibilité et garde

Le mode `candidate` conserve son ensemble fermé de huit autorités et ses statuts `NOT_PROMOTABLE/PRE_REVIEW/NO_PRODUCTION_ACTIVATION`. Les releases V4/V5 ne sont pas promues. Le changement de `release_mode` ou de statuts du candidat #312 ne suffit pas ; l'identité `student-public-successor-*`, la chaîne de 21 autorités, le type texte, les placements publics et la vérification indépendante sont nécessaires. Aucune migration, activation ou publication n'est effectuée ici.
