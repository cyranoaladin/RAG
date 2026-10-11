# Lot — alignement du pin de cible et du transfert sur le successeur public courant

Source : `origin/main=61a6e82ced66190f1dc680090303e67117821468`, le 11 octobre 2026. Ce lot ne transfère aucun fichier et ne modifie ni la base ni les services staging ou production.

## Défaut constaté

L'ancre A courante `student_public_successor_content_anchor_20261011.json` (SHA-256 `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`) lie le manifeste `efc5c425189ec8ec83460aff2d3539401f3dbdba1dcde252187608276f65ec85` à la release `student-public-successor-20261010-40b956c6f5ec0c60`. Les 11 autorisations LOT41A enregistrées dans la cible publique et les 11 scopes V3 émis après la revue #330 portent ce même contenu.

Le pin de #333 et le plan de transfert du 10 octobre désignent encore `student-public-successor-20261010-fcc84331e7700042`. Le contrôle canonique du transfert qualifié exige à la fois `plan.release_id = inventory.release_id` et `plan.release_id = pin.release_id` ; leur association avec A courant serait donc refusée. Le pin de #333 reste inchangé et ne devient pas, par interprétation, un pin de la release 40b.

## Nouveaux artefacts dérivés et bornés

Le producteur `scripts/go_live/public_text_transfer.py --plan --complete-profile-binding` a rejoué l'inventaire et l'allowlist de la release 40b, le CAS privé exact et les 253 dérivés textuels. Le nouveau plan `student_public_successor_v2_transfer_plan_release40b_20261011.json` (SHA-256 `212385841d6966875f8f20567378bbfeb9afa18f308da4faaf763bd0ee8ee19c`) porte `PLANNED_NOT_TRANSFERRED` et énumère 253 fichiers texte, 253 reçus CAS et 377 placements. Son inventaire est `5c349975e2a327f8b855e82dc932ff8d7d7984537ae48cdf131f814858b6a4ac`, son allowlist `13559906d9cd66d8519bf132450d3145692d019bb56b8b25871e53e66000ff56`. Aucun reçu d'observation V1/V2 n'est produit ici.

Sur l'hôte `korrigo`, le producteur canonique `independent_staging_target_pin.py capture` a observé, en lecture seule, le conteneur Docker `5fe53fb652d8876d4e0701f58a7fdb0b145c93ae733d0e80ad2a89adce19131e`, la base dédiée `ragdb_student_public_qual` et le répertoire distinct `/srv/nexus-public-qual-20261011/servable-text`. Le nouveau pin `governance/staging_target_pins/student-public-successor-release40b-20261011.json` (SHA-256 `309144dc6de90dd8f6df9ceb45be754c259467d2055d93beada1bb8fbd45ab69`) lie la release 40b à l'ancre A, à ce conteneur, à la base et à l'identité physique du répertoire. Il expire le **12 octobre 2026 à 18:51:51 UTC**. La fenêtre d'actualité de A, plus courte, expire le **12 octobre 2026 à 13:58:41 UTC** ; aucune étape autorisée par A ne peut continuer après cette limite.

## Frontière de revue et fermeture

La capture du pin est **non approuvée**. Cette PR doit recevoir la review de `abenrhouma` sur son HEAD/base/challenge exacts, avec `trusted-human-review/head-pinned=success`. Avant fusion, `independent_staging_target_pin.py verify` doit relire le blob de ce pin au HEAD revu et la même cible vivante, puis rendre `EXPECTED_TARGET_PIN_SHA256=309144dc6de90dd8f6df9ceb45be754c259467d2055d93beada1bb8fbd45ab69`. Après fusion, `historical_staging_target_pin_receipt.py --write-receipt` doit rejouer le merge, la review, le statut et la cible actuelle. Toute avance de `main` entre la review et le merge peut invalider le parent exact exigé par ce reçu : recontrôler avant fusion.

Le reçu B existant de #330 est indépendant du pin et se revérifie avec 11 scopes. Les 11 autorisations LOT41A enregistrées en DB ne prolongent pas l'expiration de A. Ce lot ne signe pas la readiness `INGESTION` ou `PUBLICATION`, n'ingère aucun dérivé et n'autorise pas l'accès étudiant. Le plan et le pin servent aux étapes suivantes seulement après leur propre revue et leur rejeu live.
