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
et rehaché portant le rendu V4 de 200 000 pixels. `ruff`, `mypy`, la validité
du schéma JSON et `git diff --check` sont verts.
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
