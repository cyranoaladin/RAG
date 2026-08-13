# ADR-0034 — LOT41A-V2 : autorité positive liée au contenu

- **Statut** : Proposé — **non Accepté**. Une acceptation exige une review
  humaine `APPROVED` du Code Owner `@abenrhouma` sur le HEAD exact de la PR
  d'implémentation.
- **Date** : 2026-08-09
- **Décideur proposé** : à confirmer par `@abenrhouma`.
- **Périmètre** : évolution technique candidate de LOT41A ; ce document ne
  constitue aucune autorisation de corpus et n'active aucune ingestion.
- **S'appuie sur** : ADR-0025, ADR-0026, ADR-0032 et ADR-0033.
- **Ne supersede pas LOT41A-V1** : les décisions V1 conservent leur sens et
  leur représentation exacts.

## Contexte

LOT41A-V1 borne un scope, des domaines et des exclusions. Un domaine autorisé
peut toutefois servir plusieurs documents : la preuve PII d'un sous-ensemble
n'empêche pas, à elle seule, un autre contenu du même hôte d'avancer. Une
référence libre dans `pii_absence_evidence` n'est pas une règle exécutable et
une URL n'est pas une identité de contenu : elle peut rediriger ou servir de
nouveaux octets.

## Décision

LOT41A-V2 ajoute à l'artefact Git canonique la liste positive obligatoire
`allowed_content_sha256`. Elle est non vide, lisible dans la PR, composée de
SHA-256 minuscules, triés et uniques. La liste participe directement à la
sérialisation canonique et au digest de l'autorisation.

Le SHA-256 est l'identité autoritaire parce qu'il désigne les octets revus et
reste stable quand un chemin ou une URL change. Les contrôles de destination
restent obligatoires et cumulatifs : une identité de contenu autorisée ne
permet jamais d'atteindre une destination interdite.

V1 et V2 utilisent deux modèles stricts discriminés par `protocol_version`.
V1 n'accepte aucun champ V2 ; V2 exige sa liste. Une version inconnue échoue.
La politique H2 de publication de documents réels exige V2 : une autorisation
V1 valide peut continuer d'exister pour compatibilité, mais ne satisfait pas
`H2_CONTENT_BOUND_AUTHORITY_REQUIRED`.

## Point de contrôle contenu

Après validation live de l'autorité et de chaque destination, le fetcher reçoit
les octets dans une limite de taille, calcule leur SHA-256 et revérifie
l'autorité en direct. Il compare ensuite le SHA à l'allowlist V2 **avant** :

- toute transition `FETCHED` ;
- tout stockage durable d'artefact ;
- extraction ou parsing ;
- droits, qualité et revue ;
- toute écriture produit ou pgvector.

Une révocation pendant le téléchargement empêche donc l'extraction. Un refus
ne journalise que des métadonnées assainies et libère les octets temporaires.
Les contrôles de droits et la revalidation déjà effectuée à leur checkpoint ne
sont pas supprimés.

## Représentation PostgreSQL

La migration ingestion-control 009 ajoute
`allowed_content_sha256 TEXT[] NULL`. Les contraintes imposent :

- `LOT41A-V1` avec NULL uniquement ;
- `LOT41A-V2` avec tableau unidimensionnel, borne inférieure 1, non vide,
  sans NULL, SHA-256 minuscules, ordre bytewise canonique et unicité.

La vérification live recompare la liste exacte et son ordre au blob Git. Une
extension, réduction, substitution ou réorganisation directe en base invalide
l'autorisation. L'opérateur d'enregistrement ne fournit aucun SHA en argument :
il ne fait que relire et projeter le blob approuvé.

## LOT42

Pour H2, LOT42 exige une autorisation V2 live dont la liste contient le SHA du
fait durable. Ce fait vient de l'artefact persisté et de l'événement de contrôle
contenu lié à l'identifiant, au digest et à la version de l'autorisation ; il
n'est jamais fourni librement par l'opérateur. Une divergence interdit
`RETRIEVAL_ELIGIBLE`.

## Révocation et rollback

La révocation reste celle d'ADR-0032 : fermeture/dismissal/head drift/expiration
invalident V2 aux mêmes checkpoints, notamment après téléchargement. Le
rollback 009 refuse de retirer la colonne ou les contraintes tant qu'une ligne
V2 existe. Il ne convertit jamais V2 en V1 et ne détruit jamais silencieusement
la frontière positive.

## Migration et compatibilité

L'ajout du nouveau modèle public est rétro-compatible et porte
`nexus-contracts` de `0.6.0` à `0.7.0`. Le namespace des schémas exportés reste
inchangé selon ADR-0026. Les lignes et artefacts V1 restent lisibles et
strictement identiques. La future autorisation de production PR #96 ne sera
régénérée en V2 qu'après fusion de l'implémentation et CI verte sur `main`.

## Conséquences

- Une URL ou un domaine ne peut plus élargir le corpus H2 au-delà des octets
  explicitement revus.
- Le texte de preuve PII reste auditable mais n'est jamais interprété comme
  allowlist.
- PR #95 peut fusionner du code inerte testé avec des autorités V2 de staging ;
  une autorisation réelle reste indispensable avant toute ingestion live.
- Le rollback devient volontairement bloquant en présence de décisions V2,
  afin qu'un retour applicatif ne supprime pas une frontière de sécurité.
