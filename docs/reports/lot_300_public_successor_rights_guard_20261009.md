# Lot #300 — porte des droits de la release publique successeur

Au 2026-10-09 UTC, le producteur canonique `build_production_profile_release.py`
refuse avant toute écriture une candidate portant des placements `public` si le
pack d'adjudication déléguée ne passe pas le vérificateur indépendant sur le
miroir PDF exact et le HEAD fourni. Il exige l'égalité des ensembles de SHA
entre les placements de la candidate, son registre d'artefacts et les seules
décisions `APPROVE_PUBLIC`. Il recalcule les comptes des artefacts, placements,
chunks et collections. Il vérifie aussi les SHA déclarés par l'agrégat pour le
registre et les sujets, le lien de chaque sujet au registre, le
`release-registry.json` et la topologie `(content_sha256, collection, nombre de
placements)` ainsi que les octets des listes de chunks contre les manifests
V4/V5 scellés. `officiel_public` n'est
jamais une preuve de droits.
Les candidates mêlant `internal` et `public`, réutilisant les identités V4/V5
historiques ou contenant CFTR sont refusées.

La porte s'active automatiquement quand la topologie produite en mémoire
contient au moins un placement public, y compris en `--dry-run`. Le producteur
exige alors `--student-public-rights-expected-head <SHA>` et réutilise
`--pdf-root` comme miroir du vérificateur. Les releases internes historiques
restent inchangées ; aucun manifeste V4/V5 n'a été réécrit et aucune cible
staging/production n'a été touchée.

Le pack machine ne peut produire qu'un candidat explicite `PRE_REVIEW`,
`NOT_PROMOTABLE`, `NO_PRODUCTION_ACTIVATION`. Le producteur refuse un état
activable jusqu'à l'attestation externe de la review d'autorité exacte #300 ;
une réussite du seul vérificateur documentaire ne vaut pas cette review.

Le vérificateur du pack refuse le mandat non scellé, le policy non scellé, les
315 SHA manquants ou inconnus, une ligne `PENDING`, une preuve/citation/page
absente, CFTR approuvé, une revue A/B incomplète, une feuille TSV altérée, des
comptes artificiels, une source PDF non concordante et une approbation fondée
sur `officiel_public`. Il rejoue `scan_pdf` sur chaque PDF du miroir et confronte
les preuves structurées aux octets et au code scanner. Il exige un checkout Git
propre au HEAD SHA-1 exact (40 hex) et relit tous les reçus CAS A/B de chaque
page et segment, avec leurs hachages, leur couverture et l'agrégat des
observations. Il reconstruit indépendamment `request_sha256` et
`context_sha256` depuis les octets du PDF, le texte, les rendus et l'OCR.
Le protocole d'assemblage V5 projette les valeurs XMP uniques et vérifie les
images incorporées séparément, retire seulement les lignes OCR identiques au
texte extrait, puis lie chaque page au record par `text_assembly`. Une page
graphique commence par un segment visuel court portant le SHA du rendu ; les
segments textuels suivent, bornés à 4 000 caractères. Le rendu vision est
plafonné à 150 000 pixels par une échelle déterministe au plus égale à 0,5 ;
l'OCR/scanner reste à sa résolution distincte.
Les deux classifications d'un candidat positif portent des nonces 0 et 1,
des reçus CAS distincts et des agrégats d'observation concordants. Son succès n'est pas
l'approbation terminale exacte de l'autorité, ni une autorisation de déployer.

