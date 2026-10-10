# ADR-0071 — Droits et profils complets des scopes étudiants

- **Statut** : proposé dans la PR #294 ; l'émission reste interdite avant autorisation exacte des subjects finaux.
- **Date** : 2026-10-10.
- **Autorités** : décision documentaire déléguée #300, ADR-0064, successeur préparatoire #323.

## Constat

Le garde ADR-0064 de l'émetteur réutilisait deux valeurs de scopes PDF historiques : `rights=officiel_public` et `audiences=[libre,tous]`. La décision #300 refuse `officiel_public` comme preuve suffisante de l'usage public. Les onze profils YAML complets du successeur #323 portent `audience=[libre,aefe]` ; seuls les artefacts textuels dérivés admis portent le droit gouverné `public_allowed`. Le target étudiant du produit V1 demeure limité à `libre`.

## Décision

La proposition des onze nouveaux scopes expose séparément `rights=[public_allowed]`, `evidence_audiences=[libre,aefe]`, `programme_version` et la cible `roles=[student], audiences=[libre], candidates=[libre]`. Elle fige `scope_artifact_version=3` pour les onze identifiants `student_public_*_v1` déjà scellés dans #323. Son vérificateur confronte ces valeurs aux onze profils YAML complets, au registre de profils #323 et au registre des programmes V3 scellé. Le registre V3 est réutilisé uniquement comme autorité de versions et de SHA des taxonomies ; les releases V4/V5 restent internes et ne sont pas promues. Le garde de l'émetteur ADR-0064 refuse désormais les valeurs `officiel_public` et `tous` héritées des anciens PDF.

L'émetteur construit un `RetrievalScopeArtifactV3` uniquement pour l'autorité ADR-0064, avec `target_policy.roles=[student]`. Les autres politiques continuent à produire V2. Le lecteur du registre fermé reconnaît V3 lorsque son identifiant, son digest et sa version sont épinglés ; aucun identifiant actuel ne change. Un scope V2 du même subject ne peut être réutilisé comme scope public étudiant.

`nexus-contracts` passe de 0.24.0 à 0.25.0 : l'ajout de la voie V3 est mineur, sans changement de schéma ni d'artefact déjà émis. Une politique de registre finale reste nécessaire. Elle doit viser les SHA des subjects d'une release publique finale, après preuve d'autorité et revue exacte du HEAD ; elle ne peut être déduite du paquet candidat #323. Cette ADR n'émet aucun scope, n'active aucune publication et n'élargit pas le rôle étudiant à `internal`.
