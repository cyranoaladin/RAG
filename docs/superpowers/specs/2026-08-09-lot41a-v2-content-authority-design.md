# LOT41A-V2 — autorité liée au contenu

## Statut de la conception

Conception approuvée par l'instruction de gouvernance Nexus Réussite H2-E du
9 août 2026. Cette spécification ne lève aucun verrou de production : PR #96
reste gelée, l'ingestion live reste désactivée et aucun accès à une base de
production n'est autorisé.

## Problème

LOT41A-V1 lie une décision humaine à un scope, des domaines et des exclusions
négatives. Cette frontière ne prouve pas que le contenu effectivement reçu a
fait partie des artefacts contrôlés par la preuve PII. Un document différent,
servi par le même domaine autorisé, franchit aujourd'hui le contrôle de
destination. Le digest libre inclus dans `pii_absence_evidence` est utile à
l'audit mais n'est ni un contrat structuré ni une règle exécutée.

## Approches considérées

1. **Nouveau protocole canonique LOT41A-V2 (retenu).** Ajouter une allowlist
   explicite et obligatoire de SHA-256 dans un modèle V2 distinct, la projeter
   en PostgreSQL et l'appliquer aux octets téléchargés. Cette solution préserve
   V1 et rend la décision directement lisible dans la PR GitHub.
2. **Modifier LOT41A-V1.** Rejeté : cela changerait silencieusement le sens de
   décisions V1 existantes et rendrait leur sérialisation historique ambiguë.
3. **Interpréter le texte PII, élargir les exclusions ou faire confiance aux
   URL.** Rejeté : ces mécanismes ne constituent pas une allowlist positive et
   ne lient pas les octets réellement traités à la revue humaine.

## Contrat partagé

`ScopeAuthorizationArtifact` conserve exactement le modèle LOT41A-V1 public,
avec l'alias explicite `ScopeAuthorizationArtifactV1`. Un nouveau
`ScopeAuthorizationArtifactV2` porte les mêmes champs et ajoute
`allowed_content_sha256`, tuple non vide de SHA-256 minuscules, triés et
uniques. `ScopeAuthorizationArtifactV1` est fourni comme alias explicite du
modèle historique afin de rendre le dispatch lisible sans casser l'import
public existant.

Le type public `ScopeAuthorizationArtifactAny` est l'union fermée V1/V2. Le
parseur inspecte exclusivement `protocol_version`, puis valide le document
avec le modèle strict correspondant. V1 rejette le champ V2, V2 exige ce champ,
et toute version inconnue échoue. La liste V2 est exposée sous forme de tuple
immuable déjà canonique. Elle apparaît dans
`canonical_document()`, donc toute mutation modifie les octets canoniques et le
digest. La version du paquet passe de `0.6.0` à `0.7.0`, ajout rétro-compatible
au sens de la politique SemVer du dépôt. Le namespace des schémas JSON reste
inchangé, conformément à ADR-0026.

## Projection PostgreSQL

La migration ingestion-control 009 ajoute
`allowed_content_sha256 TEXT[] NULL`, élargit le CHECK de protocole à V1/V2 et
ajoute un helper IMMUTABLE de validation. Une contrainte croisée impose :

- V1 : liste NULL ;
- V2 : liste non NULL, non vide, entièrement composée de SHA-256 minuscules,
  triée et sans doublon.

Le helper renvoie toujours un booléen non NULL. Il exige un tableau à une
dimension, une borne inférieure égale à 1, aucun élément NULL, l'expression
exacte `^[0-9a-f]{64}$`, l'ordre lexicographique bytewise `C`, et l'unicité.
Des écritures SQL directes prouvent le refus des listes NULL/vides,
multidimensionnelles, décalées, malformées, en majuscules, dupliquées ou non
triées, ainsi que de V1 avec une liste V2.

`_AUTHORIZATION_COLUMNS`, l'enregistrement opérateur, la reconstruction et la
lecture live portent la colonne. `VerifiedAuthorization` expose
`protocol_version` et `allowed_content_sha256: tuple[str, ...] | None` : NULL
est la seule représentation de V1, un tuple non vide celle de V2. La lecture
live compare la version et la liste, dans l'ordre canonique, entre la ligne et
le blob Git approuvé. Toute extension, réduction, substitution ou
réorganisation de la liste échoue. Le rollback 009 refuse explicitement de
continuer si une ligne V2 existe ; il ne supprime jamais silencieusement une
frontière de sécurité.

## Flux d'exécution

Le worker conserve les contrôles de scope et de destination avant accès
réseau. Le fetcher valide aussi chaque redirection et l'URL finale avec le
même contrôle de destination. Il calcule le SHA-256 des octets reçus dans son
buffer borné puis appelle un checkpoint injecté avant toute transition
`FETCHED`, tout stockage d'artefact ou toute extraction. Le callback relit
l'autorité en direct afin qu'une révocation pendant le téléchargement prenne
effet ; c'est cette nouvelle instance revérifiée, jamais celle mise en cache
avant le fetch, qui est passée à `enforce_content_sha256`.

Pour V2, l'absence du SHA dans l'allowlist produit un
`ScopeEnforcementViolation(checkpoint="content")`. Pour V1, le mécanisme
historique reste utilisable hors politique H2, mais une fonction de politique
H2 exige explicitement V2 et refuse V1 avec le motif
`CONTENT_ALLOWLIST_AUTHORITY_REQUIRED`. Aucun octet refusé n'est stocké dans le
magasin durable, aucune transition de ressource n'est appliquée et aucun agent
d'extraction, droits ou qualité n'est appelé. Le buffer temporaire est libéré
dans tous les chemins de refus, exception ou annulation ; aucune référence vers
ses octets ne survit au checkpoint.

