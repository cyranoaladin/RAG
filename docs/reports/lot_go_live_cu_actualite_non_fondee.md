# Le candidat `profile_gate_v2` n'est pas chargeable par sa propre chaîne d'autorités

> Mesuré le 2026-09-22 sur la branche
> `go-live/cu-batch-projection-and-pii-reconciliation`.
> Toutes les mesures ci-dessous sont reproductibles par les commandes
> données en fin de document. Aucune n'exige de réseau ni de base.

## Résumé

La régénération gouvernée demandée au §3 du mandat a été préparée et
testée. **L'inventaire se régénère et est accepté** par le chargeur
canonique. **L'actualité ne peut pas suivre**, et pas pour une raison
technique : elle affirme, pour 315 contenus, un téléchargement officiel
byte-à-byte que rien dans le dépôt ne fonde.

Ce n'est donc pas un remplacement de trois nombres qui manque. C'est une
décision d'autorité qui n'est pas la mienne.

## Ce que le chargeur canonique refuse, aujourd'hui, sur le candidat livré

```
INVENTAIRE REFUSÉ : inventory unique_artifacts count differs
```

Le fichier `profile_gate/candidate_inventory.json` du candidat déclare :

| Compteur déclaré | Valeur | Valeur réelle du fichier |
|---|---|---|
| `placements` | 486 | 486 |
| `unique_artifacts` | 486 | **319** |
| `multi_placement_artifacts` | 0 | **167** |
| `physical_objects` | 486 | *(non mesuré : le chargeur refuse avant)* |

Il confond placements et artefacts uniques. Ce défaut n'est pas propre au
périmètre réduit : il est présent tel quel dans la répétition à 319/486
dont le candidat hérite, et le successeur produit par
`build_production_profile_release.py` le recopie à l'identique — le chemin
successeur copie treize fichiers de preuve verbatim.

La régénération dérivée corrige ce point :

| | Placements | Contenus | Multi-placements | Chargeur |
|---|---|---|---|---|
| Candidat livré | 486 | 319 | 0 déclaré | **refusé** |
| Successeur du constructeur | 486 | 319 | 0 déclaré | **refusé** |
| Régénération dérivée | 479 | 315 | 164 | **accepté** |

## Le blocage réel : une actualité que rien ne fonde

L'inventaire régénéré accepté, l'actualité est refusée à son tour :

```
ACTUALITÉ REFUSÉE : CURRENT official URL is invalid
```

Le contrat est sans ambiguïté (`multilevel_evidence.py`) : une décision
`CURRENT` exige `current_download_url` **et**
`current_source_listing_url`, toutes deux sur un hôte officiel
(`eduscol.education.gouv.fr`, `www.education.gouv.fr`). Le résolveur
(`multilevel_verified_placement.py:537`) refuse par ailleurs tout contenu
dont la décision n'est pas `CURRENT`, et relit l'URL de téléchargement
(`:554`). Il n'existe pas de troisième voie : `MULTILEVEL_ARTIFACT_CURRENTNESS_V2`
n'assouplit pas cette règle, il la durcit (audit réseau lié au corpus et à
l'ensemble exact de contenus).

Or l'actualité livrée :

- porte **486 entrées** pour **319 contenus distincts** — des doublons, que
  le chargeur refuse avant même d'examiner les URL
  (`currentness content is duplicated`) ;
- déclare `decision: CURRENT` pour **toutes** ;
- ne nomme une URL de téléchargement que sur **17 lignes**, correspondant à
  **13 contenus distincts** ;
- annonce dans ses `counts` **26** artefacts, pour une liste qui en porte 486.

Et `decision_basis` affirme :
`"Official Eduscol URL downloaded read-only and byte-matched"`.

## Ce que le dépôt sait vraiment des URL officielles

`services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/url_source_registry.json`
est le registre de résolution d'URL du corpus. Il est catégorique :

| Compteur | Valeur |
|---|---|
| `URL_DISCOVERED` | 123 |
| `URL_DIRECT_RESOLVED` | **12** |
| `URL_DIRECT_UNRESOLVED` | **111** |
| `URL_UNRECOVERABLE` | **110** |
| Statuts HTTP observés | 13 × `200`, **110 × `403`** |

Et son autorité-source le dit en toutes lettres :

> « 2956 affectations, 111 URL de navigation distinctes, **aucune URL de
> document direct**. »

Croisé au périmètre du candidat :

| | Contenus |
|---|---|
| Périmètre du candidat | 315 |
| Disposant d'une URL directe résolue sur hôte autorisé | **5** |
| Sans URL directe | **310** |
| Affirmés avec URL par l'actualité livrée | 13 |
| …dont réellement adossés au registre résolu | **4** |

## Conséquence, énoncée sans adoucissement

Une actualité honnête, régénérée sur le périmètre réel, classerait environ
**310 des 315 contenus en `REVIEW_REQUIRED`** — seul état disponible quand
aucune URL officielle ne fonde la décision. Le résolveur refusant tout
contenu non `CURRENT`, la release publiable tomberait à une poignée de
contenus.

Il n'y a pas de dérivation qui évite cela. Produire les URL manquantes
serait fabriquer la preuve que le contrat exige ; assouplir le chargeur
serait rétrograder le contrat pour l'accorder à des données incohérentes.
Le mandat interdit l'un et l'autre, et il a raison.

## Ce que le banc a réellement prouvé, et ce qu'il n'a pas prouvé

