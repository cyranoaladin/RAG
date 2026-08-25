# ADR-0045 — Scopes de retrieval liés à la release de profils production

- **Statut** : Proposé — HUMAN GATE requis sur la PR profils production
- **Date** : 2026-08-25
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0038, ADR-0041, ADR-0044

## Contexte

La release finale issue du gate de profils couvre 26 contenus dans 18
collections. Les scopes V2 existants demeurent liés aux manifests historiques :
leur `source_sha256` ne peut pas être réécrit pour désigner les nouveaux
subjects sans invalider leur identité canonique et les enveloppes déjà émises.

Le runtime doit toutefois prouver qu'un scope de retrieval exact est lié à
chaque subject du registre de release actif. Réutiliser un ancien scope dont le
digest source diffère ferait échouer le démarrage ; choisir implicitement entre
plusieurs scopes d'une même collection créerait une ambiguïté d'autorité.

## Décision

Publier dans `nexus-contracts` 0.14.0 dix-huit nouveaux
`RetrievalScopeArtifactV2`, un par collection de la release
`production-profile-gate-2026-2027-v1`.

Chaque artefact lie exactement :

- le SHA-256 du subject de release courant ;
- le tenant, niveau, voie, matière et statut du profil production ;
- `candidat=libre`, `audiences=[libre,tous]`, `visibility=internal` ;
- l'année scolaire et la version de programme sourcée ;
- la collection production exacte.

Les treize scopes historiques restent packagés et adressables sous leurs IDs
existants. Aucun digest historique n'est modifié.

Au démarrage, le moteur sélectionne un scope par le couple exact
`(collection, subject_sha256)`. Zéro correspondance ou plusieurs
correspondances sont des refus. L'ordre du registre ne peut donc jamais servir
de mécanisme de sélection.

## Conséquences

- le registre partagé contient 31 scopes, dont 30 V2 ;
- les clients peuvent continuer à valider les anciennes enveloppes ;
- la release production dispose d'une couverture retrieval exacte 18/18 ;
- toute nouvelle version de subject exige un nouvel ID de scope et un nouveau
  digest, jamais une mutation silencieuse d'un scope existant ;
- cette ADR ne constitue ni une autorisation de contenu, ni une ingestion, ni
  un cutover production.
