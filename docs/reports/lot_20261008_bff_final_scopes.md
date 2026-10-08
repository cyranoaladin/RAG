# Lot — raccordement BFF aux scopes contractuels V4/V5

Le Cockpit signait exclusivement le pilote `libre_terminale_maths_nsi_real_v1`
(maths et NSI terminale). La release V4+V5 courante contient 11 collections,
dont aucune maths. La readiness du pilote agrège ses deux collections et
empêche donc le parcours HTTP de recherche sur le produit final.

Cette PR génère depuis `packages/contracts` la projection Cockpit des **11
artefacts V2 internes déjà gouvernés** par les autorisations successeurs V4 et
HGGSP V5. Le générateur Node compare les digests JSON canoniques aux onze
empreintes épinglées par les registres `nexus_contracts.scope` et
`nexus_contracts.hggsp_successor_scopes`, puis vérifie l'unicité des `scope_id` et
l'égalité de la population des collections
avec le registre de release V4+V5 ; la sélection est explicitement figée dans
le générateur et n'adopte pas automatiquement de futurs artefacts publics. La
copie générée conserve le digest canonique des artefacts Python : NSI terminale
`prod_nsi_terminale_specialite_v3` donne
`dd6eeafd7749b9cd7f3084fec826707100756f330005a68f385d0dada1979b2d`.

Une identité SSO correspondant exactement à une cible de l'un des 11 scopes
reçoit un jeton interne lié à **une seule collection**. À l'entrée BFF, la
signature, le digest et les dimensions du scope sont revérifiés ; la route de
recherche construit le profil API v2 depuis ce scope. La readiness moteur ne
porte plus sur une collection maths absente pour ces profils. Le scope pilote
historique reste accepté et inchangé pour ses identités, sans promotion
silencieuse. La rotation d'un jeton conserve son `scope_id`.

Le contrat V2 canonique impose exactement une matière dans l'identité signée
(`profile.matieres == [target.matiere]`). Un profil SSO multi-matières qui ne
correspond pas au pilote historique reste refusé à la connexion : sélectionner
une matière et dériver une nouvelle identité exigerait un lot gouverné distinct
(ADR, évolution du contrat, autorité de dérivation et tests de bout en bout).
Le simple retrait de la condition mono-matière dans le Cockpit fabriquerait une
enveloppe que `RetrievalScopeArtifactV2.validate_envelope` refuse côté API.
La décision produit reste ouverte : confirmer un périmètre V1 mono-matière ou
autoriser explicitement ce nouveau protocole. Aucune identité SSO n'est
réétiquetée pour contourner ce refus.
Ce lot qualifie les onze collections avec des identités mono-matière distinctes.

La visibilité des 11 artefacts est toujours `internal`. Aucun filtre moteur,
aucune liste `_ROLE_VISIBILITIES`, aucun chunk ni placement n'est modifié.
Un élève peut avoir une identité signée, mais le moteur doit continuer à
refuser ces placements ; le succès élève requiert la décision de droits,
la revue et la release publique distinctes. Ce lot ne revendique aucun
succès HTTP staging tant que le Cockpit final n'y est pas déployé et mesuré.

La release V1 expose seulement la recherche avec passages cités. Le verrou
`answer_generation_allowed=false` de
`services/rag-pedago/configs/pedago_interface_contract.yml` reste intact,
conformément aux ADR-0012 et ADR-0037. `/api/chat` répond explicitement
`503 answer_generation_disabled` après contrôle de session et de collection,
sans appeler le moteur ; l'interface ne présente plus de bouton de génération.
Cela évite également une erreur 500 sur les nouvelles collections, auparavant
absentes du scope pilote du chat. Une transition gouvernée distincte devra
réouvrir cette fonction.

Le build Next.js porte le SHA source dans son `BUILD_ID` (Git sur checkout,
ou `NEXUS_COCKPIT_BUILD_SHA` explicite pour une archive immuable). La route
`/api/health` expose ce SHA sans détail moteur ; le harnais BFF refuse un
runtime déployé dont le SHA diffère du checkout qualifié. L'image et la
provenance de l'archive restent à contrôler séparément lors du déploiement.

Code testé : `cb9547f6fd792bc623176c337bdc27858639062c` (arbre
`bf2ba108fe154ab85de5610a4456931a487a332d`), sur `main`
`1ab971838e90c876bf185da03b67423f9f0a32c9` (arbre
`cbdae38bedfe6a4ba9f3a1f32a6b29fe9bfa4c88`). Depuis
`services/cockpit` dans ce worktree isolé :

```sh
npm ci --no-audit --no-fund             # 495 paquets installés
npm test -- --run                       # 218 tests, 25 fichiers, tous verts
npm run lint                            # exit 0
npm run typecheck                       # exit 0
npm run contracts:check                 # exit 0
npm run build                           # exit 0 ; .next/BUILD_ID = cb9547f6...
env PATH='' /usr/bin/node scripts/generate-contracts.mjs --check # exit 0 sans Python
```

Les nouveaux tests ont d'abord échoué parce que l'import du générateur
réécrivait `src/generated`, que le contrôle lançait Python même sous Vitest,
et que la commande Git de provenance n'avait pas de délai maximal. Ils passent
après garde de l'entrée CLI, vérification Node des digests épinglés et délai
Git de 5 secondes. `contracts:check` conserve le prérequis Python existant
pour exporter les schémas ; `npm test` et `contracts:generate` n'en ajoutent
aucun. Le commit de rapport suivant est documentaire seulement.

Le harnais #293 au HEAD `a6749e6be61b0bffe8470f810edfac92e8077014`
lit toujours le même JSON de onze scopes, le digest canonique et le SHA exposé
par `/api/health` ; ses interfaces restent compatibles. Aucun parcours HTTP
staging n'a été exécuté ici, et son E2E reste conditionné au déploiement du
Cockpit final sur la cible qualifiée.
