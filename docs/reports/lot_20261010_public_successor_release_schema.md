# Lot — schéma de release `public_successor`

Base de travail : `eb8fb79c`, worktree et venv isolés. Aucun manifeste final, aucune preuve externe, aucun staging ni production modifiés.

Le parseur de `nexus-release-chain` reconnaît désormais une déclaration `public_successor` séparée du candidat #312. Il exige une nouvelle identité, 19 digests d'autorité obligatoires, un manifeste de profils publics complets, des artefacts dérivés textuels et des placements `public`. Les subjects doivent porter la même chaîne que l'agrégat ; les cardinalités restent recomptées par les validateurs existants. La garde du candidat historique reste intacte.

**Verdict de promotion : refus.** Les mécanismes existants ne savent pas vérifier depuis ce contrat les preuves exact-HEAD de revue et d'autorisation, le reçu de transfert observé, les décisions PII/actualité des dérivés et la portée réelle des droits. Le parseur refuse donc `public_successor` même si tous les noms de digests sont présents et que ses statuts déclarent `PROMOTABLE`. Cela évite qu'un simple renommage du candidat atteigne Worker A ou un runtime. Les formats et validateurs de ces pièces, puis leur intégration au Worker, constituent la dépendance bloquante avant toute promotion.

Le rapport PII reçu `student_derivative_pii_pattern_screen_20261010.json` annonce `PATTERN_SCREEN_ONLY_NOT_FULL_PII_ADJUDICATION` ; il ne peut pas devenir la preuve PII de ce schéma par simple référencement de son SHA.

Tests TDD : l'import du nouveau schéma était rouge ; huit tests dédiés sont verts, dont les sabotages d'autorité manquante, SHA invalide, identité candidate, PDF, placement `internal` et statuts de candidat. Le package complet passe : 71 tests. Ruff passe sur les fichiers touchés avec les trois règles déjà en échec avant ce lot (`RUF007`, deux `BLE001`) ignorées explicitement ; ces lignes préexistantes ne sont pas modifiées. L'ADR-0070 décrit la frontière de sécurité et ne prétend pas approuver une release.
