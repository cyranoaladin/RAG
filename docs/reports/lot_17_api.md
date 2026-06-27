# Rapport — Lot 17 : API de retrieval en lecture seule (ADR-0011)

## Objectif

Exposer le retrieval pgvector derrière une API HTTP, en lecture seule, avec filtrage niveau/audience IMPOSÉ par le serveur selon le profil — pas choisi par le client.

## Levée de verrous

| Verrou | Avant | Après | ADR |
|---|---|---|---|
| `server_start_allowed` | false | true | ADR-0011 |
| `runtime_api_allowed` | false | true | ADR-0011 |

Scope STRICT : lecture seule (pas d'écriture pgvector, pas d'ingestion via l'API). `real_documents_allowed`, `qdrant_allowed`, `curated_ingestion_allowed` restent false.

Baseline : 18 clés (inchangé, mêmes clés, valeurs mises à jour).

### Gating prouvé par mutation

```
=== REAL CONTRACT ===
server_start_allowed: True
runtime_api_allowed:  True
→ API démarre

=== MUTATION: server_start_allowed=false ===
BLOCKED: server_start_allowed is false
sys.exit(1) — API refuse de démarrer

=== MUTATION: runtime_api_allowed=false ===
sys.exit(1) — API refuse de démarrer
```

## Endpoint

`POST /search` — `services/rag-engine/scripts/retrieval_api.py`

### Entrée

```json
{"query": "dérivée d'une fonction", "top_k": 3}
```

- `query` : 1-500 caractères (validation Pydantic)
- `top_k` : 1-20 (défaut 5)
- **PAS de niveau/audience dans le body** — le schéma `SearchRequest` n'a que `query` et `top_k`

### Profil serveur

Le profil est résolu côté serveur via l'en-tête `X-Student-Profile` (mapped à un `StudentProfile(niveau, audience)` depuis un registre contrôlé). En production : JWT decode ou session lookup.

Le client NE PEUT PAS forger un niveau/audience arbitraire :
- L'en-tête map vers des profils pré-définis
- Un profil inconnu → 403
- Le body n'accepte pas de champs niveau/audience (Pydantic les ignore)

### Sortie

```json
{
  "results": [...],
  "profile_niveau": "terminale",
  "profile_audience": "libre",
  "count": 3
}
```

## Filtrage non contournable — preuves réelles

### Résultats normaux

```
terminale-libre → 3 résultats dérivation (similarity 0.890, 0.867, 0.866)
terminale-aefe  → 3 résultats + accès contenu aefe
premiere-libre  → 1 résultat premiere uniquement
```

### Tentatives de contournement — TOUTES ÉCHOUENT

```
BYPASS 1: Body injecte niveau=terminale, profil=premiere-libre
→ Résultat: SEULS chunks premiere retournés. Body ignoré.

BYPASS 2: Body injecte audience=aefe, profil=terminale-libre
→ Résultat: profile_audience="libre". Body ignoré.

BYPASS 3: Pas d'en-tête X-Student-Profile
→ 422: Field required

BYPASS 4: Profil fictif "admin-all-access"
→ 403: Unknown profile

BYPASS 5: premiere-libre cherche "justice philosophie" (chunks terminale)
→ 0 chunks terminale. Seul premiere retourné.
```

### Validation d'entrée

```
Requête vide → 422: String should have at least 1 character
top_k=100   → 422: Input should be less than or equal to 20
PUT /search → 405: Method Not Allowed
DELETE      → 405: Method Not Allowed
```

## Lecture seule — aucune route d'écriture

Routes exposées :
- `GET /health`
- `POST /search`

Pas de PUT, DELETE, PATCH. Pas d'ingestion. `ingestion_allowed` reste géré côté script gouverné (`index_pgvector.py`).

## Tests (17 tests unitaires)

- 5 tests gating (server_start false/true, runtime_api false/true, missing, malformed)
- 3 tests profil (résolution, inconnu → 403, frozen)
- 4 tests validation (vide, oversized, top_k bounds)
- 2 tests injection body (extra fields ignorés, schéma strict)
- 1 test read-only (aucune route d'écriture)
- 1 test filtrage SQL (WHERE clause obligatoire niveau+audience)
- 1 test schéma (SearchRequest n'a que query+top_k)

## CI locale : 7/7 PASS

```
PASS  packages/contracts
PASS  services/rag-pedago
PASS  services/rag-engine
PASS  governance-locks
PASS  taxonomy-validation
PASS  governance-guard-tests
PASS  ci-failsafe-tests
```

Baseline 18 clés. Verrous sensibles (`real_documents`, `qdrant`, `curated_ingestion`) false.
