# Lot 2026-11-03 — cadencer la campagne de source, et s'arrêter au lieu de marteler

## Déclencheur : un blocage Cloudflare a arrêté le rescellement A3

Le 3 novembre 2026 à 12:09 UTC, la capture des listings Éduscol a rendu **14/14 HTTP 200**. La matérialisation de provenance qui a suivi a émis **392 GET de PDF en environ quarante-cinq secondes**. À 12:11 UTC, l'intégralité du domaine `eduscol.education.gouv.fr` est devenue inaccessible depuis ce poste :

```
HTTP/2 403
server: cloudflare
cf-ray: a54ba7d67c7bfffb-AMS

« Attention Required! | Cloudflare — Sorry, you have been blocked.
  You are unable to access eduscol.education.gouv.fr »
```

Contrôle positif décisif : les pages qui répondaient **200** vingt minutes plus tôt renvoyaient **403** après la campagne. Ce n'est donc pas une page disparue, c'est **notre propre débit** qui a déclenché la protection de la source. Onze essais espacés de cinq minutes sur **soixante-dix minutes** sont tous restés en 403.

Conséquence directe : la campagne d'actualité A3 ne peut plus être rejouée, donc l'autorité temporelle ne peut pas être rescellée, donc **le chemin critique du go-live est arrêté** par un garde-fou que nous avons nous-mêmes déclenché.

## Le défaut : une politique déclarée mais non implémentée

`services/rag-pedago/configs/pedago_interface_contract.yml` porte :

```yaml
network_allowed: true  # ADR-0004 — scoped fetch (GET-only, whitelist, robots.txt, rate limit)
```

ADR-0004 exige explicitement « **rate limiting** et user-agent identifiable » et « **robots.txt respecté** sans exception ». État mesuré de la chaîne de récupération avant ce lot :

| Exigence ADR-0004 | État | Preuve |
| --- | --- | --- |
| GET-only | **conforme** | `urllib` en GET, aucun autre verbe |
| whitelist de domaine | **conforme** | `ALLOWED_HOST = "eduscol.education.gouv.fr"` |
| user-agent identifiable | **conforme** | `NexusSourceIdentityVerifier/1` |
| **rate limiting** | **ABSENT** | 0 occurrence de `sleep`, `backoff`, `throttle`, `Retry-After` dans les trois scripts de la chaîne |
| **robots.txt** | **ABSENT** | 0 occurrence |

Le verrou de gouvernance annonçait donc une politique que le code n'appliquait pas. Ce n'est pas un défaut cosmétique : il est exactement ce qui sépare aujourd'hui le projet de sa release.

## Correctif — un seul point, parce que tout y passe

Le débit est appliqué dans `_fetch_urllib` de `scripts/go_live/student_rights_source_check.py`. C'est le transport partagé par la vérification de source, l'observation des PDF et le suivi des redirections : le placer plus haut laisserait un appelant sans garde-fou.

Le GET nu est isolé dans `_open_url`, et `_fetch_urllib` l'encadre de trois garde-fous :

1. **Intervalle minimum entre deux GET** — `FETCH_MIN_INTERVAL_SECONDS`, défaut **0,75 s**. Les 392 récupérations de la campagne prennent alors environ cinq minutes au lieu de quarante-cinq secondes.
2. **`Retry-After` respecté**, borné par `FETCH_RETRY_AFTER_MAX_SECONDS` (défaut 30 s) pour qu'un en-tête hostile ne suspende pas une campagne indéfiniment.
3. **Disjoncteur** — après `FETCH_RATE_LIMIT_STREAK_LIMIT` refus de débit **consécutifs** (défaut 5, sur 403/429/503), la campagne lève `SOURCE_RATE_LIMITED` au lieu de continuer. Un succès remet le compteur à zéro : un refus isolé ne condamne pas une campagne par ailleurs saine.

C'est le troisième qui compte le plus. Les scripts étaient déjà *fail-closed* au sens du verdict — un PDF non récupéré devient `SOURCE_UNPROVEN` — mais un outil fail-closed qui émet trois cent quatre-vingt-douze appels avant de constater qu'il est bloqué reste un outil qui martèle. Avec ce lot, la campagne du 3 novembre se serait arrêtée après cinq refus.

Les trois seuils sont surchargeables par variable d'environnement (`NEXUS_SOURCE_FETCH_MIN_INTERVAL_SECONDS`, `NEXUS_SOURCE_FETCH_RETRY_AFTER_MAX_SECONDS`, `NEXUS_SOURCE_FETCH_RATE_LIMIT_STREAK_LIMIT`) : un opérateur peut ralentir davantage, jamais accélérer sans le décider explicitement.

## Vérifications

TDD : les cinq tests de `scripts/tests/test_student_rights_source_fetch_pacing.py` ont d'abord échoué sur `reset_fetch_pacing` absent, puis passé après implémentation.

| Contrôle | Résultat |
| --- | --- |
| `test_student_rights_source_fetch_pacing.py` | **5 / 5** |
| Suites liées : `source_check`, `source_provenance`, `attest_..._currentness`, pacing | **49 / 49** |
| `scripts/tests` (hors 5 modules à dépendances absentes du venv) | **1 299 passés**, 46 ignorés, 3 échecs |
| Les 3 échecs | `ModuleNotFoundError: fitz` et `jsonschema` — **préexistants**, reproduits sur le HEAD sans ce diff ; aucun des trois n'importe le module modifié |
| `ruff check` sur les deux fichiers | All checks passed |
| `scripts/check-governance-locks.sh` | 18/18 conformes |
| `git diff --check` | propre |

## Portée et limites

- **`robots.txt` n'est pas implémenté par ce lot.** L'exigence d'ADR-0004 reste donc partiellement non tenue. Ce lot traite la cause du blocage constaté ; le respect de `robots.txt` est un ajout distinct, à décider séparément pour ne pas mêler deux changements de politique réseau dans une même revue.
- **Le SHA de ce transport n'est inscrit dans aucune attestation.** L'index de provenance épingle `source_checker_code_sha256` (`student_rights_source_provenance.py`) et `capture_script_sha256` (`capture_eduscol_source_listings.py`), mais **pas** `student_rights_source_check.py`. Une modification du transport est donc invisible aux attestations. Ce lot en bénéficie — il ne périme aucune preuve existante — mais le trou de traçabilité est réel et doit être instruit.
- **Ce lot ne débloque pas Cloudflare.** Le blocage en cours est côté source et ne se lève pas par un changement de code. Il évite la récidive à la prochaine campagne.
- Aucune autorité, aucun scope, aucun contenu, aucun verrou de gouvernance n'est touché. Aucun déploiement.

## Gate

Review exact-HEAD et CI standard verte. La campagne A3 devra être rejouée **avec** ce correctif fusionné, une fois l'accès à la source rétabli, et en passant `--extra-listing-url` pour la page DGEMC afin d'atteindre les 15 listings qu'exige l'attestation.
