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

`ScopeAuthorizationArtifact` conserve exactement le modèle LOT41A-V1 public.
Un nouveau `ScopeAuthorizationArtifactV2` porte les mêmes champs et ajoute
`allowed_content_sha256`, tuple non vide de SHA-256 minuscules, triés et
uniques. `ScopeAuthorizationArtifactV1` est fourni comme alias explicite du
modèle historique afin de rendre le dispatch lisible sans casser l'import
public existant.

Le parseur inspecte exclusivement `protocol_version`, puis valide le document
avec le modèle strict correspondant. V1 rejette le champ V2, V2 exige ce champ,
et toute version inconnue échoue. La liste apparaît dans
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

La lecture live compare la version et la liste, dans l'ordre canonique, entre
la ligne et le blob Git approuvé. Toute extension, réduction, substitution ou
réorganisation de la liste échoue. Le rollback 009 refuse explicitement de
continuer si une ligne V2 existe ; il ne supprime jamais silencieusement une
frontière de sécurité.

## Flux d'exécution

Le worker conserve les contrôles de scope et de destination avant accès
réseau. Le fetcher calcule le SHA-256 des octets reçus en mémoire bornée puis
appelle un checkpoint injecté avant toute transition `FETCHED`, tout stockage
d'artefact ou toute extraction. Le callback relit l'autorité en direct afin
qu'une révocation pendant le téléchargement prenne effet, puis appelle
`enforce_content_sha256`.

Pour V2, l'absence du SHA dans l'allowlist produit un
`ScopeEnforcementViolation(checkpoint="content")`. Pour V1, le mécanisme
historique reste utilisable hors politique H2, mais une fonction de politique
H2 exige explicitement V2 et refuse V1 avec le motif
`CONTENT_ALLOWLIST_AUTHORITY_REQUIRED`. Aucun octet refusé n'est stocké dans le
magasin durable, aucune transition de ressource n'est appliquée et aucun agent
d'extraction, droits ou qualité n'est appelé.

La destination et le contenu sont des contrôles cumulatifs : un SHA autorisé
ne sauve jamais une URL interdite, tandis qu'une URL autorisée ne sauve jamais
des octets non listés.

## LOT42 et publication

La vérification LOT42 continue de relire son LOT41A nommé. Pour le chemin H2,
elle exige une autorisation V2 et vérifie que le `content_sha256` attesté est
présent dans l'allowlist avant `RETRIEVAL_ELIGIBLE`. Le publisher interne ne
reçoit donc jamais un fait LOT42 fondé sur une autorité V1 large ou un SHA V2
non listé. Aucun second chemin de promotion ni writer HTTP n'est ajouté.

## Génération de la future autorisation

Un helper H2 peut dériver la proposition V2 depuis l'intersection exacte du
catalogue scellé, des droits, de la currentness, de la preuve PII et de la
politique de placement. Il trie et valide les SHA puis sérialise le modèle V2.
Ces entrées ne deviennent une autorité qu'après commit et revue GitHub. PR #96
n'est pas modifiée dans ce lot d'implémentation ; elle sera régénérée contre le
nouveau `main` après fusion de PR #95.

## Tests et preuves

Les tests couvrent la discrimination V1/V2, la canonicité, les contraintes SQL,
les divergences DB/blob, l'isolation des rôles et l'ordre du worker. Le scénario
P1 exact — même domaine, SHA absent — doit passer le contrôle de destination,
échouer au checkpoint contenu et laisser extraction, droits, qualité,
`RETRIEVAL_ELIGIBLE` et pgvector intacts.

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
