# ADR-0040 — Extension contractuelle dormante à la Quatrième

- **Statut** : Acceptée pour le staging gouverné ; activation interdite dans cette décision
- **Date** : 2026-08-12
- **Décideur** : Nexus Réussite
- **S'appuie sur** : ADR-0002, ADR-0013, ADR-0015, ADR-0038, ADR-0039

## Contexte

L'extension multi-niveaux prioritaire doit pouvoir représenter des preuves
pédagogiques exactes de Quatrième pour les mathématiques et le français. Le
contrat canonique s'arrêtait à `troisieme` et le catalogue ne déclarait aucune
collection grade-specific de Quatrième. Utiliser `cycle4` ou `4e` comme repli
aurait supprimé l'identité de niveau exacte et affaibli les gates de placement.

Pour l'année scolaire 2026-2027, l'autorité de programme fournie pour cette
extension est exactement `BOEN_special_11_2018-07-26_aj_2020`.

## Décision

Ajouter `Niveau.quatrieme = "quatrieme"` à `nexus-contracts` et publier cette
évolution additive sous la version `0.11.0`. Le namespace documentaire des
JSON Schemas reste `v0.5`, conformément à ADR-0026.

Déclarer exactement deux collections nouvelles :

- `rag_nexus_maths_quatrieme_tc` ;
- `rag_nexus_francais_quatrieme_tc`.

Elles portent `niveau=quatrieme`, `voie=college`,
`statut=tronc_commun` et restent toutes deux `instanciee=false`. Leurs
taxonomies et l'index programme Quatrième lient exclusivement la version
`BOEN_special_11_2018-07-26_aj_2020`. Une autre valeur, un niveau `4e`, un
fallback `cycle4` ou une voie absente ne constitue pas une autorité valide.

## Limites et activation

Cette ADR n'autorise ni ingestion, ni serving, ni activation de collection.
Les deux flags ne pourront passer à `true` qu'après inventaire non vide,
preuves artifact-bound, profils exacts, ingestion gouvernée et réconciliation
release/readiness complète. ADR-0039 reste l'unique autorité d'activation Wave
0 et ne couvre pas la Quatrième.

## Conséquences

- les schémas Python/JSON et les types Cockpit sont régénérés depuis le
  contrat canonique ;
- le snapshot Cockpit reflète mécaniquement le catalogue sans compteur codé en
  dur ;
- les deux collections sont déclarables mais non résolvables pour le serving ;
- profils, mappings, inventaires, scopes signés et releases multi-niveaux
  restent des gates distincts et ne sont pas créés par cette ADR.