Validation V5 : la suite combinée du lot (moteur, scanner, revues, sources,
vérificateur, porte et producteur) compte 179 tests verts, dont le test
d'intégration du `main` réel prouvant le refus avant écriture. Les 46 tests
du vérificateur couvrent le segment visuel court, les sabotages XMP/OCR, le
refus d'un reçu textuel revendiquant une inspection visuelle sans image, le
rendu borné d'une page dépassant 150 000 pixels et le refus d'un reçu modifié
et rehaché portant le rendu V4 de 200 000 pixels. `ruff`, `mypy` ciblé sur le
vérificateur, la validité du schéma JSON et `git diff --check` sont verts.
Une invocation locale de `mypy` sur les modules scanner et reviewer signale
sept erreurs de typage liées aux objets dynamiques PyMuPDF et à deux valeurs
optionnelles du reviewer ; aucun résultat `mypy` global vert n'est revendiqué.
Le smoke modèle V4 sur le PDF CAS
`85319cb509247343b082abed6012c50ebd157134fd6ce84150cf852ae4f870fb`
est rouge : le rendu de 435 × 456 pixels (198 360 pixels) provoque
`MODEL_HTTP_400`, la requête comptant 4 269 tokens pour un contexte disponible
de 4 096. Seuls 2 reçus sur 3 existent pour chacun des reviewers A et B.
Ce protocole n'est donc pas qualifié sur la page témoin. Une sonde directe à
150 000 pixels sur ce même PDF a reçu HTTP 200 et un JSON complet de neuf clés,
avec `visual_examined=true`. Le smoke CLI V5 frais a ensuite terminé sans
erreur de transport : A/B complets, trois segments et trois reçus chacun. Son
résumé structuré a pour SHA256
`af90418016a48195f901c4868e3ae9a7108182bd7e90b582afddce427379a491`.
Le gate a relu les octets du PDF exact et reconstruit le rendu 377 × 395 pixels
(148 915 pixels, deux essais), puis les six empreintes de requête/image et les
six reçus CAS : zéro divergence. Les deux observations avec image indiquent
`visual_examined=true`, les quatre sans image `false`. Les deux verdicts restent
`FAIL` avec confiance basse : ce résultat valide la concordance technique V5
sur un document, sans autoriser sa publication ni qualifier les 315 PDF.
Un smoke V3 strict historique sur un PDF CAS exact
`8eb23c91b035d968bb90019912190bb09b165dbe5ee7573d39217b142047d084`
a produit 7 segments par reviewer et 14 reçus CAS valides, sans erreur de
transport. Son résumé structuré a pour SHA256
`3b765ab51460b187652c8cebe9014f900327cec274efe970070ee01cca2fb031`.
Sur ce PDF réel, le vérificateur a reconstruit indépendamment les 14 empreintes
de requête et d'image : aucune divergence ; 4 reçus avec image revendiquent une
inspection visuelle et les 10 reçus sans image déclarent correctement
`visual_examined=false`. Les deux reviewers ont rendu `FAIL`. Ce smoke démontre
la concordance du protocole V3 pour un PDF ; il n'est pas une preuve du V4 et
ne prouve ni la véracité des observations du modèle ni 315 revues complètes.
Les 72 tests existants du producteur sont verts dans un venv temporaire avec
`pypdf==6.14.2`, version déclarée par le producteur. Le Python système porte
`pypdf==6.16.1` et fait échouer uniquement le contrôle de runtime canonique ;
le venv temporaire a été supprimé après validation.

Le contrôle source réel, exécuté à `2026-10-09T21:22:36Z` sur l'inventaire
exact de 315 PDF, a produit 315 checkpoints temporaires non versionnés. J'ai relu les
315 fichiers : leurs `content_sha256` sont uniques et égaux à l'inventaire,
leurs 315 empreintes de checkpoint sont valides, et tous portent
`inventory_sha256=4bee52a4d853aee23c86428585ebf28fa5afd3ecb82e1b3b90e1f84ed8667679`
et le SHA256 du contrôleur source
`c4918eb4e85ebe0bbb2c96f52168e795e6615fc9d37bb5911641fb09f2597d9f`.
L'identité exacte du PDF a été vérifiée pour 13 documents ; elle est
invérifiable pour 302. **Aucun** des 315 n'a de base de droits positive :
`rights_basis=NONE` pour 315, zéro reçu positif, actualité et révocation
invérifiables pour 315. Les motifs sont `SOURCE_IDENTITY_NOT_PROVEN` pour 302
et `OFFICIAL_TERMS_UNVERIFIABLE` pour 13. Une identité PDF concordante ne
constitue pas une autorisation de recherche publique étudiante. Ces
checkpoints locaux sont un diagnostic daté, pas le pack de preuves final.
Une sonde HTTPS GET distincte, sans redirection, sur la notice légale Éduscol
`https://eduscol.education.gouv.fr/4656/mentions-legales`, a reçu HTTP 403 à
`2026-10-09T21:28:51.166359Z` ; l'URL finale était identique. Ce résultat
réseau ponctuel ne change aucun des 315 verdicts de droits.

