# Lot CH4 — Autorisations LOT41A du staging V2, et base logique `ingestion-control`

- **Lot** : `LOT_GO_LIVE_FINAL_CH4_STAGING_SCOPE_AUTHORIZATION_LOT41A_AND_INGESTION_CONTROL_DB`
- **Branche** : `go-live/staging-scope-authorization-lot41a`
- **Base** : `cabc7c92` (`main`, après merge de #231 / lot CH3)
- **Date** : 2026-09-20

> **L'approbation de cette PR par abenrhouma vaut autorisation LOT41A pour créer
> et exécuter les jobs d'ingestion staging de la release V2 complète
> `production-profile-gate-2026-2027-v2`, dans le périmètre 11 subjects / 315
> artefacts uniques / 479 placements / 8268 chunks, avec publication
> exclusivement vers la base staging dédiée, sans current switch, sans écriture
> DB production, sans ingestion production, sans exposition publique.**

Aucune ingestion n'est lancée par cette PR. Aucun job créé, aucune écriture en
base, aucun blocker fermé.

---

## 1. Pourquoi ce lot existe

Le lot CI a buté sur un gate de conception, constaté et non supposé. Une fois
l'image staging reconstruite (contracts 0.18.0, 52 scopes) :

- `scope source SHA differs from subject release` → **franchie** ;
- `release database reconciliation unavailable` → bloque, parce que l'index de
  staging ne couvre pas les 11 collections V2.

En remontant la chaîne canonique jusqu'au bout :

| Constat | Conséquence |
|---|---|
| **Worker A** écrit dans une base `ingestion-control` (`ingestion_control_app`) | absente du staging |
| **Worker B** lit `ingestion-control` **et** publie dans `PG_RAG_DSN` | deux bases nécessaires |
| Aucun job sans `--scope-authorization-id` | autorisation LOT41A obligatoire |
| `authorize_scope_cli` lit la décision **uniquement depuis le dépôt**, au commit exact, et refuse si la revue n'est pas `APPROVED` sur le head attendu | **gate humain non contournable** |

C'est l'invariante d'AGENTS.md : *aucun worker n'écrit dans pgvector sans être
passé par quality → gate → review*.

## 2. Les onze autorisations

`governance/authorizations/lot41a-staging-v2-<collection>.json`, une par
collection de la release V2, au chemin **dérivé de l'identifiant seul** — il ne
peut pas désigner un fichier hors de `governance/authorizations/`.

| Champ | Source — jamais saisi à la main |
|---|---|
| `scope` (10 dimensions) | le profil `v2_livraison_319/<collection>.yml` |
| `profile_id` | `profile.scope.collection`, comme le worker le dérive |
| `profile_version` | `profile-gate-v2` |
| `profile_fingerprint` | recalculée par `profile_fingerprint()`, comparée au manifeste |
| `manifest_digest` | sha256 de `ingestion_manifest_v2_livraison_319.yml` (`d8b99a1d…`) |
| `allowed_domains` | `profile.allowed_domains`, normalisées et triées |
| `rights_categories` | `docs/governance/retrieval_scope_policy_registry.yml` |
| `pii_absence_evidence` | `pii_evidence.json` de la release V2, avec son sha256 |

Les fichiers sont écrits par `ScopeAuthorizationArtifact.canonical_bytes()`,
donc **canoniques octet à octet**. Un espace, un ordre de clés ou une casse de
domaine différents, et `parse_scope_authorization_artifact` refuse : sans cela,
deux fichiers distincts produiraient la même décision logique, et la revue
humaine ne serait plus liée à des octets précis.

**Protocole V1, délibérément.** `LOT41A-V2` exige une liste de contenus
exactement revus (`allowed_content_sha256`) qu'aucun producteur gouverné ne
rend aujourd'hui. Émettre du V2 sans ce producteur fabriquerait une
autorisation fausse.

## 3. Base logique `ingestion-control`

Créée **dans le conteneur `nexus-staging-pgvector-1` existant** :

- aucun nouveau conteneur, aucun nouveau volume, aucun service ajouté sur l'hôte ;
- `docker-compose.ingestion.yml` n'est **jamais** déployé sur `nexus-prod` — il
  porte cinq services et construirait des images hors du digest épinglé.

### Une garde qui ne valait qu'en production

`multilevel_publication_resume_cli` refusait un DSN produit identique au DSN de
contrôle — mais **uniquement dans `_enforce_production_evidence`**. En
`rehearsal`, la vérification ne s'exécutait pas : un staging pouvait publier
avec un DSN unique, effondrant la séparation des rôles précisément là où on la
qualifie.

CH4 extrait ce refus dans `_require_distinct_control_and_product_dsn()` et
l'applique à **tous** les environnements. C'est un ajout de garde ; rien n'est
retiré, et la production conserve toutes ses exigences supplémentaires.

## 4. Épreuves

`scripts/qualification/tests/test_staging_scope_authorizations_lot41a.py` —
**25 épreuves**.

| # | Exigence | Épreuve |
|---|---|---|
| 1, 10 | pas d'autorisation, pas de job ; identifiant inconnu refusé | `test_chaque_autorisation_est_a_son_chemin_canonique`, `test_un_identifiant_inconnu_n_a_pas_d_artefact`, `test_un_identifiant_non_canonique_est_refuse` |
| 2, 3, 4 | la revue est liée aux octets exacts | `test_les_octets_commits_sont_canoniques`, `test_toute_alteration_d_octet_casse_la_canonicite` (3 cas), `test_l_artefact_ne_porte_jamais_sa_propre_approbation` |
| 5, 6, 7 | périmètre = release V2, ni manquante ni supplémentaire | `test_une_autorisation_par_collection_de_la_release`, `test_aucune_collection_hors_release` |
| 8 | comptes de la release | `test_les_comptes_de_la_release_sont_ceux_attendus`, `test_le_digest_du_manifeste_de_release_est_celui_scelle` |
| 9 | `profiles_dir` v2 | `test_les_empreintes_de_profil_sont_celles_du_manifeste`, `test_chaque_autorisation_cite_le_manifeste_de_profils_v2` |
| 11 | DSN control ≠ produit, **dans tous les environnements** | `test_la_garde_de_separation_des_dsn_n_est_plus_reservee_a_la_production`, `test_la_garde_refuse_effectivement_deux_dsn_identiques` |
| 12, 13, 14 | jamais `rag_pgvector` ni ressource de production | `test_aucune_autorisation_ne_nomme_une_ressource_de_production` |
| 15 | HGGSP ×2 et HLP terminale couvertes | `test_les_trois_collections_hggsp_hlp_sont_autorisees` |
| 16 | manifeste de transfert cité et intact | `test_le_manifeste_de_transfert_du_corpus_est_present_et_intact` |
| 17 | ni release ni scope packagé modifiés | `test_aucune_release_n_est_modifiee_par_ce_lot`, `test_aucun_scope_de_retrieval_n_est_modifie_par_ce_lot` |

S'y ajoute `test_aucune_autorisation_ne_contient_de_secret` : une décision
n'est pas un identifiant — ni DSN, ni mot de passe.

`test_staging_ssh_authorization.py` reste vert (**46 épreuves**) : le plan
d'exécution est amendé (§ 3 bis), son digest passe de `a0a9a99a…` à
`52d43cb7…`, et l'autorisation SSH cite le nouveau. Sans ce réalignement, le
contrôleur refuserait — et il refuse déjà tant que la PR n'est pas fusionnée :

```
{"ssh_staging_authorized": false,
 "ecarts": ["l'autorisation n'est pas (ou pas à l'identique) sur origin/main"]}
```

## 5. Preuves déjà acquises, jointes au lot

| Preuve | Empreinte |
|---|---|
| Transfert du corpus V2 — 315/315 digests conformes sur l'hôte | `1f63939b…` |
| Snapshot pré-ingestion — 26 artefacts / 730 chunks / 18 collections | `bb340020…` |
| Backup `pg_dump -Fc` dans `/srv/nexus-staging/backups/` | `e4b3f852…` |
| Image staging qualifiée | `sha256:d0134f49…` |

Le snapshot établit que **13 artefacts en base sont hors périmètre V2** : la
preuve `STAGING_EXTERNE` devra montrer qu'ils ne subsistent pas dans l'index
final.

## 6. Un gate ultérieur, signalé dès maintenant

Les profils V2 portent `publication: {mode: human_review, auto_publish: false}`.
Worker B n'attribue donc pas `RETRIEVAL_ELIGIBLE` sans attestation de revue de
publication. Les placements de la release V2 déclarent `review_status:
reviewed`, ce qui **devrait** satisfaire le résolveur — mais je ne l'ai pas
encore prouvé sur le terrain. Si un gate LOT42 apparaît après CH4, il sera
rapporté, pas contourné.

## 7. Ce que cette PR n'autorise pas

Aucune ingestion, aucun job, aucune écriture en base. `STAGING_EXTERNE` non
qualifié, `GO_LIVE_READY` reste `false`. La release V2 n'est pas modifiée ni
rendue promotable ; `promotion_status`, `activation_status` et `review_status`
sont intacts. Aucun service ni volume ajouté sur `nexus-prod`, aucun
`current switch`, aucune écriture en base production, aucune exposition
publique, aucun Nginx / DNS / certificat.
