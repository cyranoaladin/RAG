# Candidats d’autorisation de production 2026-2027 — conception

## Statut et périmètre

Cette conception matérialise les décisions produit déjà approuvées pour les
sections 21 à 23 de la direction projet RAG. Elle ne rouvre aucune décision
P01–P24 et ne crée ni faux `ReviewBinding`, ni `AuthorizationSetV1` anticipé,
ni écriture en production.

Le tree de départ est le `main` fusionné au commit
`3566cafb44138d6a7f00296dc0654257f9bf0ad6`. Le set final contient exactement
26 SHA-256, de digest
`fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0`,
répartis par le placement de release sur 18 `ResourceScope` exacts.

## Décision d’architecture

Le lot ajoute un producteur déterministe minimal qui relit exclusivement les
artefacts versionnés de la release profils fusionnée et écrit un
`ScopeAuthorizationArtifactV2` canonique par scope. Les modèles et les
vérificateurs existants de `nexus-contracts` restent la source de vérité ;
aucun nouveau protocole n’est introduit.

Les 18 autorisations sont portées par une seule PR candidat. Chaque artefact
reste individuel et sera lié, après une unique revue GitHub humaine du HEAD
exact, par son propre `ScopeAuthorizationReviewBindingV1`. Le producteur de
binding existant sera exécuté une fois par identifiant avec la clé Ed25519
offline détenue par l’opérateur. Ainsi, la revue peut couvrir le même HEAD sans
affaiblir la liaison individuelle artefact/reçu.

Les bindings ne peuvent pas être ajoutés à la PR qu’ils attestent : modifier
le HEAD invaliderait la revue. La PR d’autorité reste donc ouverte et son HEAD
immuable pendant toute la durée des autorisations, conformément à ADR-0032.
Les 18 bindings sont émis après la review exacte, tant que cette PR est encore
ouverte, puis conservés avec les octets exacts des artefacts pour construire le
bundle de release et l’`AuthorizationSetV1` dans un lot suivant. La PR
d’autorité n’est jamais fusionnée ; sa fermeture ou le dismissal de la review
révoque le chemin live fail-closed.

## Entrées figées et contrôles fail-closed

Le producteur relit et recoupe les sources suivantes :

- `docs/reports/final_production_eligible_set_20260825.txt` pour l’union exacte ;
- `docs/reports/release_scope_placement_20260825.jsonl` pour la fonction totale
  contenu → profil → scope ;
- `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/production-profile-gate.release.json`
  et ses 18 releases sujet pour la présence, les URLs et les contenus exacts ;
- `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/authority_bindings.json`
  pour tous les digests de preuves ;
- `pii_evidence.json`, `currentness_evidence.json` et
  `services/rag-pedago/configs/rights_evidence_registry.yml` pour les décisions
  PII, currentness et droits.

La génération refuse toute dérive de digest, contenu absent ou supplémentaire,
scope/profil contradictoire, recouvrement, preuve PII non `CLEARED`, currentness
non `CURRENT`, source hors de `01_EDUSCOL_OFFICIEL`, domaine non institutionnel,
catégorie de droits non résolue, ou contenu sans correspondance unique dans une
release sujet.

L’union des 18 allowlists doit être exactement les 26 SHA finaux ; les
allowlists doivent être deux-à-deux disjointes. Le digest de leur union doit
rester `fe97b341…`.

## Contenu des autorisations

Pour chaque scope :

- `authorization_id` est
  `prerentree-2026-2027-<profile_id>-v1`, en forme canonique ;
- `scope`, `profile_id`, `profile_version` et `profile_fingerprint` proviennent
  octet pour octet du placement accepté ;
- `manifest_digest` vaut le fingerprint du manifeste de profils
  `57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c`,
  conformément à ADR-0044, et non le digest du manifeste corpus ;
- `allowed_content_sha256` est la partition triée de ce scope ;
- `allowed_domains` est l’union triée des hôtes réellement déclarés par les
  artefacts du scope, limitée aux domaines institutionnels observés
  `eduscol.education.gouv.fr` et `www.education.gouv.fr` ;
- `rights_categories=["officiel_public"]`, car les 26 sources sont dans la
  zone scellée `01_EDUSCOL_OFFICIEL` couverte par le registre de droits ;
- `pii_absence_attested=true` et `pii_absence_evidence` lie le chemin et le
  SHA-256 exact de la preuve PII couvrant les 26 contenus ;
- `exclusions=[]`, aucune restriction documentaire contradictoire n’étant
  présente dans les faits versionnés retenus ;
- la fenêtre uniforme est
  `[2026-08-25T00:00:00Z, 2027-08-25T00:00:00Z)`, soit une durée bornée d’un
  an à partir du profile gate. Toute prolongation exigera une nouvelle
  autorisation ou un nouveau protocole de renouvellement.

## Sorties et auditabilité

Les sorties versionnées sur la branche d’autorité dédiée sont :

- `governance/authorizations/<authorization_id>.json` pour les 18 artefacts
  canoniques ;
- `docs/reports/production_authorization_matrix_20260825.json` pour les
  digests, counts, scopes, contenus et références de preuve ;
- `docs/reports/lot_production_authorization_candidates_20260825.md` pour les
  invariants de lot et le gate opérateur suivant.

Le builder offre un mode de vérification/replay qui compare les octets attendus
aux fichiers versionnés et refuse un fichier manquant, supplémentaire ou
modifié. Les tests couvrent les mutations de chaque famille de preuve, la
partition, la canonicalisation et le replay byte-identique.

## Gates suivants

Après CI et deux revues contradictoires fraîches, la PR s’arrête au vrai gate
`trusted-human-review` sur son HEAD exact. Une fois cette review obtenue, les
18 commandes de production des `ReviewBinding` sont préparées ensemble et
exécutées avant toute fermeture de la PR. Le producteur existant doit accéder
à GitHub pour revalider la PR et son HEAD au moment de signer ; « clé offline »
signifie ici que la clé reste détenue par l’opérateur, hors Git, CI, serveur et
logs, pas que la commande est air-gapped. La clé privée n’est jamais demandée,
stockée, affichée ou transmise. Le lot suivant vérifie les 18 reçus avec les
octets exacts issus de la branche ouverte, construit `AuthorizationSetV1`, puis
enchaîne campagne V2, republish et H2 V2. La PR d’autorité reste ouverte et
inchangée jusqu’à l’expiration ou la révocation explicite de la release.
