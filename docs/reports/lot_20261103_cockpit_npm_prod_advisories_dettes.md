# Lot 2026-11-03 — dettes préexistantes du lot « avis de sécurité production npm »

PR #345. Base : `origin/main=99178e64a9eaa8c758a907d226f23ac2b68c4066`, arbre `cf5b5356ffc5d7ac9426366ae6bf26f128c16995`.

## Échecs préexistants : deux bombes d'horloge sur `main`

Quatre jobs de CI échouent sur ce lot. **Aucun n'est causé par lui.** Les quatre échouent par péremption d'une preuve, sans aucune modification de code, et ils échouent **à l'identique** sur deux PR dont les diffs n'ont rien en commun.

### Les deux causes, mesurées

| Job | Cause unique | Date de péremption |
| --- | --- | --- |
| `services/rag-pedago` | `ReviewBindingError: review binding receipt expired at 2026-10-23T19:04:55.555052Z` — 3 échecs sur **3 614 tests** (3 611 passés) | **23 octobre 2026** |
| `services/rag-engine` | même reçu expiré : `RuntimeAuthorityStartupError`, `SealedEvidenceError`, `ReviewBindingError` | **23 octobre 2026** |
| `governance postgres` | même reçu expiré : `SEALED_SOURCES_UNUSABLE` sur `test_hggsp_successor_attestation_coexistence_pg.py` | **23 octobre 2026** |
| `services/cockpit` | `scripts/ci/cockpit_audit_policy.py` → `COCKPIT_AUDIT_POLICY=REFUSED`. Son `EXPIRES_AT` vaut `2026-10-17T23:59:59Z`, et la politique refuse « toute vulnérabilité nouvelle ou différente, de quelque sévérité que ce soit » | **17 octobre 2026** |

Sur ce dernier job, `npm ci`, `npm run lint`, `npm test -- --run` et `npm run build` **réussissent tous les quatre** ; seul le pas de politique d'audit refuse.

### Preuve d'antériorité

1. **Les deux échéances précèdent aujourd'hui et suivent le dernier vert.** La dernière CI de `main` est le **13 octobre 2026 à 04:42 UTC**, `14/14 success` (runs `38347763908` et `38347763907`). Le reçu expire le 23 octobre, l'exception le 17 octobre. Entre les deux dates, **aucun commit n'a été poussé sur `main`** : son HEAD est resté `99178e64a9eaa8c758a907d226f23ac2b68c4066`. Les mêmes tests, sur le même code, étaient verts avant l'échéance et rouges après.
2. **Contrôle croisé sur un diff disjoint.** La PR #346 ne modifie que `services/rag-engine/infra/prometheus/prometheus.v2.yml` (une ligne), un fichier de règles neuf, et un rapport de lot. Elle ne peut structurellement pas affecter `services/rag-pedago`, `services/cockpit` ni `governance postgres`. Elle reproduit pourtant **les quatre mêmes échecs, aux mêmes messages**.
3. **Les messages d'erreur portent eux-mêmes la cause.** Ils nomment un horodatage de péremption et le comparent à `now`. Il n'y a pas d'interprétation à faire.

### Conséquence à ne pas manquer

**`main` est rouge depuis le 18 octobre 2026**, et rien ne l'a signalé : aucune CI n'a été déclenchée sur `main` après le 13 octobre, faute de commit. La ligne « CI 14/14 verte » du dernier état connu **n'est plus représentative**. Tout lot ouvert à partir de maintenant héritera de ces quatre rouges jusqu'à leur traitement.

Ces péremptions ne sont pas des défauts : ce sont les garde-fous du projet qui fonctionnent. « Une preuve de revue vieillit, et une preuve périmée n'autorise jamais une publication. » Elles signalent qu'une interruption de trois semaines a invalidé les scellements, exactement comme elle a invalidé A2 et son pin.

### Ce que ce lot ne fait pas, et pourquoi

Il ne renouvelle ni le reçu de revue, ni l'exception d'audit. Les deux exigent une décision humaine qui leur est propre :

- le **reçu de revue** est lié à une revue PII signée ; le régénérer sans nouvelle revue reviendrait à redater une preuve, ce que la gouvernance interdit explicitement ;
- l'**exception d'audit** (`braces`, GHSA-vfj7-8cjw-p6xm) doit être requalifiée : soit un correctif amont est devenu disponible, soit la migration Tailwind v4 est faite, soit une nouvelle échéance est décidée et motivée. Et l'ensemble toléré a dérivé : la politique refuse désormais aussi pour des avis **nouveaux**, pas seulement pour l'échéance.

Les traiter dans ce lot mêlerait deux décisions de gouvernance sans rapport avec son objet.
