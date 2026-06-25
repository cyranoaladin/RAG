# Rapport — Lot 4.2 : Première ouverture réseau scopée

## Étape 0 — Stoplist et couverture corrigée

Ajout d'une stoplist de ~50 mots vides français (`de`, `des`, `du`, `la`, `le`, etc.) exclus du matching notion↔source. Le faux positif `formule_des_probabilites_totales` (matchait via le stopword `des`) est éliminé.

**Couverture réelle : 0/79 notions couvertes** (vs 1/79 au lot 4.1).

## Étape 1 — Levée `network_allowed` (ADR-0004)

- `network_allowed: true` dans `pedago_interface_contract.yml`, avec référence ADR-0004 sur la ligne
- `ingestion_allowed: false` — aucun import au corpus
- Baseline garde-fou mise à jour (16 verrous, `network_allowed` retiré)
- Script d'audit et tests de contrat alignés (network_allowed retiré des `REQUIRED_FALSE_FLAGS` / `DANGEROUS_FLAGS`)

## Étape 2 — Module de fetch conforme

`scrapers/fetch.py` :
- **GET uniquement** (jamais POST/PUT/DELETE)
- **Whitelist étroite** : `eduscol.education.gouv.fr`, `education.gouv.fr`, `www.education.gouv.fr`, `cache.media.eduscol.education.gouv.fr`, `cache.media.education.gouv.fr`
- **robots.txt** respecté (urllib.robotparser)
- **Rate limiting** : 2s minimum entre requêtes par domaine
- **User-Agent identifiable** : `NexusReussiteBot/0.1`
- **Timeout** : 30s ; **taille max** : 10 MB
- **URL hors whitelist refusée** : retourne `FetchRefusal`

## Étape 3 — Pilote restreint (5 notions)

Seed-list : `suites`, `derivation`, `probabilites_conditionnelles` (maths) + `recursivite`, `arbres` (NSI).
URLs officielles eduscol uniquement.

## Étape 4 — Staging

Contenu déposé en `data/staging/pilot_4_2/` (hors corpus). `ingestion_allowed=false` vérifié.

## Démonstrations

- **Whitelist** : `governed_fetch("https://example.com/...")` → `FetchRefusal(reason="domain not whitelisted")`
- **robots.txt** : mock `can_fetch=False` → `FetchRefusal(reason="blocked by robots.txt")`
- **GET uniquement** : `requests.get` appelé exactement 1 fois, jamais `requests.post`
- **Rate limit** : délai minimum 2s entre requêtes
- **Garde-fou** : `check-governance-locks.sh` passe (16/16) car ADR-0004 référencé

## Tests (19 unitaires, réseau mocké)

| Test | Vérifie |
|---|---|
| `test_whitelisted_domain` | Domaines autorisés |
| `test_non_whitelisted_domain` | Domaines refusés |
| `test_fetch_refuses_non_whitelisted` | FetchRefusal retourné |
| `test_robots_refusal` | robots.txt bloque |
| `test_robots_allowed_proceeds_to_fetch` | robots.txt autorise → fetch |
| `test_rate_limit_applied` | Délai respecté |
| `test_only_get_requests` | Seul GET appelé |
| `test_extract_text_from_html` | Extraction HTML |
| `test_quality_check_pass/too_short` | Contrôle qualité |
| `test_stopwords_excluded_from_matching` | Stoplist fonctionne |
| + 9 tests discovery (lot 4.1) | Matching strict |

## CI locale : 6/6 PASS, garde-fou 16/16
