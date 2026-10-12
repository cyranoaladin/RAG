# Lot 2026-10-12 — assemblage du bundle C A2

Base : `origin/main=c046b65e43acea9b095078f1f2ea5e8543372231`, worktree isolé. Aucun transfert, job, déploiement ou écrit en base n'a été effectué par ce lot technique.

`scripts/go_live/assemble_public_successor_c_a2.py` accepte l'ancre A, la release immuable, une carte explicite de 26 fichiers d'autorité, quatre fichiers compagnons et les onze scopes V3 exacts de B. Il refuse une preuve absente, vide ou liée symboliquement, une release contenant un fichier étranger, un dossier de sortie existant ou situé dans la release, et les clés JSON dupliquées. Les onze chemins et SHA de scopes sont dérivés du registre B ; toute absence, substitution ou entrée supplémentaire est refusée avant création de la sortie. Il copie les octets dans un nouveau dossier privé, sous `authorities/<champ>.bin` et `scopes/<id>.json`, et produit `authority-envelope.json` canonique avec `activation_allowed=false` et `semantic_verification_complete=false`. Les trois preuves directement liées à A sont comparées à la release recopiée. La fonction historique d'enveloppe V1 conserve son format à 21 champs ; l'appel `authority_version="A2"` exige exactement les 26 champs définis par le contrat.

La carte JSON porte exactement trois objets : `authorities` contient les 26 noms de `_PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS` associés à des chemins absolus ; `companions` contient `observed-transfer-v1.json`, `target-pin.json`, `scope-policy.yml` et `scope-names.yml` ; `scopes` associe les onze chemins `scopes/<id>.json` du registre B à leurs chemins absolus. L'invocation est :

```text
python3 scripts/go_live/assemble_public_successor_c_a2.py \
  --anchor <ancre-A-approuvée> \
  --release-root <release-40b956c6f5ec0c60> \
  --evidence-map <carte-JSON-des-41-chemins-exacts> \
  --output-root <nouveau-dossier-privé-C>
```

Cette sortie est **seulement un transport de preuves**. Le signer `sign_staging_readiness_manifest_cli.py --public-successor-phase PUBLICATION` doit encore rejouer sémantiquement le bundle avec `replay_public_successor_publication`, la revue GitHub, les sources privées, le pin, la cible de transfert et les 377 attestations LOT42. Le reçu initial A2 `f19ea43406a6eb3994be1620f9c31200e5963c3b395a92ad6e3d5f50058c8e84` doit être fourni depuis ses octets privés exacts ; le constat C doit être nouvellement généré après l'émission A2. Ni l'un ni l'autre n'est inventé par l'assembleur.

TDD : le test A2 de l'enveloppe a échoué sur le paramètre absent, puis réussi ; l'assemblage a échoué sur l'implémentation absente, et le sabotage d'une sortie dans la release a reproduit une copie récursive avant correction. Le test de clé JSON dupliquée a échoué puis réussi après refus explicite. La lacune des scopes B a été couverte par un test rouge (argument manquant), puis par les sabotages d'un scope absent et d'octets remplacés. Vérification : 209 tests ciblés initiaux verts, puis sept tests de l'assembleur verts après correction ; Ruff et mypy ciblés verts ; `git diff --check` vert. Aucun succès C live ni readiness signée n'est revendiqué.
