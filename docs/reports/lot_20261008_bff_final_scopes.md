# Lot — raccordement BFF aux scopes contractuels V4/V5

Le Cockpit signait exclusivement le pilote `libre_terminale_maths_nsi_real_v1`
(maths et NSI terminale). La release V4+V5 courante contient 11 collections,
dont aucune maths. La readiness du pilote agrège ses deux collections et
empêche donc le parcours HTTP de recherche sur le produit final.

Cette PR génère depuis `packages/contracts` la projection Cockpit des **11
artefacts V2 internes déjà gouvernés** par les autorisations successeurs V4 et
HGGSP V5. La génération les charge aussi par le registre Python canonique,
qui valide schéma et digest épinglé, puis vérifie l'unicité des `scope_id` et
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
une matière et dériver une nouvelle identité exigerait un lot gouverné distinct.
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

Validation locale sur la base `6f33805601bdd04b9b10b3ae75febf01c63773e2` :
`npm ci` PASS ; `npm run test -- --run` : 204/204 PASS ;
`npm run lint`, `npm run typecheck`, `npm run contracts:check` et
`npm run build` PASS ; `npm audit --omit=dev` : zéro vulnérabilité.
La mesure live est confiée au harnais de la PR #293,
à adapter au scope NSI V2 après l'intégration de ce lot.
