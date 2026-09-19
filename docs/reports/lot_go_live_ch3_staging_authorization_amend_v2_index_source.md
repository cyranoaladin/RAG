# Lot CH3 — Amendement d'autorisation SSH de staging (source d'index : release V2)

- **Lot** : `LOT_GO_LIVE_FINAL_CH3_STAGING_AUTHORIZATION_AMEND_V2_INDEX_SOURCE`
- **Branche** : `go-live/staging-authorization-amend-v2-index-source`
- **Base** : `202c428e` (`main`, après merge de #230 / lot CN)
- **Date** : 2026-09-19

> **L'approbation de cette PR par abenrhouma vaut amendement de l'autorisation
> SSH_STAGING_AUTHORIZED : le staging cloisonné sur nexus-prod peut ingérer et
> indexer la release V2 complète `production-profile-gate-2026-2027-v2` dans la
> base staging dédiée, avec 11 subjects / 315 artefacts uniques / 479
> placements / 8268 chunks, sans current switch, sans écriture DB production,
> sans ingestion production, sans exposition publique.**

Aucune connexion nouvelle n'est ouverte par cette PR. Aucun compteur modifié,
aucun blocker fermé, `STAGING_EXTERNE` non qualifié.

---

## 1. Pourquoi cet amendement — le terrain a répondu

Le lot A (autorisé séparément) a mis le dépôt de l'hôte à `202c428e`, rebuildé
l'image staging et l'a redémarrée. Résultat mesuré :

| Étape | Résultat |
|---|---|
| Dépôt hôte `b0749c35` → `202c428e` | propre, contracts **0.18.0**, 51 artefacts de scope |
| Image reconstruite, digest figé | `sha256:d0134f494a2af2895ebdeb91e55b047cd4774ca607c55e33d4dba1d6c47af8d1` |
| Contrats **dans** l'image | `version: 0.18.0` — `scopes: 52` |
| `scope source SHA differs from subject release` | **franchie** |
| Garde suivante | `RuntimeError: release database reconciliation unavailable` |

La garde qui bloque désormais est explicite :

```python
def validate_configured_release_database() -> None:
    ...
    if set(reports) != set(registry.collections) or any(
        not report.ready for report in reports.values()
    ):
        raise RuntimeError("release database reconciliation unavailable")
```

Elle exige un rapport `ready` pour **chaque** collection de la release
configurée. Or la base de staging contient un index qui ne correspond à aucune
des deux options que le plan prévoyait :

| | Attendu par le runtime (release V2) | Présent en base de staging |
|---|---|---|
| Collections | **11** | 18, dont **8 seulement** des 11 |
| Artefacts | 315 uniques | 26 |
| Chunks | 8268 | 730 |
| `hggsp_premiere` / `hggsp_terminale` / `hlp_terminale` | 39 / 35 / 89 placements | **absentes** |

L'ancienne source d'index déclarée par l'autorisation — « release multilevel
scellée (11 PDF officiels, 353 chunks) » — ne décrit ni ce qui est en base, ni
ce que le runtime réclame. **Elle est caduque dans les deux sens.**

## 2. Ce que l'amendement change

### 2.1 La source d'index cesse d'être une phrase

Jusqu'ici, `scope.staging_index_source` était du texte libre : rien ne pouvait
le contredire. CH3 en fait un **périmètre chiffré**, et le contrôleur refuse
désormais une chaîne de caractères à cet emplacement.

```json
"staging_index_source": {
  "release_id": "production-profile-gate-2026-2027-v2",
  "release_manifest_sha256": "e9506f5a…",
  "expected_counts": {
    "subjects": 11, "unique_artifacts": 315,
    "placements": 479, "unique_chunks": 8268
  },
  "contracts_version": "0.18.0",
  "contracts_scopes_available": 52,
  "target_pgvector_container": "nexus-staging-pgvector-1",
  "production_database": "forbidden",
  "supersedes": "périmètre CH/CH2 « 11 PDF officiels, 353 chunks » — caduc"
}
```

**Les quatre comptes ne sont pas estimés ici : ils sont LUS.** La release
scellée les déclare elle-même dans son `expected_counts`, et un test recompare
l'un à l'autre après avoir vérifié le digest du manifeste
(`test_les_comptes_v2_sont_ceux_de_la_release_scellee`). Le registre ne peut
donc pas s'inventer un périmètre plus large que celui que la release porte.

### 2.2 Le digest de l'image qualifiée est épinglé

`scope.ingestor_image_digest` nomme l'image construite au lot A. Une autre
image en service est un écart, refusé par le contrôleur.

### 2.3 Le plan d'exécution est mis en cohérence

Le § 2 du plan proposait deux options de source d'index ; CH3 les **arrête**
et motive la caducité des deux. Le digest du plan passe donc de
`57bcad2b…` à `a0a9a99a…`, et l'autorisation cite le nouveau — sans quoi le
contrôleur refuserait, comme il le fait déjà (« le plan d'exécution a changé
depuis l'autorisation : elle ne le couvre plus »).

## 3. Ce que l'amendement ne change pas

| Grandeur | Valeur | Statut |
|---|---|---|
| Hôte | `nexus-prod` | inchangé |
| Projet Compose | `nexus-staging` | inchangé |
| Conteneur PGVector | `nexus-staging-pgvector-1` | **obligatoire**, inchangé |
| Ports loopback | 18003 / 15435 / 19191 | inchangés |
| Liaison réseau | `127.0.0.1` | strictement loopback |
| Accès | `ssh_tunnel_only` | inchangé |
| Interdictions machine | **15** | toutes exigées, aucune retirée |
| `expires_after_use` | `true` | usage unique préservé |
| `consumed` | `false` | non consommée |

CH3 **élargit la source d'index, et rien d'autre**. Un test le prouve
(`test_ch3_n_ajoute_aucune_permission_machine`).

## 4. Épreuves

`scripts/qualification/tests/test_staging_ssh_authorization.py` : **46 épreuves**
(29 avant CH3, +17).

| Exigence | Épreuve |
|---|---|
| refuse l'ancien périmètre en phrase libre | `test_refuse_l_ancien_perimetre_en_phrase_libre` |
| accepte explicitement V2 : 11 / 315 / 479 / 8268 | `test_le_perimetre_v2_chiffre_est_accepte` |
| les comptes sont ceux de la release scellée | `test_les_comptes_v2_sont_ceux_de_la_release_scellee` |
| refuse un `PGVECTOR_CONTAINER` différent | `test_refuse_une_source_d_index_deviee[target_pgvector_container]` |
| refuse toute DB production | `test_refuse_une_source_d_index_deviee[production_database]`, `test_refuse_une_interdiction_omise[production_db_write]` |
| refuse toute exposition publique | `test_refuse_un_perimetre_elargi[access]`, `test_refuse_une_interdiction_omise[public_exposure]` |
| refuse l'omission d'une interdiction machine | `test_refuse_une_interdiction_omise` (15 cas) |
| reste à usage unique et consommable | `test_l_autorisation_amendee_reste_a_usage_unique`, `test_une_autorisation_consommee_n_autorise_plus` |
| refuse un compte altéré | `test_refuse_un_compte_v2_altere` (4 cas) |
| épingle le digest de l'image | `test_le_digest_de_l_image_staging_est_epingle` |

Contrôle fail-closed en l'état actuel de la branche :

```
{"ssh_staging_authorized": false,
 "ecarts": ["l'autorisation n'est pas (ou pas à l'identique) sur origin/main"]}
```

C'est le comportement voulu : **une autorisation ne vaut que fusionnée**.

## 5. État du staging à la clôture du lot A

| | Avant | Après |
|---|---|---|
| `nexus-staging-ingestor-1` | `Restarting (3)` | **`Exited (3)`** — arrêt ciblé |
| `nexus-staging-pgvector-1` | `Up 40 hours (healthy)` | inchangé |
| Conteneurs production | 35 | 35, **diff vide** |
| Volume | `nexus-staging_rag_pgvector_data` | intact |
| Ports en écoute | `127.0.0.1:15435` | `127.0.0.1:15435` |

`current_switch=0`, `production_db_writes=0`, `production_deployments=0`,
`public_exposure=false`, `secret_exposed=false` — les DSN ont été caviardés à
la lecture, les fichiers de secrets jamais affichés.

## 6. Ce que cette PR n'autorise pas

Aucune ingestion n'est lancée par cette PR. `STAGING_EXTERNE` n'est pas
qualifié, aucun blocker n'est fermé, `GO_LIVE_READY` reste `false`. La release
V2 n'est pas rendue promotable ; ni `promotion_status`, ni `activation_status`,
ni `review_status` ne sont touchés. Aucune modification de Nginx, DNS ou
certificat, aucune exposition publique, aucun `current switch`.

## 7. Suite

Après approbation et merge, le lot CI staging reprend : ingestion/indexation V2
en staging, vérification exacte des 11 collections et des comptes
315 / 479 / 8268, smoke tests de retrieval **avec citations** sur les onze — y
compris `hggsp_premiere`, `hggsp_terminale` et `hlp_terminale` —, smoke tests
Cockpit, rollback éprouvé, puis seulement la preuve `STAGING_EXTERNE`.
