# LOT 1.2 — le producteur de la lignée du 29 août existe, hors de `main`

> Recherche ordonnée : quel outil lit `catalog_delta.json` et écrit les manifests de sujet ?
> La question était mal posée — `catalog_delta.json` n'est pas une entrée, c'est une sortie.

## Ce que le producteur est

`services/rag-pedago/scripts/build_production_profile_release.py`, **dans sa version de la
branche `rag-pedago/release-chain-ingestion-319`** — qui diffère de celle de `main` de
**885 insertions et 82 suppressions**.

Il **produit** `catalog_delta.json`, `candidate_inventory.json`, les manifests de sujet,
l'agrégat et le registre. Ces fichiers ne sont pas ses entrées.

## Ses entrées réelles, et pourquoi personne ne les voyait

La version de la branche 319 rend trois chemins **surchargeables par l'environnement** —
la version de `main` ne le fait pas :

```python
FINAL_MATRIX_PATH    = Path(os.environ.get("NEXUS_FINAL_MATRIX", …20260825.json))
PROFILE_ROOT         = Path(os.environ.get("NEXUS_PROFILE_ROOT", …/ingestion_profiles))
PROFILE_MANIFEST_PATH= Path(os.environ.get("NEXUS_PROFILE_MANIFEST", …/ingestion_manifest.yml))
```

**La lignée du 29 août a été produite en surchargeant les trois.** Cela explique du même
coup pourquoi le sceau lie `ingestion_manifest_v2_livraison_319.yml` : c'est la valeur
passée à `NEXUS_PROFILE_MANIFEST`, et c'est l'autorité qu'il a fallu importer sur `main`
pour que l'outil de rescellement cesse de refuser.

## La matrice réellement passée

Recherche par un contenu témoin — présent en base, absent de la matrice du 25 août :

```
00be5591656578cf94095266d34c778d14dd31c596e7045bafd1b3655babf475
```

```
docs/reports/evidence-index/matrice_preuve_v2_20260829.json
   121 entrées · 121 collections · 5 265 couples · 2 389 contenus

présente sur : forensic/image-20260830-0903 · lot/cockpit-cutover-20260829
               lot/release-reseal-scopes-v2-20260828 · rag-pedago/release-chain-ingestion-319
               rescue/f7f4345 · backup/forensic/image-20260830-0903
ABSENTE de main · absente du disque · absente des sauvegardes · absente de l'image
```

## La chaîne complète de la lignée du 29 août

```
matrice_preuve_v2_20260829.json        2 389 contenus · 121 collections   HORS DE main
   + profils v2_livraison_319 (11)                                        entrés au LOT 1c
   + ingestion_manifest_v2_livraison_319.yml                              entré au LOT 1c
        ↓  build_production_profile_release.py, VERSION DE LA BRANCHE 319
           avec NEXUS_FINAL_MATRIX, NEXUS_PROFILE_ROOT, NEXUS_PROFILE_MANIFEST
        ↓
   catalog_delta.json (486) · candidate_inventory.json (11) · 11 manifests · agrégat · registre
        ↓
   rag_artifact_placements (486, identité parfaite) · rag_chunks (8 324)
```

## Ce que cela résout et ce que cela ouvre

**Résolu :** le producteur existe, ses entrées sont nommées, et la deuxième des trois issues
posées s'applique — il existe mais hors de `main`, donc il entre par cherry-pick avec sa
provenance.

**Ouvert :** trois artefacts de cette lignée sont absents de `main` — le producteur dans sa
version 319, la matrice de preuve, et les profils déjà importés au LOT 1c. **`main` ne peut
pas reproduire sa propre production.** C'est le constat 01 au niveau de la chaîne de
release : non seulement on ne sait pas quel commit produit ce qui répond, mais le commit
publié ne contient pas de quoi produire ce qui existe.

**Et un défaut de conception à inscrire :** un producteur dont les entrées sont
surchargeables par l'environnement, sans que la valeur employée soit enregistrée dans sa
sortie, rend sa propre sortie non reproductible. Rien dans `catalog_delta.json` ne dit
quelle matrice l'a produit. C'est la même famille que le fantôme `330c3362` — une sortie
fonction de l'ambiance, pas des entrées déclarées.
