# ADR-0023 — Review via BFF et durcissement du runtime

- **Statut** : proposé (LOT41R ; accepté uniquement après fusion de la PR)
- **Date** : 2026-08-02
- **Périmètre** : protocole de review partagé entre navigateur, cockpit BFF et
  `rag-engine`
- **S'appuie sur** : [ADR-0001 — séparation contrôle/données/cockpit](ADR-0001-separation-controle-donnees-cockpit.md),
  [ADR-0002 — contrat d'interface partagé](ADR-0002-contrat-partage-nexus-contracts.md)
  et [ADR-0022 — identité interne et filtres de retrieval](ADR-0022-identite-et-filtres-retrieval.md)

## Contexte

Le runtime historique de review expose une frontière distincte du retrieval,
mais ses messages ne sont pas publiés dans `nexus-contracts`. Le cockpit et le
moteur pourraient donc dériver sur les champs acceptés, la pagination, la
provenance ou le résultat d'invalidation du cache. Surtout, un navigateur ne
doit jamais pouvoir choisir son tenant : ADR-0022 fait de l'identité interne
signée et du scope serveur les seules sources autorisées de cette dimension.

Le champ libre historique `reason` ne produit aujourd'hui aucune donnée
auditée et n'est consommé par aucune décision métier. Le transporter donnerait
une fausse garantie de traçabilité et ouvrirait une surface inutile de saisie
de données personnelles ou sensibles.

## Décision

### Extension du périmètre de `nexus-contracts`

`nexus-contracts` passe de `0.4.0` à `0.5.0` et publie six modèles fermés du
protocole de review : les paramètres de queue navigateur, la décision
navigateur, la décision moteur enrichie, le document de queue imbriqué et les
deux réponses moteur. Les cinq messages échangés possèdent un schéma JSON
racine déterministe adressé sous `/contracts/v0.5/` ;
`ReviewQueueDocument` reste une définition imbriquée dans la réponse de queue.

Cette décision **amende explicitement le périmètre historique d'ADR-0002**.
Sa liste de modèles « exclusivement » centrée sur
`RetrievalRequest → RetrievalResponse` décrivait l'état du Lot 0, pas une
interdiction permanente d'héberger d'autres coutures interservices. Le package
canonique couvre désormais aussi les messages de review qui franchissent les
frontières cockpit/moteur. Les interdictions d'ADR-0002 restent inchangées :
aucune logique métier, aucun accès I/O et aucune redéfinition locale dans un
service.

L'ajout des nouveaux messages est rétro-compatible avec les modèles 0.4.0
existants et justifie un incrément mineur pré-1.0. Les producteurs,
consommateurs, schémas et validateurs générés utilisent néanmoins ensemble les
artefacts 0.5 afin d'éviter une surface partiellement typée.

### Frontières navigateur, BFF et moteur

Le navigateur envoie uniquement `ReviewQueuePayload` ou
`ReviewDecisionPayload` au BFF. Ces modèles sont fermés et **ne contiennent pas
de tenant**. Une tentative d'ajouter `tenant` est rejetée ; la décision
navigateur ne contient pas davantage de `reason`.

Le BFF authentifie le reviewer, valide son identité et son scope selon
ADR-0022, puis construit `ReviewDecisionRequest`. Le champ `tenant` requis de
cette requête provient exclusivement de l'identité interne signée. Le passage
**BFF → moteur porte donc le tenant signé**, sur un canal interne authentifié ;
il ne recopie jamais une valeur du navigateur. Le moteur reste responsable des
contrôles d'autorisation, de collection et de transition au runtime. Le
contrat décrit les messages, pas ces règles métier.

Les réponses sont également fermées. La queue borne la pagination et la
provenance, puis exige que `returned` égale le nombre de documents. La réponse
de décision indique au moins un chunk affecté, l'invalidation du worker courant
et une durée maximale de stale inter-workers fixée contractuellement à zéro.

### Retrait du champ `reason`

`reason` est absent des deux décisions canoniques et rejeté comme clé extra.
Il est retiré parce qu'il est inutilisé, non audité et susceptible de recevoir
de la PII ou du texte sensible sans finalité ni politique de conservation.
Une justification future exigerait un besoin métier explicite, un stockage
audité, une politique de minimisation/rétention et une nouvelle évolution de
contrat ; elle ne sera pas réintroduite comme simple champ libre.

### Portée opérationnelle

Cette décision ne modifie aucune table et ne requiert **aucune migration de
base de données**. Elle n'active aucune collection, aucun pipeline et **aucun
verrou de gouvernance**. La publication du contrat ne vaut ni revue réelle du
corpus, ni autorisation de promotion, ni ouverture d'une route publique.

## Conséquences

- Le cockpit et `rag-engine` partagent une définition unique et versionnée de
  la review, avec types TypeScript et validateurs générés depuis les schémas.
- La frontière navigateur ne peut injecter ni tenant, ni justification libre ;
  l'identité signée reste l'autorité selon ADR-0022.
- Le document de queue est réutilisable seulement comme définition imbriquée,
  ce qui limite la surface publique aux cinq messages réellement échangés.
- Le raccord des endpoints moteur et des routes BFF reste un travail runtime
  séparé ; cet ADR ne l'implémente pas à lui seul.
- Le verdict global demeure explicitement **`GO_LIVE: NO_GO`**. LOT41R ne
  remplace aucune preuve exhaustive de substance, de review ou de promotion.

## Retour arrière

Le retour arrière est coordonné. Fermer d'abord toute route BFF de review
dépendant de 0.5, arrêter les appels moteur associés, puis remettre ensemble le
cockpit, le moteur, le package et les artefacts générés sur 0.4. Déployer un
générateur, un BFF ou un moteur avec un ensemble de schémas d'une autre version
est interdit.

Aucune migration de données n'étant créée, aucun rollback SQL n'est requis.
Les décisions déjà persistées par le moteur restent inchangées. En cas de
divergence de version ou d'identité, les frontières restent fermées et tous les
verrous de gouvernance demeurent dans leur état antérieur.
