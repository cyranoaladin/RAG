# Lot — qualification HTTP du BFF sur le staging final

Le harnais `scripts/go_live/staging_bff_e2e.py` est préparé pour envoyer de
vraies requêtes HTTP au Cockpit, avec sessions NextAuth et identités internes
signées par le générateur de test existant. Il exige d'abord que les onze scopes
BFF V2 projetés correspondent un pour un aux onze collections du registre
V4+V5 et aux artefacts gouvernés de `packages/contracts`. Il sélectionne
ensuite le profil, la matière, le niveau et le scope signé de la collection
demandée. Il vérifie le refus sans session (401), le refus hors scope avant le
moteur (403), puis la recherche enseignant. Chaque passage
doit porter la collection exacte, une revue `reviewed`, une citation complète,
un chunk et un placement exacts du sujet de la release scellée. L'URI, le
libellé et la page citée sont rapprochés de l'artefact et du chunk scellés.
En mode `internal`, un élève ne doit recevoir aucun passage ; en mode
`public`, il doit recevoir des passages cités. Le mode `public` ne lève aucun
verrou et n'est utilisable qu'après la publication gouvernée des placements
publics.

Exécution depuis le checkout propre de `origin/main` **sur l'hôte staging**,
après mise en service du Cockpit final, avec les six variables d'identité
requises déjà provisionnées dans l'environnement opérateur (ne jamais les
mettre dans la ligne de commande) :

```bash
git fetch origin main
python3 scripts/go_live/staging_bff_e2e.py \
  --repository-root . \
  --cockpit-url http://127.0.0.1:18004 \
  --registry services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json \
  --registry-sha256 59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6 \
  --expected-sha "$(git rev-parse origin/main)" \
  --operator-id "$USER" \
  --collection rag_nexus_nsi_terminale_specialite \
  --student-mode internal \
  --output "$NEXUS_QUALIFICATION_DIR/bff-e2e-internal.json"
```

Changer `--student-mode public` et le chemin de sortie seulement après
autorisation, revue, scellement et publication du scope public. Passer alors
le digest du nouveau registre de release. La preuve privée (`0600`) lie
checkout, tree, HEAD distant interrogé en direct, registre, scope final,
population, statuts HTTP, citations, identité des placements et identifiant
de l'opérateur ; elle ne conserve aucun jeton. Le Cockpit doit exposer dans
`/api/health` le SHA de build exact de ce checkout. Un serveur déployé depuis
un autre build ou une redirection HTTP fait échouer l'épreuve avant usage des
sessions signées. L'URL est limitée à une origine loopback sans identifiants.

Le `main` au moment de cette préparation signe encore le pilote immuable
`libre_terminale_maths_nsi_real_v1`, qui contient une collection maths absente
de V4+V5. Le harnais échoue donc avant toute requête tant que la PR #294,
qui projette les onze scopes finaux, n'est pas intégrée et déployée sur staging.
Une exécution du harnais cible une collection et prouve le chemin BFF réel
pour celle-ci ; elle ne remplace pas l'acceptance API v2 des onze collections.
La réussite élève exige toujours une publication publique gouvernée distincte.

Base relue : `origin/main=1ab971838e90c876bf185da03b67423f9f0a32c9`.
Le code a été vérifié dans un worktree détaché propre au commit
`fae819760a8da14d7a88b12fa515fb3c7fc31f78`, tree
`9daa3bc153aeadb962e4fff83209ceaa9b693664`, avec un venv dédié :
`python -m pytest -q scripts/tests/test_staging_bff_e2e.py` donne `21 passed` ;
`ruff check scripts/go_live/staging_bff_e2e.py
scripts/tests/test_staging_bff_e2e.py` donne `All checks passed`. La projection
de travail de #294, lue sans la modifier, contient bien onze scopes : le digest
canonique du scope NSI terminale calculé par le harnais est
`dd6eeafd7749b9cd7f3084fec826707100756f330005a68f385d0dada1979b2d`,
égal à celui annoncé par #294. Cette lecture locale ne constitue pas une
qualification BFF live. Aucun trafic staging n'a été lancé pendant la sonde
dense. Les contrôles Cockpit et le harnais seront rejoués au HEAD final de
cette PR et après l'intégration de #294.
