# ADR-0048 — Émetteur canonique des scopes de retrieval, et succession de subject

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-05
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0038, ADR-0041, ADR-0044, **ADR-0045**

> Cette ADR décrit une **procédure de génération**. Elle n'autorise aucun
> scope, n'approuve aucune audience, n'élargit aucun droit et ne promeut aucun
> contenu. La politique d'autorisation reste celle des scopes déjà gouvernés,
> obtenue sous ADR-0038 et ADR-0045 ; cette ADR se borne à décrire comment on
> la reconduit sans la déformer.

## Contexte — pourquoi

La release multi-niveaux `prerentree_2026_2027` a été régénérée sous les
autorités courantes, en une passe non circulaire, à partir d'un producteur de
préflight enfin présent dans le dépôt
(`services/rag-pedago/scripts/build_multilevel_preflight.py`, schéma
`MULTILEVEL_RELEASE_PREFLIGHT_V2`). Les dix manifestes de subject ont donc de
nouvelles empreintes. La release précédente (2026-08-13, sha `d8ee6703…`) est
archivée intacte sous `multilevel-superseded-20260813/`.

Le moteur sélectionne un scope de retrieval par le couple **exact**
`(collection, subject_sha256)` : zéro correspondance est un refus, plusieurs
correspondances aussi (`validate_release_startup_configuration`). La
régénération a donc délié les dix scopes qui désignaient l'ancienne release, et
le démarrage a échoué sur `scope source SHA differs from subject release`.

Cette garde a bien fonctionné : elle a découvert la dette. La dette n'était pas
le refus, c'était l'absence d'émetteur. Les trente `RetrievalScopeArtifactV2`
packagés dans `nexus-contracts` avaient été **écrits à la main**, puis épinglés
au registre fermé par leur digest. Aucun outil in-repo ne pouvait les
reproduire, les contredire, ni dire de quelle politique ils tenaient leurs
douze dimensions d'autorisation. Tant qu'aucune release ne bougeait, cela
tenait ; dès qu'une release bouge, plus personne ne peut prouver comment les
remplaçants ont été fabriqués.

## Décision — quoi

### 1. Un émetteur canonique, versionné, à entrées nommées

`packages/contracts/scripts/build_retrieval_scope_artifacts.py` produit les
artefacts de scope. Toutes ses entrées sont **nommées à l'exécution** et
vérifiées contre le digest qu'on lui annonce ; il ne lit jamais le CWD, ne
porte aucun chemin de poste de travail, n'écrit aucun horodatage. Deux
exécutions des mêmes entrées rendent des octets identiques.

### 2. Deux familles d'entrées, jamais confondues

**Une release dit CE QUI EXISTE ; un scope dit QUI PEUT VOIR QUOI.** L'émetteur
tient les deux séparées :

| Entrée | Ce qu'elle apporte | Ce qu'elle n'apporte jamais |
|---|---|---|
| `--subject-release` | `source_sha256`, le digest du manifeste de subject | aucune dimension d'autorisation |
| `--policy-authority` | le **nom** du scope gouverné dont la politique est reconduite | aucune valeur de politique écrite en propre |

L'autorité de politique
(`packages/contracts/authorities/multilevel-retrieval-scope-policy-v1.yml`)
n'écrit ni `tenant`, ni `niveau`, ni `voie`, ni `matiere`, ni
`statut_enseignement`, ni `candidat`, ni `audiences`, ni `visibility`, ni
`rights`, ni `school_year`, ni `programme_version`, ni `collection` : elle
**désigne** un scope existant, et l'émetteur lit ces douze dimensions chez lui,
dans le registre fermé, digest vérifié.

### 3. Croisement, et refus plutôt qu'élargissement

L'émetteur confronte les dimensions que les placements du subject déclarent aux
dimensions de la politique nommée. Une divergence — collection, niveau, voie,
matière, statut, candidat, visibilité, année scolaire, version de programme,
tenant — est un **refus**. `audiences` et `rights` n'ont aucune contrepartie
dans une release : ils restent l'apanage exclusif de la politique.

