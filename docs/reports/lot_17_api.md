# Rapport — Lot 17 : API de retrieval en lecture seule (ADR-0011)

## Objectif

Exposer le retrieval pgvector derrière une API HTTP, en lecture seule, avec filtrage niveau/audience IMPOSÉ par le serveur selon un profil **cryptographiquement signé** (HMAC-SHA256) — pas choisi par le client.

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
server_start_allowed: True → API démarre

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

### Authentification du profil (Lot 17.1 — HMAC-SHA256)

Le profil est transporté dans un jeton signé HMAC-SHA256 :

```
Authorization: Bearer {"niveau":"terminale","audience":"libre"}.<hmac_hex>
```

- Le payload encode `{niveau, audience}` en JSON canonique
- Le HMAC est calculé avec `PROFILE_SECRET` (variable d'environnement serveur, jamais commitée)
- `resolve_profile` **recalcule** le HMAC côté serveur et **rejette (401)** si la signature ne correspond pas
- Un client **sans le secret** ne peut pas produire une signature valide pour AUCUN profil

`GET /test/token?niveau=...&audience=...` : utilitaire de test pour émettre un jeton valide (non destiné à la production).

### Sortie

```json
{
  "results": [...],
  "profile_niveau": "terminale",
  "profile_audience": "libre",
  "count": 3
}
```

## Filtrage non contournable — preuves réelles (Lot 17.1)

### PROOF 1 — Jeton valide premiere-libre

```
profile: premiere/libre
count: 1
  [0.861] premiere/mathematiques
→ Accès premiere uniquement. OK.
```

### PROOF 2 — USURPATION : token premiere-libre + body revendique terminale

```
Token signé pour: premiere/libre
Body envoie: {"niveau": "terminale", "audience": "aefe"}
→ profile: premiere/libre (du token SIGNÉ, PAS du body)
→ count: 1 (premiere uniquement)
→ Le contenu suit le profil signé, pas la prétention du client.
```

### PROOF 3 — FORGERIE : token signé avec MAUVAIS secret

```
Forged token for terminale-aefe with "attacker-secret"
→ {"detail": "invalid signature"}
→ 401 REJETÉ. Sans le secret serveur, on ne peut pas forger de profil.
```

### PROOF 4 — ALTÉRATION : payload modifié après signature

```
Token original: terminale/libre
Tampered: libre→aefe dans le payload, signature inchangée
→ {"detail": "invalid signature"}
→ 401 REJETÉ. La modification du payload invalide le HMAC.
```

### PROOF 5 — Pas de token

```
→ 422: Field required (Authorization header)
```

### PROOF 6 — Token valide terminale-libre

```
profile: terminale/libre
count: 3
  [0.8897] terminale/mathematiques (dérivation)
  [0.8668] terminale/mathematiques (dérivation)
→ Accès normal avec profil vérifié.
```

### Validation d'entrée (acquis Lot 17)

```
Requête vide → 422: String should have at least 1 character
top_k=100   → 422: Input should be less than or equal to 20
PUT /search → 405: Method Not Allowed
DELETE      → 405: Method Not Allowed
```

## Lecture seule — aucune route d'écriture

Routes exposées :
- `GET /health`
- `GET /test/token` (utilitaire de test)
- `POST /search`

Pas de PUT, DELETE, PATCH. Pas d'ingestion via l'API.

## Tests (25 tests unitaires)

- 5 tests gating (server_start false/true, runtime_api false/true, missing, malformed)
- 7 tests HMAC (roundtrip, forgerie wrong secret, payload tampered, malformed, invalid niveau, invalid audience, frozen)
- 4 tests resolve_profile (bearer valide, prefix manquant, token forgé → 401, secret absent → 500)
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
