# Lot go-live — actualité de la preuve PII au 8 octobre 2026

- Base de travail propre : `ee35544bce5af74d6186ea0ef61f6902a2258ffe`, arbre `e7f13396a17676ceba5550d039b50a6a2160838f`.
- Source CI : [main, run 37730000035](https://github.com/cyranoaladin/RAG/actions/runs/37730000035), démarré le 2026-10-08 à 04:57 UTC.
- Portée du lot : tests d'actualité et plan de renouvellement. Aucune preuve scellée, release, clé, autorisation, donnée staging ou production n'est modifiée.

## Constat opposable

Les cinq échecs PII de ce run (deux `rag-pedago`, trois `rag-engine`) relisent le reçu de la campagne historique du 3 septembre comme s'il autorisait encore une publication le 8 octobre. Le reçu `pii-review-2026-09-03-final.json` a expiré le **2026-10-03T22:02:48.263884Z**. Le vérificateur canonique le refuse correctement (`review binding receipt expired`) : prolonger sa date, ignorer l'horloge ou assouplir le vérificateur serait une régression.

La chaîne V4/V5 effectivement scellée utilise une autre campagne :

| Élément | Mesure sur cette base |
|---|---|
| décisions PII | `pii-review-2026-09-22-profile-gate-v3.json`, SHA-256 `1b70d91b52d207d301d87076573593cb0899ed2b52d6e2963fbcf8fcd3472a66` |
| index | `pii_review_index_20260922_profile_gate_v3.json`, SHA-256 `abdd15256eba9ed5717529327131b0afe6f5de17189180bd082fd2a9bfeadb55` |
| reçu | `pii-review-2026-09-22-profile-gate-v3.json`, SHA-256 `22361dd17df811425d87f14ff33649efca320a8ee63292023ff5187d977bd55d` |
| émission | PR #249, review `5295099308`, décision `APPROVED`, 22 contenus détectés sur 315 revus |
| expiration | **2026-10-23T19:04:55.555052Z** |
| releases épinglant ce reçu | V4 `profile_gate_v3/release-f8fb983d04f4b7c1` et V5 `profile_gate_hggsp_v5/release-b34b11e678bf9559` |

Ces mesures sont celles des fichiers versionnés de la base, pas une mesure du staging final ou de la production. Le test positif ajouté vérifie la signature et l'actualité du reçu V4/V5 à l'heure réelle, puis compare son empreinte aux deux `authority_bindings.json`. Il devient volontairement rouge si ce reçu expire : la CI doit exiger une nouvelle revue gouvernée, jamais figer son horloge ni donner un faux vert à une preuve périmée. Le test négatif ajouté exige que le producteur et le moteur refusent le reçu du 3 septembre à l'heure réelle. Les seuls tests historiques positifs du moteur sont rejoués au 4 septembre, après émission et avant expiration ; ils ne prétendent plus qualifier une publication courante. Les deux tests du producteur qui exercent l'index et la population passent à la campagne V4/V5 courante.

## Renouvellement gouverné avant expiration

La PR #249 est **MERGED**. Le vérificateur canonique exige une PR ouverte (`pull_request_not_open`) et une review `APPROVED` sur son HEAD et sa base exacts. Son ancien HEAD et sa review ne permettent donc pas d'émettre aujourd'hui un nouveau reçu par simple réexécution de `issue_review_binding_cli`. Le reçu actuel reste valable jusqu'à la date ci-dessus ; aucune réémission préventive non gouvernée n'est faite par ce lot.

Si le cutover ou une nouvelle release dépasse cette date, constituer **sur la population finale effectivement publiée** une nouvelle campagne canonique ADR-0047 : scan des contenus exacts, index de revue et paquets hors Git, décisions individuelles pour chaque détection, PR dédiée au nouvel ensemble de décisions, review humaine du Code Owner `abenrhouma` avec challenge ADR-0025 recalculé sur base/HEAD live, puis reçu ADR-0035 signé localement par le détenteur de `review-binding-v1-2026-08-25` après relecture GitHub live par l'émetteur canonique. L'opérateur fournit la clé à l'outil hors dépôt ; elle ne passe ni dans Git, ni dans CI, ni dans une conversation. Vérifier le reçu hors ligne contre l'ancre et les octets approuvés. Une empreinte de reçu ou de décision différente exige de **nouvelles identités de release** et la reconstruction de leur chaîne de manifests/registry ; ADR-0050 interdit de resceller V4 ou V5 en place. Requalifier ensuite staging, retrieval, qualité et readiness au nouvel ensemble.

Le dossier de renouvellement ne peut pas être présenté comme une nouvelle autorisation déjà accordée : les paquets complets contiennent la matière brute hors Git, la population finale peut changer avec la release publique étudiant, et le review/head ainsi que le challenge n'existent pas encore. Le human gate concret est la future review du **nouveau** jeu de décisions au HEAD exact, puis la signature offline de son reçu. À la date de ce rapport, la chaîne V4/V5 existante ne demande pas ce gate pour sa seule actualité PII.

## Vérification du lot

- Référence RED : run main `37730000035`, cinq échecs nommés ci-dessus dus à l'expiration du reçu historique.
- Rejeu local sur le worktree #285 au HEAD `55abb99e22ecee188282977c9aa4016ecb1b31d9`, avec `PYTHONPATH=src:../../packages/contracts/src:../../packages/release-chain/src:../../packages/pdf-page-policy/src` pour charger les paquets de ce worktree : depuis `services/rag-pedago`, `python3 -m pytest -q tests/test_build_release_pii_projection.py tests/test_pii_review_projection.py` → **91 passed** ; depuis `services/rag-engine`, `python3 -m pytest -q tests/test_pii_human_review_admission.py tests/test_review_binding_producer.py` → **84 réussis**. Le commit source #288 a également été vérifié dans ses propres venvs isolés ; aucun venv d'un autre checkout n'est réutilisé ici. La CI complète du HEAD final constitue le verdict de merge.
- Depuis la racine de ce worktree : `python3 -m ruff check services/rag-engine/tests/test_pii_human_review_admission.py services/rag-pedago/tests/test_build_release_pii_projection.py` → **All checks passed** ; `bash scripts/check-governance-locks.sh` → **18 clés vérifiées** ; `bash scripts/check-repository-hygiene.sh` → **PASS**. Verrous et chemins scellés : inchangés.