Après construction, l'émetteur recalcule `AUTHORIZATION_SEMANTIC_DIFF` entre
l'artefact émis et sa politique source, en excluant `scope_id` et
`source_sha256` — les seuls porteurs légitimes de la nouvelle liaison. Toute
différence résiduelle est un refus.

### 4. Réutilisation avant émission

Pour chaque subject actif, l'émetteur cherche d'abord une correspondance exacte
`(collection, subject_sha256)` parmi les scopes existants :

- exactement une → le scope existant est **réutilisé**, rien n'est émis ;
- zéro → un successeur est émis ;
- plusieurs → **échec** : c'est l'ambiguïté d'autorité que le moteur refuserait
  au démarrage.

`NEW_SCOPE_COUNT` est le résultat de ce calcul, jamais un nombre supposé.

### 5. Invariant — les scopes historiques sont immuables

Aucun artefact existant n'est réécrit, supprimé ni renommé ; aucun
`source_sha256` existant n'est modifié ; aucun digest épinglé au registre ne
change. Conformément à **ADR-0045**, une nouvelle version de subject exige un
**nouvel identifiant de scope ET un nouveau digest**, jamais une mutation
silencieuse. Cette ADR ne contredit ADR-0045 sur aucun point : elle en
automatise l'application.

L'identifiant successeur suit la convention de version déjà gouvernée :
`<stem>_v<N>` → `<stem>_v<N+1>`. L'émetteur refuse tout identifiant hors
convention, et tout identifiant déjà épinglé au registre dont les octets émis
ne reproduiraient pas exactement le digest épinglé.

### 6. Rester en V2

Le runtime et le registre attendent `RetrievalScopeArtifactV2` dans ce
périmètre. Aucune migration vers V3 n'est faite : `V3_ARTIFACTS=0`.

## Sémantique verrouillée — entrée en N, contenu de N−1

Les scopes `entree_*` portent un décalage d'un niveau entre leur cible et leur
collection : `entree_premiere_maths_v2` cible la première et interroge
`rag_nexus_maths_seconde_tc`. **Ce n'est pas un défaut d'affectation, c'est
l'intention métier du diagnostic** : un élève qui entre en N est évalué sur ce
qu'il devait maîtriser en N−1. Un test dédié verrouille ce décalage sur toute
la famille, pour que personne ne le « corrige » par inadvertance.

## Conséquences

- `nexus-contracts` passe de `0.15.0` à `0.16.0` — évolution **additive** :
  une nouvelle population de ressources empaquetées et adressables, aucun
  schéma modifié, aucune rupture. C'est le niveau que le dépôt applique à ce
  cas : ADR-0042 (0.11→0.12), ADR-0044 (0.12→0.13), ADR-0045 (0.13→0.14, pour
  exactement cette opération — dix-huit scopes V2 ajoutés) et ARIA-B
  (0.14→0.15) ;
- le registre fermé passe de 31 à 41 scopes, dont 40 V2 et un pilote V1 ;
- la release multi-niveaux régénérée dispose d'une couverture exacte 10/10 :
  `ZERO_MATCHES=0`, `MULTIPLE_MATCHES=0` ;
- les enveloppes déjà émises sous les identifiants historiques restent
  vérifiables : leurs artefacts et leurs digests n'ont pas bougé ;
- les dix-huit scopes `prod_*` de la porte de profils production
  (ADR-0045) sont hors périmètre et strictement inchangés ;
- la garde runtime `scope source SHA differs from subject release` n'est pas
  desserrée : elle reste la preuve de couverture ;
- cette ADR ne constitue ni une autorisation de contenu, ni une ingestion, ni
  un cutover production.

## Ce que cette ADR ne fait pas

Elle ne déclare approuvée aucune audience, aucun droit, aucune visibilité.
Si une autorisation devait réellement changer — `visibility` élargie, audience
ajoutée, droits étendus, tenant ou collection modifiés —, ce serait une
décision d'autorisation distincte, à instruire séparément. L'émetteur est
construit pour **refuser** un tel changement, pas pour le déduire.
