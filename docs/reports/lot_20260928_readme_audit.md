# Lot documentaire — état du projet et README auditable

## Périmètre

Base examinée : `main` au commit
`5203c737aa41dd2994504e671819b7a1f024d5f1` (fusion de #267).
Ce lot met à jour le README racine ; il ne change ni code, ni release,
ni autorisation, ni données. Il ne touche pas à #262 et n'effectue aucune
opération SSH, base ou Worker B.

## Sources et frontière de preuve

- Les manifests V4 et HGGSP, le registre mixte v2, les deux mappings de
  sujets, l'autorisation HGGSP proposée, le runbook HGGSP, les rapports DI et
  les preuves de build ont été relus depuis la base exacte.
- Les SHA des cinq autorités principales ont été recalculés depuis leurs
  octets. Les 405 placements/263 artefacts servis par V4 et les 74
  placements/52 artefacts HGGSP ont été recomptés depuis les manifests de
  sujets ; intersections des artefacts et placements : zéro.
- Les PR #266/#267 fusionnées, #262 ouverte au HEAD
  `079461659b60f8a8ce9458145a199599ad822bbc`, ainsi que les deux
  workflows `main` verts, ont été relus sur GitHub le 28 septembre 2026.
- Les journaux opérateur locaux DI ont été relus et identifiés par leurs
  SHA-256 dans le README. Ils ne sont pas versionnés : l'état du staging est
  rapporté comme preuve externe, sans prétendre à une nouvelle mesure de la
  base depuis ce lot.

## Résultat documentaire

Le README distingue désormais l'état courant daté des lots historiques.
Il expose l'architecture, les frontières de confiance, les identités et
cardinalités V4/HGGSP, les empreintes, la preuve de provenance DI, l'état de
#262, les qualifications, les blocages et le chemin d'activation restant.
Il corrige les formulations historiques qui donnaient encore le Cockpit
comme futur, la NSI comme en cours et une tolérance d'échec CI inexistante.

## Qualification du lot

- `git diff --check` : succès.
- Liens locaux du README : 53, manquants : 0.
- Ancres internes du README : 28, manquantes : 0.
- `sha256sum` des cinq autorités : conforme aux valeurs documentées.
- Recalcul des manifests : V4 servi 9/263/405 ; HGGSP 2/52/74 ; aucune
  intersection d'artefact ou de placement.
- `bash scripts/check-governance-locks.sh` : 18 clés conformes.
- `bash scripts/check-authority-uniqueness.sh` : PASS.
- `bash scripts/check-repository-hygiene.sh` : PASS.
- Revue indépendante du diff : aucun écart factuel majeur ; deux précisions
  intégrées sur le SHA de base et le miroir PDF hors dépôt.

La CI complète de cette branche sera exécutée par la PR. Les deux workflows
de `main` au SHA de base étaient `success` ; ce résultat ne préjuge pas de la
CI du futur HEAD documentaire.
