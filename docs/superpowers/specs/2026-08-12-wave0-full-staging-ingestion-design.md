# Full Wave 0 — ingestion staging exacte et release gouvernée

## Statut et périmètre

Conception approuvée par l'instruction Nexus Réussite du 12 août 2026. La
base est le HEAD `d3190b2ffcaf9746686731a5dfcad9b5bd883cce`; la PR #95 reste
Draft. Le Search-Ready Wave 0 existant est conservé.

Le périmètre est calculé depuis le catalogue H2-E scellé, jamais depuis une
liste Python : PDF Éduscol dont le placement est exactement `level=3e` et dont
la matière est `mathematiques`, son alias fermé `maths`, ou `francais`. Le calcul exhaustif du catalogue
scellé donne deux artefacts uniques et deux placements : un par matière. Les
ressources `cycle-4`, multi-niveaux ou non classées restent hors release. Cette
égalité avec les deux pilotes historiques est un résultat d'inventaire, pas une
exception du runtime.

## Autorité release data-driven

Un inventaire candidat déterministe contient les métadonnées physiques et
pédagogiques des deux placements, les compteurs par matière et les digests du
catalogue et du manifest corpus. Il ne contient aucun octet PDF.

La currentness V1 pilote reste immuable. Une preuve V2 lie exactement son set
d'artefacts à l'inventaire candidat et porte les preuves officielles de
currentness pour 2026-2027. Un mapping YAML fermé traduit les types document
externes réellement observés vers `TypeDoc`; toute valeur inconnue est refusée.

Le resolver charge et vérifie au démarrage : catalogue, inventaire candidat,
currentness V2, manifest release matière, mapping fermé, index programme,
profils et catalogue collections. Il exige l'appartenance exacte au release
set éligible et l'égalité de chaque fait avec le catalogue. Niveau, voie,
matière et collection sont dérivés par égalités fermées entre inventaire,
profil et catalogue collections (`3e→troisieme`, `college/*→college`, alias
`mathematiques→maths`) ; le manifest ne peut donc pas s'auto-attester. Aucun SHA métier
n'est présent dans le code runtime. Les SHA des pilotes ne restent que dans les
preuves, manifests et fixtures.

Le resolver sélectionne un placement par son `source_placement_id` exact. Un
artefact peut avoir plusieurs placements gouvernés; les chunks restent liés au
SHA unique et ne sont jamais dupliqués par placement.

## Gates et manifests

Chaque artefact candidat reçoit un résultat nommé pour currentness, droits,
PII, extraction, placement, conformité et chunking. Le calcul continue après
un échec isolé. Un artefact est release-eligible seulement si tous les gates
sont positifs; le bilan vérifie `candidate = eligible + noneligible` sans trou.

Le scan PII cible une fois chaque SHA unique avec la policy H2-B v5 et produit
une nouvelle preuve immuable portant explicitement `candidate_inventory_sha256`,
`corpus_manifest_sha256`, `policy_sha256` et `scanner_sha256`. Les preuves de
droits utilisent uniquement le chemin physique scellé. L'extraction utilise
`extract_pdf_pages`; le chunking utilise le provider E5 vérifié et exige
couverture page complète, métadonnées non nulles et zéro passage hors limite.

Les manifests Maths, Français et agrégé portent les digests de toutes les
autorités, l'identité des modèles, les profils et les sets attendus. Pour chaque
artefact ils fixent pages, placements, nombre et identités de chunks ainsi que
les digests des sets de textes/pages. Les sets sont canoniques (tri lexical,
JSON compact UTF-8, doublons refusés) et le réconciliateur recalcule identités,
SHA et pages depuis les octets/chunks plutôt que de croire les compteurs. Aucun vecteur ni contenu brut n'est
versionné.

Les modèles sont strictement épinglés à E5
`e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a`
et au reranker
`bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1`.

## Batch gouverné et réconciliation

Une base PostgreSQL/pgvector staging propre reçoit exclusivement les deux
artefacts du release set. Deux autorisations LOT41A étroites portent exactement
les sets de SHA de leur manifest matière. Worker A traverse toutes les
transitions jusqu'à `NEEDS_REVIEW`; LOT42 produit les attestations staging;
Worker B revalide le même resolver puis publie avec le provider E5 réel.

La réconciliation compare les sets complets artefacts, placements et chunks à
leurs manifests, y compris SHA, pages, modèle et pins de gouvernance. Le batch
complet est rejoué : aucune création, duplication ou inférence nouvelle n'est
permise au second passage.

Les scénarios Phase B crash après eligibility, crash après commit produit,
expiration de lease et retry sont testés après le premier passage réussi.

## Runtime et readiness

Les deux CLIs chargent toutes les preuves et construisent une seule instance du
resolver avant toute connexion de travail. Un worker publiable sans resolver ou
avec digest divergent échoue au startup. La CLI Worker B ne réclame que les jobs
`publication_resume` et utilise le provider E5 attesté; aucun public writer
n'est introduit.

Un validateur de readiness charge le manifest agrégé ancré par SHA et compare
exhaustivement la base : artefacts, placements actifs/reviewed/current, chunks,
pages et modèle. L'absence, un drift ou une ligne inattendue rend la collection
non prête. `/collections/readiness` consomme ce résultat au lieu d'un booléen
constant. Le même résultat bloque `search`, `chat` et le picker pour les deux
collections release : `instanciee=true` seul ne suffit jamais à rendre une DB
partielle interrogeable.

Le catalogue canonique n'active les deux collections qu'après une
réconciliation réelle verte. Les autres entrées restent bit-for-bit inchangées.

## Search, livraison et limites

L'acceptance HTTP existante est relancée puis étendue à vingt requêtes par
matière. Comme le filtre exact-grade ne contient qu'un artefact par matière,
les probes couvrent plusieurs pages/concepts de chacun; la discoverability est
mesurée sur 1/1 artefact par collection. L'isolation de scope reste stricte.
La consigne « plusieurs artefacts par matière » est donc mathématiquement
inapplicable sans élargir illégitimement le scope aux ressources `cycle-4`.

Le rapport de lot consigne l'inventaire exhaustif, les gates, manifests,
comptages DB, idempotence, reprise, CLIs, readiness et search. Les deux findings
GitGuardian historiques sont seulement signalés pour dismissal humain; aucune
réécriture d'historique n'est autorisée. La PR reste Draft.
