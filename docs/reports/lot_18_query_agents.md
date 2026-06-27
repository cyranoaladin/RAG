# Rapport — Lot 18 : Agents de requête branchés sur l'API filtrée (ADR-0012)

## Objectif

Créer une chaîne d'agents de **requête** interrogeant l'API filtrée (Lot 17) pour assembler un CONTEXTE structuré, sans générer de réponse (`answer_generation_allowed` reste false).

## Architecture

```
QueryOrchestrator(question, niveau, audience, matiere)
  ├── Vérifie answer_generation_allowed → context_only
  ├── Signe le jeton HMAC (rag-pedago = signataire de confiance)
  └── QueryLevelAgent(niveau)
        └── QuerySubjectAgent(matiere)
              └── POST /search (API rag-engine, cross-service HTTP)
                    → Contexte structuré (passages + métadonnées)
```

- Module séparé : `services/rag-pedago/query_agents/` (agents d'acquisition `agents/` intacts)
- Le profil vient de l'auth amont (simulée pour le pilote), jamais auto-attribué
- `PROFILE_SECRET` partagé entre rag-pedago (signe) et rag-engine (vérifie)

## Preuves d'exécution réelle

### PROOF 1 — Bout en bout (terminale/libre/mathematiques)

```
question: "dérivée d une fonction"
mode: context_only
count: 3 passages
  [0.8897] terminale/mathematiques/derivation
  [0.8668] terminale/mathematiques/derivation
  [0.8655] terminale/mathematiques/derivation
answer_generation_allowed: false
```

### PROOF 2 — Filtrage niveau (premiere ≠ terminale)

```
Même question, profil premiere/libre
→ count: 0 passages (aucun chunk terminale)
```

### PROOF 3 — Audience aefe a accès au contenu aefe

```
profil terminale/aefe → count: 3 (inclut contenu aefe)
```

### PROOF 4 — Audience libre ne voit PAS le contenu aefe-exclusif

```
profil terminale/libre → has aefe-exclusive chunk: False
```

### PROOF 5 — context_only enforced

```
mode: context_only
answer_generation_allowed: False
answer_generation_blocked_reason: "answer_generation_allowed is false in pedago contract"
has "answer" key: False
has "response" key: False
```

## Gouvernance

- `answer_generation_allowed` : **false** (inchangé)
- `answer_without_source_allowed` : **false** (inchangé)
- Baseline : 18 clés (inchangée)
- Le filtrage est imposé par l'API via le jeton HMAC, jamais réimplémenté côté agent
- L'agent ne peut pas élargir l'audience — il signe ce qu'il reçoit de l'auth amont

## Tests (11 tests unitaires)

- 2 tests context_only (mode + pas de prose)
- 3 tests gouvernance (answer_generation false dans contrat, answer_without_source false, blocked_reason)
- 2 tests subject agent (structure contexte, Bearer token transmis)
- 1 test level agent (routage)
- 2 tests filtrage (premiere ≠ terminale, pas de re-filtrage côté agent)
- 1 test erreur (PROFILE_SECRET absent → mode error)

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
