# Lot — Protocole LOT42 de revue de publication pour release scellée

- **Lot** : `LOT_GO_LIVE_FINAL_CI_LOT42_RELEASE_BATCH_PUBLICATION_REVIEW_ADR`
- **Branche** : `go-live/lot42-release-batch-publication-review-adr`
- **Base** : `d21610c9` (`main`, après merge de #233 / lot CH5)
- **Date** : 2026-09-20

> **L'approbation de cette PR par abenrhouma vaut validation du protocole LOT42
> de revue de publication batch pour release scellée, permettant qu'une
> attestation humaine unique couvre l'ensemble immuable
> `production-profile-gate-2026-2027-v2`, dans le périmètre 11 subjects / 315
> artefacts / 479 placements / 8268 chunks. Cette PR ne publie rien et ne
> qualifie pas `STAGING_EXTERNE`.**

Aucune attestation produite. Aucune écriture en base, staging ou production.

---

## 1. Le problème, mesuré

Worker B refuse de publier sans attestation LOT42. Le protocole `LOT42-V1` lie
une revue humaine à **une** ressource, avec un `canonical_url` obligatoire.

Appliqué à la release V2 scellée, cela impose deux choses impossibles à honorer
sans fabriquer :

| Grandeur | Valeur |
|---|---|
| Revues humaines exigées | **315** |
| Pages `source_url` distinctes pour 315 artefacts | **19** |
| `canonical_url` documentaire par artefact | **inexistante** |

Et ce pour un corpus dont chaque placement déclare **déjà**
`review_status=reviewed`, `placement_status=active`, `currentness=current`.

## 2. La décision

`LOT42-V1` **ne bouge pas**. Deux épreuves l'attestent : `canonical_url`,
`resource_id` et `artifact_id` restent obligatoires et unitaires.

Un protocole distinct est ajouté, `LOT42-RELEASE-BATCH-V1`, fondé sur un
principe explicite : *une revue humaine unique ne vaut pour un ensemble que si
cet ensemble est déterminé par une release immuable et des digests vérifiés.*

L'artefact lie la décision à quatre digests — release, artefacts, inventaire de
candidats, manifeste de transfert —, aux quatre comptes, aux onze collections,
à l'état uniforme des placements, et aux autorisations LOT41A déjà
enregistrées.

### `canonical_url` : le protocole dit ce qui n'existe pas

Le nouveau protocole **ne porte aucun `canonical_url`**. Le lien aux artefacts
passe exclusivement par digests. La provenance est conservée pour ce qu'elle
est : `source_url` reste dans `candidate_inventory.json`, et l'artefact en
déclare seulement le nombre, avec une note qui énonce qu'aucune URL canonique
documentaire n'existe par artefact dans cette release.

Un champ `canonical_url` ajouté à la main est **refusé** par le modèle strict.

## 3. Le validateur est pur

`require_release_batch_review_matches_release` ne lit aucun fichier : l'appelant
mesure la release et lui passe ce qu'il a observé. Une fonction qui irait
chercher la release elle-même pourrait en choisir une plus complaisante que
celle qu'on lui nomme. Deux épreuves vérifient cette pureté en inspectant le
corps de la fonction.

## 4. Épreuves — 47, toutes exécutées

| # | Exigence | Épreuve |
|---|---|---|
| 1, 2 | `LOT42-V1` inchangé, `canonical_url` toujours exigé | `test_lot42_v1_exige_toujours_canonical_url`, `test_lot42_v1_reste_unitaire` |
| 3, 4 | release non scellée / digest divergent refusés | `test_un_release_id_divergent_est_refuse`, `test_un_digest_divergent_est_refuse` (4 digests) |
| 5, 6, 7, 10 | artefact ou placement manquant / en surplus, comptes divergents | `test_un_compte_divergent_est_refuse`, `test_un_compte_en_surplus_est_refuse` (4 comptes chacun) |
| 8, 9 | collection manquante / en surplus | `test_une_collection_manquante_est_refusee`, `test_une_collection_en_surplus_est_refusee` |
| 11 | HGGSP ×2 et HLP terminale ne peuvent être omises | `test_une_revue_sans_hggsp_ou_hlp_ne_couvre_pas_la_release` (3 cas) |
| 12, 13, 14 | `review_status`, `currentness`, `placement_status` | `test_un_etat_de_placement_non_conforme_est_refuse` (3 cas), `test_un_etat_de_placement_heterogene_est_refuse` |
| 15 | provenance absente refusée | `test_une_provenance_absente_est_refusee`, `test_une_note_de_provenance_vide_est_refusee` |
| 16, 17 | pas de `canonical_url`, et impossible d'en fabriquer un | `test_le_protocole_batch_ne_porte_aucun_canonical_url`, `test_un_canonical_url_fabrique_est_refuse` |
| 21, 22 | aucune écriture possible depuis ce module | `test_le_validateur_est_pur_et_ne_lit_aucun_fichier`, `test_aucune_ecriture_de_base_n_est_possible_depuis_ce_module` |

S'y ajoutent : canonicité octet à octet (2 altérations), collections non triées
ou dupliquées refusées, nombre de collections ≠ `expected_counts.subjects`
refusé, fenêtre de validité inversée refusée, revue sans autorisation LOT41A
refusée, et une contre-épreuve qui relit les quatre comptes **dans la release
scellée** pour prouver qu'ils ne sont pas inventés ici.

### Les exigences 18 à 20 et 23 à 24

La chaîne humaine (`evaluate_trusted_review`) et la contrainte d'ordre —
approbation sur le head exact, enregistrement **pendant que la PR est ouverte**
— sont déjà couvertes par les 18 épreuves du lot CH5
(`test_lot41a_registration_requires_a_live_review.py`), qui valent
identiquement ici. Les rejouer n'ajouterait rien.

Les exigences 23 et 24 (aucun `current switch`, aucun déploiement production)
sont des faits d'exécution : cette PR ne touche ni infrastructure ni base.

## 5. Qualité

`packages/contracts` : **839 tests verts** (792 avant, +47). `ruff` propre.
Verrous de gouvernance 18/18. `export_schemas --check` vert.
`nexus-contracts` passe en **0.19.0** — évolution additive, aucun contrat
existant modifié ni retiré.

## 6. Ce que cette PR n'autorise pas

Aucune attestation enregistrée, aucune publication, aucune ingestion, aucune
écriture en base staging ou production. `STAGING_EXTERNE` n'est pas qualifié,
`GO_LIVE_READY` reste `false`. La release V2 n'est ni modifiée ni rendue
promotable. Aucun `current switch`, aucune exposition publique.

## 7. Suite

Après approbation et merge, la PR **opérationnelle** produira l'artefact de
revue batch effectif — avec les digests réels d'`artifacts.release.json` et de
`candidate_inventory.json` —, le fera approuver, puis enregistrera
l'attestation **pendant que la PR est ouverte**, et ne sera fusionnée
qu'ensuite. Ce n'est qu'après cela que le point d'entrée d'ingestion orienté
release pourra être construit et exécuté.
