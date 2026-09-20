# LOT_GO_LIVE_FINAL_CH6_STAGING_WORKER_IMAGE_AUTHORIZATION

- **Branche** : `go-live/ch6-staging-worker-image-authorization`
- **Base** : `24b28d41` (#236, point d'entrée orienté release scellée)
- **Décision attendue** : `GO_LIVE_CH6_STAGING_WORKER_IMAGE_AUTHORIZATION_PR_OPEN`
- **Amende** : `docs/reports/go_live/authorizations/staging_ssh_authorization.json` (CH2, CH3, CH4 → **CH6**)

> Ce lot ne construit rien sur `nexus-prod`, n'y tire aucune image, n'y démarre
> aucun conteneur, ne touche ni la base produit, ni `current`, ni Nginx. Il
> autorise — il n'exécute pas.

## Le fait qui rend ce lot nécessaire

L'image épinglée du périmètre staging,
`sha256:d0134f494a2af2895ebdeb91e55b047cd4774ca607c55e33d4dba1d6c47af8d1`,
**est l'API de retrieval** : son `CMD` est `uvicorn api_v2:app`. Elle ne porte
ni `httpx` ni la pile `ingestion_agents`. Tentative mesurée :

```
ModuleNotFoundError: No module named 'ingestion_agents'
```

Les trois autres images présentes sur l'hôte ne conviennent pas davantage :
`infra-ingestor:latest` et `nexus-rag-ingestor-security:da0a167` embarquent
`nexus-contracts 0.2.0` — le dépôt en déclare `0.19.0` —, et
`compose-ingestor:latest` n'a pas `psycopg`.

Aucune image présente ne peut donc exécuter le point d'entrée d'ingestion de
release scellée. Ce n'est pas une régression du lot CO : c'est un fait
antérieur, qui vaut identiquement pour Worker A.

## Ce que le lot autorise

Une **seconde** image, qui ne remplace pas la première :

| | Image API (inchangée) | Image worker (CH6) |
|---|---|---|
| Digest | `sha256:d0134f49…` | `sha256:2ce7533d…` |
| Rôle | `uvicorn api_v2` | point d'entrée d'ingestion |
| `nexus-contracts` | 0.18.0 | **0.19.0** |
| Épinglage | par digest, sans rebuild | par digest, sans rebuild |

Chacune déclare la version de contrats qui est réellement la sienne. Écrire
0.19.0 pour l'image API aurait été faux ; CH6 ne touche pas à sa ligne.

Référence complète autorisée :

```
ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:2ce7533d00e171f47d42a579ad6afe1d8b5d51e91c63f14cf6ae051592109029
```

## Construite hors `nexus-prod`, par le producteur gouverné

L'image n'a pas été construite à la main : elle sort du workflow déjà gouverné
`.github/workflows/production-image-provenance.yml` (ADR-0036), qui refuse
toute référence autre que `refs/heads/main`, construit dans GitHub Actions,
pousse avec attestation de provenance et SBOM, et publie un
`NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1`.

| Fait | Valeur |
|---|---|
| Run | `35524322769`, tentative 1 |
| Commit source | `24b28d417d1f99ebe8f37363d75b73a83ffe87ff` |
| Arbre source | `503e07e5e7b6c4250f0c57ad9723d7390cd4f48a` |
| Dockerfile | `Dockerfile.multilevel-worker-production` |
| `dockerfile_sha256` | `feeceb7813ad2cfb38e984ceef12cf51088c7054d13045ff03ab30eba57c60de` |
| Construit le | 2026-09-20T17:01:45Z |
| Construit sur `nexus-prod` | **non** |

Le commit source est exactement le `main` qui porte le point d'entrée.

## Ce qui a été mesuré sur les octets réels

Vérification faite **sur le poste de travail**, hors `nexus-prod` : `docker pull`
par digest, puis exécution `--network none`.

```
contracts      : 0.19.0
httpx          : present     psycopg : present     pydantic : present
cryptography   : present     yaml    : present
import ingestor.ingestion_agents.classifier                  : OK
import ingestor.ingestion_worker.sealed_release_ingestion     : OK
import ingestor.ingestion_worker.sealed_release_ingestion_cli : OK
import ingestor.ingestion_control.provisioning                : OK
```

Secrets : dix variables d'environnement, aucune porteuse de secret ; aucun
fichier `.env`, clé privée, `credentials` ou `.netrc`. Seuls le bundle CA du
système et la clé GPG de l'image de base Python sont présents — attendus l'un
et l'autre.

**Un point à ne pas passer sous silence** : le `CMD` par défaut de cette image
est `python -m ingestor.ingestion_worker.multilevel_cli`, c'est-à-dire
Worker A. CH6 **n'autorise pas** cette commande. L'autorisation nomme un seul
module exécutable et en interdit deux nommément :

```json
"allowed_entrypoint_module": "ingestor.ingestion_worker.sealed_release_ingestion_cli",
"forbidden_entrypoint_modules": [
  "ingestor.ingestion_worker.multilevel_cli",
  "ingestor.ingestion_worker.multilevel_publication_resume_cli"
]
```

L'image sait lancer les deux workers ; l'autorisation, non.

## Ce qui ne bouge pas

`pinned_by_digest_no_rebuild` est maintenu, `tag_alone_accepted` est `false`,
`build_on_nexus_prod` est `forbidden`, le réseau reste `loopback_only`, l'accès
reste `ssh_tunnel_only` sur `127.0.0.1`, aucun service durable n'est créé,
aucun fichier Compose n'est déposé sur l'hôte, la base produit reste interdite,
et les quinze interdictions de l'autorisation sont intactes.

## Preuves

`docs/reports/evidence/staging_worker_image_provenance.json`, lié par digest
depuis l'autorisation elle-même (`scope.staging_worker_image.evidence.sha256`)
— un test vérifie que le digest déclaré est celui du fichier.

### Les neuf épreuves demandées

| # | Exigence | Test |
|---|---|---|
| 1 | ancienne image API refuse / sans `ingestion_agents` | `test_1_…`, `test_1bis_…`, `test_1ter_…` |
| 2 | nouvelle image contient `ingestion_agents` | `test_2_l_image_worker_contient_ingestion_agents` |
| 3 | nouvelle image déclare contracts 0.19.0 | `test_3_…`, `test_3bis_aucun_secret_dans_l_image` |
| 4 | digest obligatoire | `test_4_le_digest_est_obligatoire` |
| 5 | tag seul refusé | `test_5_…`, `test_5bis_…`, `test_5ter_…` |
| 6 | build sur `nexus-prod` refusé | `test_6_…`, `test_6bis_…`, `test_6ter_…`, `test_6quater_…` |
| 7 | base produit interdite | `test_7_la_base_produit_reste_interdite` |
| 8 | `current switch` interdit | `test_8_le_current_switch_reste_interdit` |
| 9 | image bornée au périmètre staging | `test_9_…`, `test_9bis_…`, `test_9ter_…`, `test_9quater_…`, `test_9quinquies_…` |

```
python3 -m pytest scripts/qualification/tests/ -q     264 passed, 2 skipped
ruff check                                            All checks passed!
```

### Un test existant a dû être précisé, sans être affaibli

`test_aucun_secret_ni_adresse_dans_l_autorisation` interdisait tout `@` dans
l'autorisation — le motif traque une **adresse** (courriel, `user@hôte`).
Une référence d'image par digest en contient un : `nom@sha256:…`. C'est
l'inverse d'un secret — une empreinte publique.

Le filtre retire donc cette seule forme et continue de refuser tout autre `@`.
Un test ajouté le prouve sur `operateur@example.org`, `root@88.99.254.59` et
`a@b` : les trois échouent toujours.

## L'autorisation n'est pas encore effective

`check_staging_authorization.py` répond aujourd'hui :

```json
{"ssh_staging_authorized": false,
 "ecarts": ["l'autorisation n'est pas (ou pas à l'identique) sur origin/main"]}
```

C'est le comportement voulu : l'amendement n'autorise rien tant qu'il n'est pas
fusionné sur `main` par une PR à revue humaine épinglée. Aucun écart de
périmètre n'est signalé — seule l'absence de fusion l'est.

## Ce lot ne débloque pas l'exécution à lui seul

CH6 fournit l'image. Il reste le second blocage, traité par le lot **CQ**
(`LOT_GO_LIVE_FINAL_CQ_REHEARSAL_READINESS_TRUST_CHAIN`) : il n'existe aucune
chaîne de readiness de répétition, et le point d'entrée en exige une. Les deux
lots sont cumulatifs — voir
`docs/reports/evidence/sealed_release_entrypoint_staging_execution_blocked.json`.

Après fusion des deux, et dans cet ordre seulement : configuration des
variables `NEXUS_READINESS_*` côté staging, vérification de la readiness,
tirage de l'image par digest, exécution du point d'entrée, vérification
11 / 315 / 479 / 8268 et `NEEDS_REVIEW`, preuve — puis, et pas avant,
`LOT_GO_LIVE_FINAL_CI_LOT42_RELEASE_BATCH_ATTESTATION`. Worker B ne tourne pas
avant cette attestation.