Le banc d'acceptation (15/15, Worker B, publication puis retrieval sur
PostgreSQL isolé) construit **sa propre release**, par
`_banc_multiniveaux.construire_contexte_du_banc`. Il prouve que la chaîne
— autorités, publication gouvernée, index produit, retrieval — fonctionne
de bout en bout.

Il ne prouve rien sur le corpus réel : **aucun test, nulle part, ne charge
`candidate_inventory.json` ni `currentness_evidence.json` du candidat
`profile_gate_v2` par `load_multilevel_runtime_authorities`.** Ce qui est
lu de cette release, dans la suite, c'est son manifeste et son registre de
programmes. Les granularités « 315 contenus / 479 placements » sont des
valeurs **déclarées** par la release, jamais des valeurs qu'une
publication réelle aurait traversées.

## Décision attendue, qui n'est pas la mienne

Le fondement de l'actualité pour un corpus acquis par Drive est une
question de gouvernance, pas d'implémentation. Trois voies, à trancher :

1. **Mesure réseau autorisée** contre Eduscol, pour résoudre les URL
   directes. Le registre enregistre 110 × HTTP 403 : cette voie est
   probablement sans issue en l'état, et elle exige une autorisation.
2. **Nouveau fondement d'actualité** pour un corpus Drive — un ADR qui
   définit ce qui atteste l'actualité quand l'URL directe n'existe pas, et
   le contrat correspondant. C'est un changement de contrat versionné.
3. **Livraison explicitement partielle**, limitée aux contenus réellement
   adossés à une URL officielle résolue. Sur les mesures ci-dessus, cela
   représente **5 contenus sur 315** — à présenter comme tel, jamais comme
   l'achèvement des 315.

Aucune n'est engagée ici.

## Reproduction

```bash
cd /home/alaeddine/Bureau/RAG/services/rag-engine
PYTHONPATH=src:../../packages/contracts/src .venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
from ingestor.multilevel_evidence import (
    load_multilevel_candidate_inventory, load_multilevel_currentness,
)
G = Path("../rag-pedago/data/releases/prerentree_2026_2027"
         "/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate")
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
inv_p = G / "candidate_inventory.json"
print("counts déclarés :", json.loads(inv_p.read_text())["counts"])
try:
    load_multilevel_candidate_inventory(inv_p, expected_sha256=sha(inv_p))
except Exception as exc:
    print("INVENTAIRE REFUSÉ :", exc)
cur = json.loads((G / "currentness_evidence.json").read_text())
print("actualité : %d entrées, %d contenus distincts, %d avec URL, counts=%s" % (
    len(cur["artifacts"]),
    len({a["content_sha256"] for a in cur["artifacts"]}),
    sum(1 for a in cur["artifacts"] if a.get("current_download_url")),
    cur["counts"],
))
reg = json.loads(Path("../rag-pedago/data/releases/prerentree_2026_2027"
                      "/multilevel/url_source_registry.json").read_text())
print("registre d'URL :", reg["compteurs"])
PY
```

## Les quatre contenus exclus ne sont pas un cas particulier

Le mandat demandait de résoudre la contradiction entre « l'actualité
positive de quatre contenus » et le registre qui les exclut comme
archives. Mesuré :

| Contenu (abrégé) | Registre d'exclusion | Actualité livrée |
|---|---|---|
| `157309db13b6` | `ARCHIVE_DECLARED` — `BLOCKED_NOT_CURRENT_BY_SOURCE` | `CURRENT` |
| `174f273ff258` | `ARCHIVE_DECLARED` — `BLOCKED_NOT_CURRENT_BY_SOURCE` | `CURRENT` |
| `ccffe628bbd6` | `ARCHIVE_DECLARED` — `BLOCKED_NOT_CURRENT_BY_SOURCE` | `CURRENT` |
| `dc58fcc42ef9` | `ARCHIVE_DECLARED` — `BLOCKED_NOT_CURRENT_BY_SOURCE` | `CURRENT` |

La contradiction se dissout d'elle-même : l'actualité déclare `CURRENT`
**ses 486 lignes**, sans distinction. Ces quatre contenus ne sont donc pas
quatre exceptions à expliquer, mais **quatre instances de plus du même
défaut**. Le registre, lui, nomme une raison — l'archive déclarée par la
source, sous ADR-0055 — et c'est la seule des deux autorités qui ait
réellement regardé.

Leur exclusion est donc conservée, conformément au mandat : aucun ancien
fichier déclarant `CURRENT` ne la remplace.

## Le registre d'exclusion s'adosse à un jeu de décisions non signé

`release_currentness_exclusion_registry.json` déclare ses autorités, dont :

```
authorities.pii_decisions.path  = governance/pii-review-decisions/pii-review-2026-09-17-final.json
authorities.pii_decisions.sha256 = 0805c9babfc16def…   (conforme au fichier)
```

L'empreinte est exacte. Mais `governance/pii-review-bindings/` ne contient
qu'un seul reçu, et c'est celui du **2026-09-03**. Le jeu du 17/09, qui
porte 149 décisions et que le registre nomme comme autorité, **n'a pas de
reçu ADR-0035** : rien n'atteste hors ligne qu'un relecteur habilité l'ait
approuvé.

Ce n'est pas un blocage pour la reconduction PII, qui s'appuie sur le jeu
du 03/09 — signé, non révoqué, et couvrant les 22 contenus signalés. Mais
c'est une autorité déclarée sans preuve dans un artefact de release, et
elle doit être soit signée, soit remplacée par celle qui l'est.
