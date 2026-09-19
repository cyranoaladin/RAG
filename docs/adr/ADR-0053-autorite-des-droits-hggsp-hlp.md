# ADR-0053 — Autorité des droits pour HGGSP et HLP terminale, et registre de politique de scope

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-19
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0038, **ADR-0045**, ADR-0048, **ADR-0052**

> Cette ADR **n'accorde aucun droit** aux collections qu'elle nomme. Elle
> constate qu'il n'en existe aucune source gouvernée, et elle les déclare
> bloquantes jusqu'à décision humaine sourcée.

## Contexte — pourquoi

La release `production-profile-gate-2026-2027-v2` couvre onze collections. Le
registre fermé de `nexus_contracts` packagé aujourd'hui contient dix-huit
scopes `prod_*_v1`, gouvernés sous ADR-0045. Le croisement des deux ensembles
donne :

- **8** collections de la release V2 disposent d'un scope `prod_*_v1` packagé,
  donc d'une politique d'autorisation gouvernée et reconductible ;
- **3** n'en ont aucun :
  - `rag_nexus_hggsp_premiere_specialite`
  - `rag_nexus_hggsp_terminale_specialite`
  - `rag_nexus_hlp_terminale_specialite`

Ces trois-là ne sont pas un simple oubli de packaging. Les pièces de la
campagne de vérification des profils production du 2026-08-25 sont explicites :

| Source | HGGSP | HLP terminale |
|---|---|---|
| `docs/reports/verified_production_profiles_20260825.json` | absent | absent (seul `rag_nexus_hlp_premiere_specialite` y figure) |
| `docs/reports/proposed_production_profile_matrix_20260823.json` | absent | absent |
| ADR-0045 | non couvert | non couvert |

Aucune autorité par collection n'existe par ailleurs :
`services/rag-pedago/configs/rights_evidence_registry.yml` et
`corpus_zone_routing.yml` ne mentionnent ni HGGSP ni HLP et ne déclarent aucune
`visibility`.

Un lot antérieur avait produit trois artefacts `prod_hggsp_premiere_specialite_v1`,
`prod_hggsp_terminale_specialite_v1` et `prod_hlp_terminale_specialite_v1` en
recopiant `audiences`, `visibility` et `rights` depuis des collections
voisines, puis en les insérant dans le registre fermé afin que l'émetteur les
accepte comme « politiques déjà gouvernées ». C'est une auto-autorisation :
la reconduction prouve alors une politique que rien n'a jamais décidée. Ce
travail a été retiré et n'est pas repris.

## Décision — quoi

### 1. Les trois collections restent bloquantes

`rag_nexus_hggsp_premiere_specialite`, `rag_nexus_hggsp_terminale_specialite`
et `rag_nexus_hlp_terminale_specialite` sont déclarées
`BLOCKED_PENDING_HUMAN_DECISION`. En conséquence :

- aucun scope de retrieval ne peut être émis pour elles ;
- aucune valeur d'`audiences`, de `rights` ou de `policy_visibility` ne leur est
  attribuée, ni par défaut, ni par analogie, ni par héritage de niveau, de
  matière ou de tenant ;
- la couverture de la release V2 reste **8/11**, et
  `validate_release_startup_configuration` continue légitimement de refuser un
  démarrage qui exigerait les onze.

Le staging ne démarrera donc pas tant que ces trois décisions n'auront pas été
prises. **C'est le résultat voulu** : un démarrage obtenu en dotant trois
collections de droits non décidés vaudrait moins qu'un refus.

### 2. Un registre de politique gouverné, pour les onze

`docs/governance/retrieval_scope_policy_registry.yml`
(`NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1`) couvre les **onze** collections de
la release V2, pas seulement les trois manquantes.

Le registre **ne crée aucun droit** : pour les 8 collections gouvernées, chaque
valeur de politique est citée de sa source (`policy_source_scope_id` +
`policy_source_sha256`, sous `authority_source: ADR-0045`), et un test refuse
toute valeur qui divergerait de cette source. Pour les 3 bloquantes, les champs
de politique sont `null` — le registre ne peut pas les remplir.

Chaque entrée déclare : `collection`, `tenant`, `niveau`, `voie`, `matiere`,
`statut_enseignement`, `candidat`, `audiences`, `rights`, `policy_visibility`,
`evidence_visibility`, `corpus_provenance_id`, `programme_version` et le digest
de sa taxonomie, `subject_manifest_sha256`, `authority_source`, `justification`
et `human_decision_status`.

### 3. Ce qu'une décision humaine devra fournir pour débloquer

Pour chacune des trois collections, séparément et nommément :

1. l'**audience** servie et les `rights` applicables, avec la pièce qui les
   établit (décision Nexus datée, ou document source et son sha256) ;
2. la `policy_visibility` retenue, compatible avec l'ordre de restriction
   d'ADR-0052 §3 ;
3. la confirmation que le matériau est admissible au service — la collection
   n'ayant pas été soumise à la campagne de vérification du 2026-08-25 ;
4. l'`human_decision_status` passant à `APPROVED`, porté par une ADR ou une
   décision référencée sur une ligne ajoutée.

Tant que ces quatre éléments manquent, l'entrée reste `null` et bloquante.

### 4. Interdictions permanentes

- pas de fabrication de politique par analogie avec une collection voisine ;
- pas d'insertion directe d'un artefact de politique dans `scope.py` pour le
  faire reconnaître ensuite comme « déjà gouverné » ;
- pas de valeur par défaut, même restrictive, pour une collection sans décision ;
- pas de déblocage par retrait de la collection du périmètre de contrôle.

## Conséquences

- la trajectoire go-live est explicitement bloquée sur trois décisions
  humaines, nommées, au lieu de l'être sur un symptôme de démarrage ;
- la PR technique qui suivra devra refuser toute collection V2 sans autorité, et
  ne pourra donc pas émettre onze scopes tant que le blocage tient ;
- les 8 collections gouvernées sont prêtes à être émises strictement sous
  ADR-0052, sans affaiblissement de garde ;
- aucun scope n'est émis, aucun runtime modifié, aucune release touchée,
  aucun compteur de readiness déplacé par cette ADR.

## Ce que cette ADR n'autorise pas

Elle n'accorde aucun droit, n'approuve aucune audience, ne promeut aucun
contenu, ne rend la release V2 ni promue ni promouvable, n'autorise aucun
démarrage de staging, aucun `current switch`, aucune écriture en base
production.