La destination et le contenu sont des contrôles cumulatifs : un SHA autorisé
ne sauve jamais une URL interdite, tandis qu'une URL autorisée ne sauve jamais
des octets non listés.

## LOT42 et publication

La vérification LOT42 continue de relire son LOT41A nommé. Pour le chemin H2,
elle exige une autorisation V2 et vérifie que le `content_sha256` attesté est
présent dans l'allowlist avant `RETRIEVAL_ELIGIBLE`. Ce SHA provient de
`ingestion_control.artifacts` et de l'événement durable du checkpoint contenu,
jamais d'un argument opérateur. L'événement lie le SHA, l'identifiant, le
digest et la version de l'autorisation revérifiée. Le publisher interne ne
reçoit donc jamais un fait LOT42 fondé sur une autorité V1 large, un SHA V2 non
listé ou une affirmation libre. Aucun second chemin de promotion ni writer HTTP
n'est ajouté.

## Compilation gouvernée H2

La préparation H2 sépare la readiness pédagogique de l'autorité réelle. Une
fonction dédiée confronte chaque `eligible_artifact` de la politique de
placement à une `VerifiedAuthorization` sans jamais déduire l'autorité du seul
scope. Le résultat de cette vérification est projeté dans un contrat partagé
immuable qui porte au minimum l'identifiant, le digest, la version du protocole,
le HEAD Git revu et l'allowlist exacte. Seul le vérificateur live LOT41A produit
cette projection dans le chemin réel ; le compilateur `rag-pedago` ne reçoit ni
artefact V2 librement construit, ni ensemble de SHA opérateur, et aucun argument
CLI ne permet de fabriquer la projection. Cette frontière respecte la séparation
des services sans importer `rag-engine` dans `rag-pedago` :

- V2 et SHA présent dans `allowed_content_sha256` : clearance d'autorité ;
- même scope/domaine mais SHA absent : `REVIEW_REQUIRED`/refus ;
- V1 : refus `CONTENT_ALLOWLIST_AUTHORITY_REQUIRED` ;
- autorisation réelle absente : l'artefact reste `REVIEW_REQUIRED`.

La projection est une donnée de décision issue de la relecture Git/DB, pas une
nouvelle source d'autorité. Une divergence d'identifiant, digest, HEAD, version
ou allowlist empêche sa production avant le compilateur.

Cette fonction est utilisée par la répétition V2 et par le futur compilateur de
promotion. Avant l'approbation post-fusion de PR #96, la compilation réelle
peut donc rester à `INGEST=0` tout en prouvant que l'implémentation V2 de
staging produit un ensemble non vide et exactement borné.

## Génération de la future autorisation

Un helper H2 peut dériver la proposition V2 depuis l'intersection exacte du
catalogue scellé, des droits, de la currentness, de la preuve PII et de la
politique de placement. Il trie et valide les SHA puis sérialise le modèle V2.
Il revérifie les digests externes de la preuve PII et du manifest et refuse le
SHA de quarantaine `b81201b857c67e4e928a079cfe9d5b9b402537d0101bfccc730465631d5e8376`.
Ces entrées ne deviennent une autorité qu'après commit et revue GitHub. PR #96
n'est pas modifiée dans ce lot d'implémentation ; elle sera régénérée contre le
nouveau `main` après fusion de PR #95.

`record-authorization` continue de recevoir uniquement l'identité de
l'autorisation, le dépôt/numéro de PR et le HEAD attendu. Il n'accepte aucun
SHA, fichier de contenu ou statut PII en argument et ne reconstruit jamais une
décision : seul le blob Git revu fournit les champs V1/V2.

## Tests et preuves

Les tests couvrent la discrimination V1/V2, champ V2 manquant/vide/dupliqué/non
trié/en majuscules/malformé, champ V2 ajouté à V1, protocole inconnu, dérive des
octets canoniques et du digest, contraintes SQL et divergences DB/blob
(élargissement, réduction, substitution, réordre, changement de protocole,
digest ou blob). Ils couvrent aussi l'isolation des rôles et l'ordre du worker.

Le scénario P1 exact — même domaine, SHA absent — doit passer le contrôle de
destination, échouer au checkpoint contenu et laisser extraction, droits,
qualité, `RETRIEVAL_ELIGIBLE` et pgvector intacts. La matrice comprend aussi :

- chacun des cinq SHA autorisés ;
- mêmes octets autorisés depuis une autre URL elle-même autorisée ;
- octets différents sous une URL apparemment approuvée ;
- redirection autorisée aboutissant à des octets non listés ;
- SHA autorisé obtenu via une destination interdite, refusée avant contenu ;
- V1 appliqué à un candidat H2, qui reste `REVIEW_REQUIRED` avec
  `CONTENT_ALLOWLIST_AUTHORITY_REQUIRED`.

La matrice de mutation gagne MUT-H2B-13, qui neutralise uniquement le test
d'appartenance au contenu et exige que le test de menace devienne rouge avant
restauration octet à octet. Les migrations 004 et 009, le multi-placement, les
répétitions LOT42 V2, la CI canonique et la sécurité sont rejoués sur le HEAD
final avant l'audit indépendant.

## Rollback et révocation

La révocation live reste celle d'ADR-0032 et s'applique au nouveau checkpoint
après téléchargement. Le rollback applicatif vers une version ne comprenant
pas V2 est interdit tant qu'une ligne V2 existe. Cette condition est un arrêt
explicite à traiter par révocation/archivage gouverné, jamais une suppression de
données ou une conversion implicite vers V1.
