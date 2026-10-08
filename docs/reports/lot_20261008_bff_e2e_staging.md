# Lot — qualification HTTP du BFF sur le staging final

Le harnais `scripts/go_live/staging_bff_e2e.py` envoie de vraies requêtes HTTP
au Cockpit, avec sessions NextAuth et identités internes signées par le
générateur de test existant. Il vérifie le refus sans session (401), le refus
hors scope avant le moteur (403), puis la recherche enseignant. Chaque passage
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
  --student-mode internal \
  --output "$NEXUS_QUALIFICATION_DIR/bff-e2e-internal.json"
```

Changer `--student-mode public` et le chemin de sortie seulement après
autorisation, revue, scellement et publication du scope public. Passer alors
le digest du nouveau registre de release. La preuve privée (`0600`) lie
checkout, tree, HEAD distant interrogé en direct, registre, artefact pilote,
population, statuts HTTP, citations, identité des placements et identifiant
de l'opérateur ; elle ne conserve aucun jeton. Le Cockpit doit exposer dans
`/api/health` le SHA de build exact de ce checkout. Un serveur déployé depuis
un autre build ou une redirection HTTP fait échouer l'épreuve avant usage des
sessions signées. L'URL est limitée à une origine loopback sans identifiants.

Limite vérifiée sur `6f33805` : le BFF signe actuellement le pilote immuable
`libre_terminale_maths_nsi_real_v1` (maths et NSI terminale), tandis que le
registre final V4+V5 ne contient pas maths. Sa readiness agrège les deux
collections signées ; le parcours BFF risque donc un 503 avant la recherche
NSI. Le harnais **échoue avant toute requête** quand le scope signé n'a pas
exactement les collections du registre final. Il ne
qualifie pas onze collections : l'acceptance API v2 sur les onze reste
obligatoire. Une évolution gouvernée distincte du scope BFF est nécessaire
pour le chemin Cockpit sur le produit final, et une nouvelle release de
visibilité publique pour le succès élève.

Validation locale au SHA `6f33805601bdd04b9b10b3ae75febf01c63773e2` :
18 tests Python du harnais, 180 tests Cockpit, Ruff, ESLint, TypeScript,
vérification des contrats et build Next.js réussis. Aucune mesure BFF live
sur le staging final n'est affirmée dans ce lot.