À cette étape le pack final n'existe pas encore : le gate réel répond
`INDEX_MISSING`, donc aucune release publique n'est émise. Après la review
exacte de #300, la nouvelle release devra encore porter une autorité de
publication vérifiable sur son digest propre ; ce garde technique ne remplace
pas la signature de release, les tests staging, ni le cutover humain. Les
reçus CAS lient les observations à des empreintes de requêtes sans persister
le texte ou les images des PDF ; ces empreintes sont recalculées par le gate.
Les reçus ne sont toutefois pas une attestation cryptographique indépendante
de l'exécution du modèle. Un reçu source CAS et un nouveau téléchargement
indépendant des octets PDF/termes/licence ne prouvent pas, à eux seuls,
l'actualité et l'absence de révocation d'un document : toute décision
`APPROVE_PUBLIC` reste rouge (`APPROVAL_SOURCE_PROOF_UNVERIFIABLE`) tant que
ces deux preuves distinctes ne sont pas disponibles. Aucun compte public
positif ne peut donc être annoncé à cette étape.

Le scanner exact a terminé les 315/315 PDF sur 3 509 pages, sans erreur,
avec 315 checkpoints locaux et `full_document_scan_complete=true` pour chacun.
Le protocole A/B V5 a ensuite été gelé : `granite3.2-vision:2b` au digest
`sha256:3be41a661804ad72cd08269816c5a145f1df6479ad07e2b3a7e29dba575d2669`,
température 0, graine 17, contexte 4 096, sortie maximale 320. Sur le PDF
témoin problématique, le CLI a terminé A et B (3/3 segments chacun) et le
vérificateur indépendant a reconstruit les 6/6 reçus CAS. La suite ciblée du
lot après scellement compte 178 tests verts ; Ruff et `git diff --check` sont
verts. Le mandat et la politique portent `SEALED_PENDING_FINAL_APPROVAL` avec
`effective_authority=false`. La revue A/B des 315 PDF a été lancée avec reprise
par artefact ; aucune décision finale ni feuille TSV n'est encore produite.

La CI du HEAD précédent a échoué dans trois jobs Docker, dont C5, à cause du
quota de pull non authentifié de Docker Hub sur l'image pgvector. Sur le HEAD
scellé `ec8bb49fb386275072e38a192626edf8f34e10d8`, la CI standard est
finalement verte, C5 et les autres jobs Docker compris. Seul le statut de
review humaine exact-HEAD reste rouge de façon attendue, puisque le challenge
terminal n'est pas encore demandé.

## Décision de pilotage du 2026-10-10 — autorité sitewide et dérivés textuels

L'autorité `abenrhouma` a changé le protocole de ce lot alors que #300 est encore
draft. Le diagnostic ancien `rights_basis=NONE` sur 315/315 et le `HTTP 403`
consigné ci-dessus décrivent les limites du contrôleur individuel et du client
Python, **pas** un verdict juridique d'absence de licence. Le batch de revues
A/B complètes des PDF source a été arrêté au 48e checkpoint individuel ;
les 48 résumés et 2 970 reçus CAS restent conservés, mais ils ne constituent pas le
pack final. Le scan structurel intégral des 315 PDF et 3 509 pages reste un
signal d'entrée valide sur ces octets exacts.

