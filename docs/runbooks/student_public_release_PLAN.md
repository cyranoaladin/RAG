# Plan gouverné — releases publiques pour la recherche étudiante

**Statut : proposition non activée.** La décision ADR-0064 et une review humaine au HEAD exact sont nécessaires avant toute émission d'autorité publique. Ce plan n'est pas une autorisation de staging ou de production.

## Entrées immuables et prévol

Partir du `main` courant dans un worktree propre et d'un environnement Python non partagé avec un autre worktree. Vérifier les manifests V4 (`bab9c398…`), HGGSP V5 (`82863880…`) et le registre mixte (`59db12e8…`) par les chargeurs canoniques et par SHA-256. Avant de construire les releases publiques, qualifier la **source interne existante** : les 74 publications V5 réussies, l'union 11/315/479/8268 et le retrieval des onze collections sur son API réelle. Cette qualification source est distincte de celle de la nouvelle cible publique, créée à l'étape 5 puis contrôlée à l'étape 6 ; aucune mesure de fixture ou d'un ancien checkout n'y supplée.

Établir la liste exacte des 315 `content_sha256` et des 479 placements autorisés, les 11 collections, les références BOEN, l'état des droits et de PII de chacun des 315 contenus, l'actualité et les révocations. Refuser tout écart entre le set réel, le registre mixte et la future entrée de release. Les droits `officiel_public` observés en staging sont une condition nécessaire, pas une revue humaine d'ouverture du service.

## Construction et contrôles, sans activation

1. **Décision de visibilité** : faire approuver ADR-0064 par `abenrhouma` au HEAD exact ; aucune politique active n'est changée par cette seule décision.
2. **Releases successeurs** : produire deux nouvelles identités immuables, neuf collections non-HGGSP et deux HGGSP, depuis les contenus vérifiés. Utiliser les producteurs existants, une sortie neuve, le miroir PDF vérifié et le diff machine contre les deux sources. Les nouveaux manifests portent des placements `public`, des profils `public`, de nouveaux digests et la chaîne de droits/PII/actualité contemporaine. Un mode `rehearsal` ou `NOT_PROMOTABLE` ne peut pas être présenté comme production.
3. **Scopes et autorisations** : émettre onze nouveaux scopes par l'émetteur canonique après cross-check `evidence_visibility=public` et `policy_visibility=public`, onze autorisations LOT41A-V2 liées aux contenus et un nouveau registre mixte. Les anciennes autorités restent inchangées. Vérifier unicité `(collection, subject_sha256)` et refus d'un scope V4/V5 utilisé pour un nouveau subject.
4. **Revues** : soumettre les octets produits à des PR gouvernées, faire approuver chaque HEAD exact et enregistrer autorisations puis revues batch pendant que leurs PR restent ouvertes. Toute révocation ou expiration annule le passage. Aucune écriture pgvector ne précède `quality → gate → review`.
5. **Qualification isolée** : créer une cible staging propre par l'autorisation d'exécution dédiée, puis publier via l'orchestrateur et Worker B bornés aux deux releases. Exiger exactement 11/315/479/8268 sur le produit, 74 placements HGGSP et 405 non-HGGSP, tous `public`, sans doublon et sans ligne historique recopiée arbitrairement.
6. **Parcours de refus et preuve** : pour chaque collection, interroger par le vrai BFF et une identité `student` signée, puis vérifier citations, identité source, niveau/matière, droit, visibilité, actualité et review ; tester les refus hors collection, tenant, rôle et audience. Exiger `STUDENT_SERVABLE=11/11`, `OUT_OF_SCOPE_RESULTS=0`, `MISSING_CITATIONS=0`. Rejouer ensuite la qualité et la charge sur cette **même** cible finale.
7. **Promotion** : figer les SHA et digests après qualification, préparer images par digest, backup/restore/rollback et readiness signée. Aucune mutation production avant le final cutover human gate.

## Arrêts obligatoires

Arrêter à tout mismatch de contenu, politique, review, droit, PII, actualité, révocation, cardinalité ou provenance ; ne jamais forcer les comptes. La base `ragdb_profile_gate_v4`, ses 479 placements `internal` attendus après V5, ses anciens jobs HGGSP V4 et ses colonnes historiques de `rag_chunks` ne sont pas modifiés par ce plan. La cible propre est une nouvelle matérialisation gouvernée, non un remplacement SQL de l'historique.
