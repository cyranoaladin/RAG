# ADR-0061 — Un seul sens pour `programme_version` : les profils de V4 portent le scope servi

- **Statut** : Proposé — décision de principe du propriétaire le 2026-09-24
  (voie S) ; devient Accepté par la review humaine `APPROVED` du HEAD exact de
  la PR qui l'introduit.
- **Date** : 2026-09-24
- **S'appuie sur** : ADR-0045 (scopes de production, `visibility=internal`),
  ADR-0048 (émetteur canonique), ADR-0050 (identité de release), **ADR-0052**
  (dimensions croisées), ADR-0053, ADR-0059, ADR-0060

## Le fait qui force la décision

Dans les releases `production-profile-gate` V1 à V3, le champ
`programme_version` porte deux sens. Les profils `v2_livraison_319`, donc les
placements, les autorisations et les identifiants de placement qui en dérivent,
y mettent `EDUSCOL_CORPUS_20260808`, un identifiant de **corpus de
provenance**. Le registre de programme de la release, les scopes de retrieval
et le filtre du retrieval y mettent la **référence officielle** (`BOEN_…`) de
chaque collection. ADR-0052 l'a constaté et a déplacé la comparaison pour
l'émetteur de scopes seulement.

Conséquence mesurée sur banc (lot CZ) : Worker B refuse chaque placement
(`release programme version differs from canonical programme`) ; et, même sans
ce refus, un contenu publié sous `EDUSCOL_…` serait introuvable, le retrieval
filtrant par égalité stricte sur le programme du scope. La même mesure révèle
une seconde divergence, adjacente : les profils déclarent `visibility=public`,
les scopes servent `internal` (ADR-0045), et le serveur ne retient que la
visibilité du scope — un chunk `public` n'y serait jamais retrouvé.

## Décision

1. **Le scope d'un profil V4 est le scope servi.** Pour chaque collection,
   `scope.programme_version` porte la référence officielle que la taxonomie de
   cette collection établit — celle du registre de programme de la release et
   du scope de retrieval — et `scope.visibility` la visibilité de la politique
   servie. Le programme est vérifié collection par collection (taxonomie,
   niveau, matière), jamais remplacé par une valeur générique.
2. **Les faits de provenance restent nommés, ailleurs.** L'identifiant de
   corpus (`EDUSCOL_CORPUS_20260808`) et l'ouverture du matériau
   (`evidence_visibility`) restent dans le registre de politique de retrieval
   (`corpus_provenance_id`, `evidence_visibility`) et dans le champ
   `provenance` du manifeste de profils V4. Aucun contrat n'est modifié.
3. **Nouvelle lignée, nouvelle release.** Onze profils `profile-gate-v3`
   (`v3_livraison_315`) et leur manifeste ; la release successeur
   `production-profile-gate-2026-2027-v4`. Les profils, releases et
   autorisations historiques ne sont ni modifiés ni réinterprétés : V1 à V3
   restent reproductibles telles qu'elles ont été scellées, et ne sont pas
   servables.
4. **Garde de construction.** Hors de la lignée historique, le producteur
   refuse un profil dont le programme n'est pas la référence officielle du
   registre de programme de la release.
5. **Visibilité : restreindre, jamais élargir.** `internal` est strictement
   plus restrictive que `public` et égale la politique déjà servie : aucun
   droit d'accès effectif ne change.

## Chaîne de concordance démontrée

Registre de programme de V4 → profils V4 → placements scellés de V4 →
autorisations r4 (portée = profil V4) → attestations et jobs → lignes de
l'index produit → scope de retrieval V4 émis par l'émetteur canonique →
filtre du serveur. Aucune valeur n'est substituée dans le publisher ou le
retrieval.

## Ce que V4 garde de V3

Les 315 contenus, leurs 8 268 chunks et leur identité, les 479 couples
collection–contenu, l'inventaire, la preuve PII et le registre de programme
(octet pour octet), les droits, audiences, domaines et exclusions. Le jeu de
décisions PII et son reçu s'appliquent à V4 : les chargeurs canoniques les
vérifient sur ses octets.

## Conséquences

* Onze autorisations r4 (LOT41A-V2), versées par leur propre PR, enregistrées
  pendant qu'elle est ouverte et approuvée.
* Onze scopes de retrieval V4, émis depuis un registre de politique lié à V4,
  avec une version mineure de `nexus-contracts`.
* Si le staging détient des placements acquis sous V2, leur reprise par V4
  change leur `placement_id` et leur programme : elle exige une transformation
  explicite et approuvée (ADR distincte), jamais un relâchement des invariants
  d'adoption. Sinon, V4 s'ingère directement.
* Le rôle `student` ne lit que `public` ; les scopes de production sont
  `internal` depuis ADR-0045. Ouvrir le service aux élèves est une décision
  produit distincte, que cette ADR ne prend pas.