À `2026-10-10T05:33:18.840Z`, Chromium 145.0.7632.6 et Playwright 1.58.2
ont obtenu `HTTP 200` sur les [mentions légales Éduscol](https://eduscol.education.gouv.fr/4656/mentions-legales), URL finale identique. À
`2026-10-10T05:33:20.288Z`, le même outil a obtenu `HTTP 200` sur la
[Licence Ouverte Etalab 2.0](https://www.data.gouv.fr/pages/legal/licences/etalab-2.0). Les deux HTML normalisés, textes extraits, captures plein écran,
horodatages, URLs et empreintes sont consignés dans
`docs/reports/go_live/student_rights_evidence/authorities/` et liés par
`governance/student_public_rights/authorities/eduscol_etalab_2_0_sitewide_20261010.yml`.
Les mentions couvrent les pages et documents téléchargeables du site, mais
excluent les éléments illustratifs, textuels et sonores tiers ; la licence
exige attribution de la source et de la dernière mise à jour, sans prétention
d'agrément officiel. Ce constat n'établit **pas** à lui seul le lien de chaque
SHA PDF local avec un téléchargement Éduscol.

La nouvelle politique 1.1.0 et ADR-0068 demandent donc : preuve individuelle
d'acquisition courante ou snapshot officiel daté ; PDF source `internal` ;
dérivé `text/plain` à SHA distinct ; exclusion déterministe des composants
non textuels, OCR graphiques, segments tiers, enseignant seul et PII ;
revue A/B ciblée seulement si une réintégration de segment suspect était
proposée, ce qui n'est pas autorisé dans ce lot ; attribution complète ; feuille
315 sources sans PENDING ; contrôle indépendant et dix sabotages. CFTR reste
`EXCLUDE` page 3 et ne produit pas de dérivé. Aucune release publique, ni
staging ni production, n'est modifiée dans ce lot.

Au moment de cette note, l'autorité globale est capturée mais les 315 preuves
de provenance, les dérivés, la feuille finale, les onze populations publiques
et le challenge exact-HEAD ne sont **pas encore établis**. L'autorité capturée
porte `SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL` et #300 doit rester draft. Les
comptes V4/V5 de répétition ne sont pas des comptes de release publique.

### Rejeu de provenance du 10 octobre, après redécouverte des URL PDF directes

Le contrôleur nouveau a recapturé 15 pages Éduscol avec Chromium (`HTTP 200`)
et contrôlé 383 URL PDF distinctes. Sur les **315** SHA de l'inventaire figé,
**296** ont une ancre de téléchargement dans une page capturée et un GET PDF
dont le SHA concorde ; **19** restent `SOURCE_UNPROVEN` et sont exclus par
défaut. Les 13 URL d'acquisition directement PDF ont été rapprochées d'une
page Éduscol actuelle sans changer leur URL historique dans l'inventaire.
Les programmes DGEMC terminale et NSI première/terminale, déjà présents
parmi ces 315 PDF, ont ainsi une provenance candidate exacte. Il ne s'agit
ni de nouveaux artefacts, ni d'une preuve que chaque passage du PDF relève
des droits du ministère.

Les 315 checkpoints et les 15 captures courantes sont indexés sous
`docs/reports/go_live/student_rights_evidence/provenance/` ; le premier jeu
de constats est conservé séparément sous
`docs/reports/go_live/student_rights_evidence/provenance_archive_v1_20261010/`.
Le bilan propre aux sources est
`docs/reports/go_live/student_rights_evidence/provenance/source_provenance_bilan_20261010.md`.
Les 48 résumés de revue antérieurs, leurs 2 970 reçus et la première
provenance sont préservés sans les confondre avec le pack courant dans
`docs/reports/go_live/student_rights_evidence/historical_pre_sitewide_evidence_20261010.tar.zst`
(17 015 522 octets, SHA-256
`c55bd6d957f569743e66b51015a459763716e2da14442b7f1f7eacafccd0942c`,
4 036 entrées d'archive). Les répertoires originaux demeurent localement.
Le `HTTP 403` de l'ancien client figure toujours comme diagnostic de transport,
non comme absence de licence. Ce rejeu a passé 38 tests ciblés, Ruff et la
vérification des empreintes ; le différentiel indépendant a reconstruit les
315 constats depuis les PDF miroir exacts. Le gate final doit encore faire
ses GET HTTPS réels sur chaque dérivé proposé. Les dérivés textuels et leurs
comptes publics ne sont pas établis au moment de cette note.

### Projection privée des décisions sur les 315 sources

Après ce rejeu, le générateur privé a produit un reçu CAS et un checkpoint
pour chacun des **315** PDF. Les décisions déterministes de la feuille
générée sont **253** `source_disposition=REPLACE_WITH_NEW_CONTENT` avec
`derivative_disposition=APPROVE_PUBLIC` candidat, et **62** `EXCLUDE` ; il n'y
a aucun `PENDING`. Les exclusions se décomposent en 19 provenances non
prouvées, 42 PDF sans bloc textuel natif admissible et le CFTR imposé
`EXCLUDE` (page 3). Les 253 fichiers texte dérivés ont des SHA distincts des
PDF, restent privés et portent `publication_authorized=false` dans leurs
reçus ; aucun original PDF n'est déclaré public.

Le manifeste **candidat**, qui ne vaut pas release, couvre les 11 collections,
253 artefacts textuels, 377 placements et 2 504 groupes textuels ; il ne
reprend aucun compte de chunks des anciennes releases. Les 19 388 blocs
sélectionnés ont chacun leur citation ; le batch signale zéro citation ou
attribution manquante et zéro image, rendu ou OCR graphique copié. Le
vérificateur indépendant a reconstruit les 315 reçus CAS, les 253 dérivés
octet par octet depuis les PDF exacts, la feuille et les comptes du manifeste,
sans erreur dans ce rejeu **hors réseau**. Le gate complet, ses GET HTTPS
réels, les sabotages, la CI et la review d'autorité exact-HEAD demeurent
distincts avant qu'une approbation publique puisse être revendiquée.
