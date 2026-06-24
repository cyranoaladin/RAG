# Rapport — Lot 1.0 : Contrat nexus-contracts 0.2.0

## Nouveaux types

### `Audience` (enum)
Valeurs : `libre`, `aefe`, `tous`.

### `ChunkMetadata` (modèle Pydantic strict)
Champs obligatoires : `tenant`, `niveau`, `voie`, `matiere`, `audience` (list, min 1, sans doublons), `type_doc`, `notions` (validés non vides), `source_label`, `source_uri`, `rights`, `official`, `doc_id`.
Champs optionnels : `difficulte` (1-5), `page` (≥1), `chapitre`.

### TypeDoc étendu
Ajout de `referentiel` et `modalite_examen` (rétro-compatible).

## Dérivation `audience`

Propriété `StudentProfile.audience` → `str` :
- `"libre"` si `status_detail == candidat_libre` OU `candidat ∈ {individuel, libre, cned_libre}`
- `"aefe"` si `status_detail == aefe`
- `"aefe"` par défaut (scolarisé réseau français = audience AEFE)

**Ambiguïté tranchée** : un élève scolarisé non-AEFE (ex. système tunisien, double cursus) reçoit `"aefe"` par défaut. Cela garantit qu'il accède au contenu commun (`audience ⊇ {aefe} OU audience = {tous}`). Si une troisième population émerge, un ajout à l'enum suffira (changement rétro-compatible).

`to_payload_filters()` produit désormais la clé `"audience"` en plus des 5 clés existantes.

## Tests (15 passés)

| Test | Résultat |
|---|---|
| ChunkMetadata valide (complet + minimal) | PASS |
| Rejet audience vide | PASS |
| Rejet audience doublons | PASS |
| Rejet TypeDoc inconnu | PASS |
| Rejet notions vide | PASS |
| Rejet champ requis manquant | PASS |
| TypeDoc referentiel + modalite_examen | PASS |
| Audience candidat libre | PASS |
| Audience candidat individuel | PASS |
| Audience CNED libre | PASS |
| Audience AEFE | PASS |
| Audience scolarisé (défaut) | PASS |
| Filtres incluent audience (libre) | PASS |
| Filtres incluent audience (AEFE) | PASS |

## Rétro-compatibilité rag-pedago

Tests rag-pedago verts (986 passed, 1 pre-existing failure). Le test `test_retrieval_schema` passe sans modification (asserte sur des clés individuelles, pas le dict complet).

## CI locale

```
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks
  PASS  governance-guard-tests
Total: 5 passed, 0 failed
```

## BACKLOG consolidé

`docs/BACKLOG.md` créé avec les dettes : 2 tests préexistants, test ADR non automatisé, distribution nexus-contracts, commit ROADMAP hors PR.
