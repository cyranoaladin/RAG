# Lot — Stockage LOT42-RELEASE-BATCH-V1 (migration 014)

- **Lot** : `LOT_GO_LIVE_FINAL_CI_LOT42_RELEASE_BATCH_STORAGE_MIGRATION`
- **Branche** : `go-live/lot42-release-batch-storage-migration`
- **Base** : `363a545c` (`main`, après merge de #234 / ADR-0056)
- **Date** : 2026-09-20
- **Option retenue** : **B** — extension typée, contrainte conditionnelle

---

## 1. Le blocage que cette migration lève

ADR-0056 a décidé qu'une release scellée n'a pas d'URL canonique
documentaire. Le schéma, lui, l'exigeait encore. Deux faits mesurés :

**La machine d'états est strictement séquentielle.**

```
DISCOVERED -> CANDIDATE     : True
DISCOVERED -> NEEDS_REVIEW  : False
CANDIDATE  -> STAGED        : False
```

Atteindre `NEEDS_REVIEW` impose donc de passer par `CANDIDATE`.

**`CANDIDATE` suppose une ligne `resource_candidates`**, dont `canonical_url`
était `NOT NULL` avec `CHECK (btrim(...) <> '')`.

Conclusion : une release scellée ne pouvait **pas** atteindre `NEEDS_REVIEW`
sans fabriquer une URL. Le point d'entrée orienté release était bloqué avant
d'être écrit.

## 2. Ce que la migration fait — et ne fait pas

Elle ne rend rien nullable globalement. Elle reprend **l'idiome déjà posé par
la migration 013** — une contrainte conditionnelle par protocole — et l'étend
à `canonical_url` :

| Origine | `canonical_url` |
|---|---|
| `resource_pipeline` / `LOT42-V1` / `LOT42-V2` | **obligatoire et non vide** — inchangé |
| `sealed_release_pipeline` / `LOT42-RELEASE-BATCH-V1` | **doit être `NULL`** |

« Doit », pas « peut ». Une valeur fabriquée pour une release scellée est
**refusée par la base**, pas seulement déconseillée par une convention. C'est
la différence entre rendre une colonne nullable et déclarer qu'une identité
documentaire n'existe pas pour cette origine.

L'origine devient une donnée déclarée — `pipeline_kind` sur `resources` et
`resource_candidates`, par défaut `resource_pipeline`, ce qui préserve
intégralement l'existant.

### `artifacts` n'est pas touchée

Elle ne porte aucun `canonical_url`. Ses champs `original_url` / `final_url`
sont de la **provenance** — d'où l'objet vient —, ce qu'une `source_url` de
release renseigne légitimement. Les confondre avec une identité canonique
serait précisément l'erreur que cette migration ferme. Un test vérifie que la
migration ne mentionne jamais `source_url`.

## 3. Le rollback refuse plutôt que de fabriquer

Même doctrine que le rollback 013. Revenir en arrière signifie réimposer
`canonical_url NOT NULL`. Si des lignes de release scellée existent, trois
issues, dont deux interdites :

- leur inventer une URL — le rollback deviendrait le chemin par lequel la
  fabrication entre ;
- les supprimer — destruction de preuves ;
- **refuser** — seule issue honnête, retenue.

Le refus est levé **avant** toute modification, et les trois tables sont
verrouillées en `ACCESS EXCLUSIVE` pendant la vérification : aucune ligne ne
peut apparaître entre le contrôle et la bascule.

## 4. Preuves — 20 statiques + 8 sur PostgreSQL réel

`tests/integration/test_lot42_release_batch_migration_014.py` exécute un
conteneur `pgvector:pg16` jetable, migré par le **vrai** script de bootstrap.
Les refus mesurés sont de vrais refus PostgreSQL, pas des assertions sur du
texte.

| # | Exigence | Épreuve |
|---|---|---|
| 1, 2, 3 | `resource_pipeline` / V1 exigent toujours une URL non vide | `test_resource_pipeline_refuse_une_canonical_url_absente`, `…_vide`, `test_lot42_v1_et_v2_exigent_toujours_une_canonical_url_non_vide` |
| 4 | release scellée acceptée sans `canonical_url` | `test_une_release_scellee_est_acceptee_sans_canonical_url` |
| 5 | **URL fabriquée refusée par la base** | `test_une_canonical_url_fabriquee_pour_une_release_est_refusee_par_la_base` |
| 6, 7 | `source_url` conservée, jamais promue | même épreuve (vérifie les deux colonnes) + `test_source_url_n_est_jamais_ecrite_dans_canonical_url` |
| 8, 10 | contraintes conditionnelles en place | `test_l_origine_est_une_colonne_contrainte_a_deux_valeurs`, `test_le_troisieme_protocole_est_admis_partout_ou_il_doit_l_etre` |
| 9 | `artifacts` : provenance ≠ identité | `test_la_migration_ne_touche_pas_artifacts` |
| 11 | **`NEEDS_REVIEW` atteignable pour une release** | `test_une_release_scellee_peut_atteindre_needs_review` |
| 12 | machine d'états inchangée pour `resource_pipeline` | `test_resource_pipeline_accepte_une_canonical_url_reelle` |
| 13 | migration réversible et auditable | `test_le_rollback_refuse_plutot_que_de_fabriquer_ou_de_detruire`, `test_le_rollback_verrouille_avant_de_compter`, `test_le_rollback_ne_supprime_aucune_ligne`, `test_le_rollback_refuse_et_ne_modifie_rien_si_une_release_existe` |
| 14 | aucune table production | `test_la_migration_ne_touche_que_le_schema_ingestion_control` |
| 15 | aucune publication | `test_la_migration_ne_declenche_aucune_publication` |
| 16 | aucune attestation | `test_la_migration_n_insere_aucune_attestation` |
| 17, 18 | conforme à ADR-0056, aucune release modifiée | `test_une_release_scellee_doit_avoir_canonical_url_null`, `test_la_release_scellee_n_a_aucune_branche_permissive` |

S'y ajoutent : la migration est transactionnelle, aucune colonne n'est ouverte
sans contrainte conditionnelle de remplacement, le défaut `pipeline_kind`
préserve l'existant, et le digest d'attribution reste réservé à V2.

## 5. Preuve que `LOT42-V1` n'est pas affaibli

Trois niveaux :

1. **statique** — la branche `resource_pipeline` de la contrainte contient
   toujours `canonical_url IS NOT NULL` **et** `btrim(canonical_url) <> ''` ;
2. **réel** — sur PostgreSQL, une insertion `resource_pipeline` sans URL ou
   avec `"   "` lève une `CheckViolation` ;
3. **structurel** — `test_la_release_scellee_n_a_aucune_branche_permissive`
   vérifie qu'aucun `IS NOT NULL` ne se glisse dans la branche scellée.

## 6. Ce que ce lot ne fait pas

Aucune attestation opérationnelle, aucune publication, aucun Worker A ou B,
aucune ressource créée. La migration n'est **pas** appliquée au staging par
cette PR. `STAGING_EXTERNE` n'est pas qualifié, `GO_LIVE_READY` reste `false`.
Release V2 ni modifiée ni promotable. Aucune écriture en base production,
aucun `current switch`, aucune exposition publique.

## 7. Suite

Après approbation et merge :

1. appliquer la migration sur le staging (`schema_head` attendu : **14**) ;
2. vérifier que le comportement V1 reste intact sur cette base ;
3. reprendre le point d'entrée orienté release, désormais capable d'atteindre
   `NEEDS_REVIEW` ;
4. **puis seulement** l'attestation LOT42 batch opérationnelle.
