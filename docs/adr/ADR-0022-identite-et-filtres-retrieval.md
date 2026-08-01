# ADR-0022 — Identité interne et filtres de retrieval

- **Statut** : proposé (LOT41 ; accepté uniquement après fusion de la PR)
- **Date** : 2026-08-01
- **Périmètre** : contrat d'identité cockpit → rag-engine et scope pilote
  `libre_terminale_maths_nsi_real_v1`
- **S'appuie sur** : [ADR-0001 — séparation contrôle/données/cockpit](ADR-0001-separation-controle-donnees-cockpit.md),
  [ADR-0002 — contrat d'interface partagé](ADR-0002-contrat-interface-partage.md)
  et [ADR-0021 — politique de validation pilote dormante](ADR-0021-politique-validation-pilote-dormante.md)

## Contexte

Le contrat `nexus-contracts` 0.3.0 transporte une identité interne insuffisamment
fermée : l'année scolaire n'est pas liée à l'identité, plusieurs claims sont peu
bornés et aucune enveloppe canonique ne lie l'identité au scope adressé issu du
plan de contrôle. Une identité 0.3 peut donc être syntaxiquement valide sans
porter toutes les dimensions nécessaires au filtrage fail-closed.

ADR-0021 impose que LOT41 raccorde `rag-engine` au scope LOT38 par contrat ou
artefact, sans import ni lecture runtime de `rag-pedago`. Le YAML canonique
LOT38 a pour SHA-256 brut
`b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26`.
Il reste `eligible_for_promotion`, jamais `active`, et n'ouvre aucun verrou.

## Décision

### Rupture contractuelle 0.4.0

`nexus-contracts` passe de 0.3.0 à 0.4.0. `InternalIdentity.school_year`
devient obligatoire au format contigu `YYYY-YYYY+1`. Les identités 0.3 qui
n'ont pas ce champ sont refusées ; aucun décodeur permissif ni valeur par
défaut ne maintient une compatibilité silencieuse.

Ce passage est volontairement cassant. Il **amende explicitement ADR-0002**
pour le cycle pré-1.0 : bien que le numéro `0.3.0 → 0.4.0` incrémente la
composante mineure au sens syntaxique de SemVer, LOT41 traite cette livraison
comme un changement **major-equivalent**. Le cockpit, le moteur et les artefacts
générés doivent effectuer un cutover coordonné vers 0.4.0. Toute évolution
cassante ultérieure reste soumise à un ADR et à la même coordination ; cette
exception ne banalise pas les ruptures pré-1.0.

Le même contrat impose :

- un `sub` pseudonymisé préfixé `psn_`, jamais une adresse ou un identifiant
  directement personnel ;
- des claims et chaînes bornés, un `jti` non trivial, des matières bornées,
  non vides et uniques ;
- un `exp` entier strictement positif, non coercitif et inférieur ou égal au
  plus grand entier JavaScript sûr (`9007199254740991`) ;
- des modèles fermés par `extra='forbid'`, sans email, identifiant élève,
  objectif libre, secret ou autre PII.

Les schémas JSON canoniques du package portent des identifiants `/v0.4/`.

### Enveloppe interne canonique

`InternalIdentityEnvelope` devient l'unique modèle partagé de l'enveloppe
signée. Sa `protocol_version` vaut exactement `1`. Elle lie les claims externes
`sub`, `jti`, `iat` et `exp` à l'objet `InternalIdentity`, au `scope_id`, au
`scope_digest` et à une liste non vide et unique de collections autorisées.
Le modèle refuse un `sub` ou `jti` différent de l'identité imbriquée, un
`exp` supérieur à celui de l'identité ou un `iat` postérieur à `exp`.

L'issuer et l'audience de transport restent des réglages serveur obligatoires,
distincts dans le cockpit et le moteur, et doivent être comparés exactement au
runtime. Ils ne sont ni dérivés du navigateur, ni inscrits dans l'artefact
LOT38, qui ne les définit pas. Le dépôt ne contient ni valeur secrète ni clé de
signature.

Aucun service ne redéfinit localement cette enveloppe. Les consommateurs
doivent utiliser `nexus-contracts==0.4.0` et appliquer en plus les contrôles
cryptographiques, de durée de vie, de révocation et de concordance avec leur
configuration serveur.

### Artefact dormant du scope LOT38

Le package livre `PilotRetrievalScopeArtifact`, projection fermée du YAML
LOT38. L'artefact contient exactement :

- le scope `libre_terminale_maths_nsi_real_v1`, son état dormant, l'année
  `2026-2027` et le SHA-256 brut du YAML source `b55ef138…` ;
- l'identité non personnelle `libre_terminale`, `terminale`, `generale`,
  `specialite`, audience `libre`, candidats `cned_libre`, `individuel` et
  `libre` ;
- les matières `maths` et `nsi`, leurs collections uniques et la version de
  programme `BOEN_special_8_2019-07-25`.

Le SHA-256 des octets JSON canoniques de cet artefact (UTF-8, clés triées,
séparateurs compacts) est
`a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24`.
C'est cette valeur, distincte du SHA brut du YAML source, que porte
`InternalIdentityEnvelope.scope_digest`. Le consommateur refuse toute
divergence de `scope_id`, digest, projection d'identité ou liste de
collections ; `allowed_collections` doit être exactement la liste ordonnée des
collections de l'artefact.

L'artefact permet au cockpit et au moteur de partager le scope sans importer
le code de `rag-pedago` ni lire ses fichiers au runtime. Les tests du package
restent autorisés à comparer l'artefact au YAML versionné afin de prouver la
projection et le digest entre services.

### Fermetures fail-closed préparées par LOT41

Le filtrage final reste construit côté moteur à partir de l'identité validée et
du scope serveur. Aucun champ fourni dans le corps d'une requête ne peut
élargir le tenant, le niveau, la voie, le statut, l'audience, la matière,
l'année ou la collection.

Les décisions humaines de review doivent être liées au tenant et à la
collection. La seule révocation additionnelle autorisée est
`reviewed → quarantined` dans le même scope ; elle n'autorise ni réactivation,
ni retour implicite à `needs_review`. Une révocation doit être visible avant
toute réponse de retrieval.

Après disponibilité du chemin BFF canonique authentifié, les routes historiques
qui acceptent un profil, un token de test ou des filtres contournables doivent
être fermées ou supprimées de la surface de production. Aucun alias permissif
ne peut contourner l'enveloppe 0.4.0.

## Conséquences

- Le cutover exige la mise à niveau coordonnée des producteurs et
  consommateurs ; une identité 0.3 échoue volontairement.
- Le package devient l'unique source des modèles d'identité, d'enveloppe et de
  scope. Les schémas sont déterministes et adressés par version.
- Le digest de l'artefact lie la configuration de release aux octets exacts du
  scope projeté, tandis que `source_sha256` conserve la traçabilité vers LOT38.
- L'artefact reste dormant : il n'autorise aucun document réel, pipeline,
  appel externe, génération de réponse, publication ou route publique.
- Aucun verrou de gouvernance n'est modifié ni activé par cette décision.

## Retour arrière

Le retour arrière est coordonné : arrêter les producteurs d'enveloppes 0.4,
fermer les routes de retrieval concernées, révoquer les jetons encore valides,
puis remettre ensemble producteurs et consommateurs sur une version
compatible. Réinstaller seulement le moteur ou seulement le cockpit en 0.3 est
interdit, car cela recréerait une frontière d'identité incohérente.

L'artefact dormant peut rester versionné pendant ce rollback : il n'active
aucune capacité. Toute divergence ou absence de configuration maintient le
refus fail-closed et tous les verrous restent à `false`.
