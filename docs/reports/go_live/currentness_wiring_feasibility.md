# Câbler la politique d'actualité — ce que cela exige réellement

`CURRENTNESS_POLICY_APPLIED=false` est un bloqueur de pré-release. La question
posée était simple : que faut-il pour le fermer ?

La réponse ne l'est pas. **Basculer le drapeau serait une fausse déclaration.**

## Le dépôt a défini `applied` comme une mesure, pas comme une décision

Le ledger de fermeture le dit déjà : « Un consommateur de production applique la
politique et le gate le constate ; un registre seulement présent ne suffit pas. »

Aucun code de production ne lit
`services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml`. Les
seuls lecteurs hors épreuves et documentation sont le garde-fou d'unicité
d'autorité, qui le cherche, et l'évaluateur de readiness, qui lit le champ
`applied` pour **refuser** le go-live.

Basculer le drapeau ne changerait donc **rien au comportement** : le service
continuerait de filtrer sur `placement.currentness = 'current'` en SQL, sans
jamais consulter la politique.

## Trois mécanismes d'actualité coexistent, et aucun n'est la politique

| Mécanisme | Où | Vocabulaire |
| --- | --- | --- |
| Filtre de service | `retrieval_pg_v2.py`, SQL | `current` |
| Preuve d'ingestion | `multilevel_evidence.py` | `CURRENT`, `effective_currentness` |
| Gate de classement | `currentness_gate.py` | `actuel`, `transition`, `archive` |

Aucun ne produit le vocabulaire de la politique — `VERIFIED_CURRENT`,
`OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE`, `NOT_CURRENT_DECLARED_BY_SOURCE`. Ces
chaînes n'existent que dans le YAML, l'ADR, la documentation et deux épreuves.

Le seul endroit où les règles de la politique sont **exécutées** est une
réimplémentation locale, dans une épreuve. C'est délibéré : la coder dans le
producteur reviendrait à l'appliquer.

## Un évaluateur fantôme, qui ne dit pas son nom

`construire_matrice_servabilite.py` code en dur la table des statuts de source
en Python au lieu de charger le YAML. Ses libellés ne correspondent même pas aux
`currentness_disposition` de la politique. Il s'émet `applied: false`, ce qui est
correct, mais la duplication de règle est réelle.

## Ce que câbler exige, dans l'ordre

1. Un module chargeur, qui n'existe pas, produisant une disposition d'actualité
   par relation depuis `source_status_mapping` et `fallback_rule`.
2. Un `SERVABILITY_GATE` nommé, qui compose cette disposition avec les gates
   programme, PII, droits, classification et placement. **Ce gate n'existe pas
   comme module** : la cascade de la matrice est un rapport dérivé, explicitement
   pas une autorité.
3. Un consommateur. Le seul réaliste est la colonne `currentness` du placement,
   celle que lit le filtre SQL. Rien ne relie aujourd'hui la disposition à cette
   colonne.
4. Épingler le nouveau lecteur dans la baseline d'unicité d'autorité, sinon la
   CI le refuse — ce qui est le comportement voulu.
5. Amender l'épreuve qui fige `applied is False`.
6. Faire passer ADR-0055 à Accepté.

Un module attendu manque d'ailleurs déjà :
`rag_pedago/governance/currentness_disposition.py`, absent de `main` comme du
lot d'actualité, et signalé comme tel dans la vérification de supersession.

## Ce qui se passerait si l'on basculait le drapeau seul

| Effet | Résultat |
| --- | --- |
| Comportement du service | aucun |
| Verrous de gouvernance | non touchés, autre fichier, autre clé |
| Garde-fou d'unicité | passe encore, il ne lit pas le drapeau |
| Épreuve de la politique | **échoue** |
| `pre_release_blockers` | tomberait de 2 à 1 |
| Cohérence d'ADR-0055 | **contredite**, l'ADR fixe `applied=false` |

Le compteur baisserait donc sans que rien ne change, et l'ADR fusionnée dirait
l'inverse du dépôt.

## Un défaut corrigé en chemin

Le message d'erreur du garde-fou annonçait « la politique d'actualité est
applied=false et a un lecteur de production ». Or ce contrôle **ne lit pas**
`applied` : il affirmait une condition qu'il ne vérifiait pas, et aurait envoyé
chercher au mauvais endroit quiconque le rencontre. Il dit maintenant ce qu'il
vérifie réellement : un lecteur de production non épinglé.

## Propriétaire et volume

Ingénierie, pas décision humaine. Mais ce n'est pas un drapeau à basculer : c'est
un module à écrire, un gate à nommer, un consommateur à relier, et une ADR à
faire accepter.
