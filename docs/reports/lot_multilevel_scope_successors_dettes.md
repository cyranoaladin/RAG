# LOT « successeurs de scope multi-niveaux » — dettes constatées

Échec constaté pendant le lot, **non causé par lui**, antériorité démontrée.

## 1. `services/rag-pedago/tests/test_production_release_scope_placement.py::test_current_head_has_no_drift_in_any_producer_input_blob`

```
AssertionError: assert _sha256(ROOT / relative) == expected_sha256
  - 60797507f3f7e36e3bd041739d891968d649a0623774895145cf296b5d9dc005
  + 00052b38aec55eb72ae3bf1a13f914c1f7e08fd24e5257f53564f54c20e3ae64
```

**Cause.** Ce test est un détecteur de dérive : il vérifie que les blobs
d'entrée du producteur de placement de scope production du **2026-08-25**
(`docs/reports/release_scope_placement_provenance_20260825.json`) sont encore
identiques à HEAD. Onze de ces blobs ont changé — les dix manifestes de subject
de la release multi-niveaux et `release-registry.json` — parce que **la release
multi-niveaux a été régénérée** (nouveau préflight `…V2`, 353 chunks, release
`6ec1a4f8…`). La provenance figée du 2026-08-25 désigne encore les manifestes
du 2026-08-13.

Blobs dérivés, mesurés :

```
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/premiere/francais.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/premiere/maths_specialite.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/premiere/nsi_specialite.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/quatrieme/francais.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/quatrieme/maths.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/seconde/francais.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/seconde/maths.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/terminale/maths_specialite.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/terminale/nsi_specialite.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/terminale/physique_chimie_specialite.release.json
services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json
```

**Antériorité démontrée.** L'assertion ne lit que deux choses : le fichier de
provenance du 2026-08-25 (non modifié par ce lot) et les fichiers de release
ci-dessus (non modifiés par ce lot). Le diff de ce lot ne touche **aucun** de
ces onze chemins — il porte sur `packages/contracts/**`, sur des tests
`services/rag-engine/tests/**` et sur `docs/**`. L'échec est donc entièrement
imputable à la régénération de la release, antérieure à ce lot dans l'arbre de
travail.

**Escalade — pas d'initiative prise.** Le fichier de test porte déjà une
exemption ligne à ligne pour `release-registry.json` (« promu pour servir la
release des onze collections »). Étendre cette exemption aux dix manifestes de
subject reviendrait à desserrer un garde-fou de gouvernance : ce n'est ni le
périmètre de ce lot, ni une décision d'agent. La remise au vert appartient au
propriétaire de la release production du 2026-08-25, qui doit choisir entre
(a) ré-attester la provenance du producteur contre le HEAD courant, ou
(b) inscrire explicitement les manifestes multi-niveaux régénérés comme entrées
légitimement remplacées. Conformément à AGENTS.md § Escalade, le lot s'arrête
ici et le signale.

**Portée.** 1 test rouge sur 3 123 dans `services/rag-pedago`
(`1 failed, 3122 passed, 4 skipped`). Aucun test vert n'est passé au rouge par
ce lot : `packages/contracts` (683 verts) et `services/rag-engine`
(3 384 verts, 7 ignorés) sont intégralement au vert, contre huit échecs
constatés au départ du lot.

---

## Résolution — 2026-09-06

La dette est fermée, sans desserrer quoi que ce soit.

Mesuré : **dix des onze** blobs attestés par la provenance du 2026-08-25 sont
encore présents, **à l'octet près**, sous
`multilevel-superseded-20260813/` — l'archive posée par la régénération. Ils
n'ont pas dérivé : ils ont été **supersédés**, et leurs octets survivent.

Le détecteur ne demande donc plus que rien ne bouge — l'exiger figerait le
dépôt, alors qu'une release se régénère. Il demande que les octets qu'une
attestation datée désigne existent encore à un chemin archivé nommé. C'est
**strictement plus fort** que l'exemption par nom envisagée : une entrée
régénérée dont l'original aurait disparu, ou aurait été retouché dans
l'archive, échoue. Un contrôle positif exige par ailleurs exactement dix
supersédés, tous sous `/multilevel/` : un détecteur devenu permissif ne
passerait pas inaperçu.

L'exemption préexistante de `release-registry.json` est laissée telle quelle :
elle précède ce lot, et l'élargir n'était pas nécessaire.

La lignée régénérée reçoit par ailleurs sa propre attestation —
`docs/reports/multilevel_producer_provenance_20260906.json` — plutôt qu'une
extension de l'ancienne, qui reste octet-identique (empreinte gelée par un
test).
