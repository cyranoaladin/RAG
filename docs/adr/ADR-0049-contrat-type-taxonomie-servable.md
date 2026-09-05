# ADR-0049 — Contrat typé de la vue taxonomie servable

- **Statut** : accepté
- **Date** : 2026-09-06
- **Portée** : `packages/contracts` (0.16.0 → 0.17.0), `services/rag-engine` (`GET /taxonomy/v2`)
- **Références** : ADR-0001 (séparation des plans), ADR-0038 (scopes de retrieval v2)
- **Ordre de version** : 0.16.0 est prise par ADR-0048 (émetteur canonique de
  scopes, PR #149), qui entre avant ce lot ; celui-ci prend donc 0.17.0.

## Contexte

`GET /taxonomy/v2` rendait `dict[str, Any]`. FastAPI publiait donc, dans le
document OpenAPI, un objet sans forme. Un générateur de client — c'est-à-dire
un agent extérieur, qui est la raison d'être de cette API — n'y découvrait ni
`version`, ni la structure d'une collection, ni le type d'une valeur de
dimension. Il devait coder contre une observation du trafic, pas contre un
contrat : toute évolution silencieuse du dictionnaire cassait ses clients sans
que rien ne le signale.

La règle du dépôt est explicite : le cockpit et tout appelant ne parlent qu'au
contrat, et le contrat vit dans `packages/contracts`, versionné en SemVer avec
un ADR. Un type local au service aurait redéfini le contrat dans le service.

## Décision

Publier `TaxonomyV2Response`, `TaxonomyCollectionV2` et `TaxonomyDimensionsV2`
dans `nexus_contracts`, exporter leur JSON Schema
(`schema/taxonomy-v2-response.json`), et déclarer le modèle en
`response_model` de la route. `packages/contracts` passe en **0.17.0** :
ajout, aucune rupture — aucun contrat existant n'est modifié ni retiré.

### Les dimensions que le contrat décrit, et celles qu'il refuse de promettre

Décrites, parce que le moteur les dérive réellement du scope serveur et du
catalogue :

`matiere`, `niveau`, `voie`, `statut_enseignement`, `programme_version`,
`school_year`, et l'identifiant de `collection`.

La **spécialité** n'a pas de dimension propre : elle est portée par
`statut_enseignement` (`specialite`, `tronc_commun`, `option`), qui est la
dimension réellement gouvernée. Lui en inventer une dupliquerait la vérité.

Absentes, délibérément :

- `chapitre` et `notion` — aucune taxonomie fermée ne les borne côté moteur.
  `notion` est du texte libre d'appelant : il est *filtré*, jamais énuméré.
  Publier une énumération que rien ne peut produire serait une promesse fausse.
- `type_document` — ce n'est pas une dimension de collection ; il qualifie un
  artefact, à un autre niveau du modèle.

Cette liste est la mesure de ce qui existe, pas le plan de ce qu'on voudrait.

## Conséquence associée : fail-closed n'est pas muet

La même route absorbait toute `HTTPException` levée par le contrôle de
servabilité pour passer à la collection suivante. Une collection délibérément
non servable (403) doit en effet être omise en silence : c'est la décision
d'autorisation qui s'exprime.

Mais une panne d'autorité de release, un catalogue malformé ou une
indisponibilité de base (500, 503) étaient absorbés de la même façon : le
client recevait une taxonomie **vide en 200**, indistinguable d'un compte
légitimement vide. Seul le 403 est désormais silencieux ; tout autre statut
remonte à l'appelant.

## Alternatives écartées

- **Garder `dict[str, Any]` et documenter en prose.** Une documentation qui
  n'est pas dérivée du code dérive du code.
- **Typer localement dans `services/rag-engine`.** Interdit par les règles
  cross-service, et cela replacerait l'autorité du contrat dans le service.
- **Annoncer `chapitre`, `notion`, `type_document` comme listes vides.** Un
  champ toujours vide n'est pas une dimension : c'est une promesse qui ne sera
  jamais tenue, et un client la traiterait comme un manque de données.
