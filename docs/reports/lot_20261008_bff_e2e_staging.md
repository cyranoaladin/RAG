# Lot — qualification HTTP du BFF sur le staging final

Le harnais `scripts/go_live/staging_bff_e2e.py` envoie de vraies requêtes HTTP
au Cockpit, avec sessions NextAuth et identités internes signées par le
générateur de test existant. Il vérifie le refus sans session (401), le refus
hors scope avant le moteur (403), puis la recherche enseignant. Chaque passage
doit porter la collection exacte, une revue `reviewed`, une citation complète
et un identifiant de contenu présent dans les placements du sujet de la release
scellée. En mode `internal`, un élève ne doit recevoir aucun passage ; en mode
`public`, il doit recevoir des passages cités. Le mode `public` ne lève aucun
verrou et n'est utilisable qu'après la publication gouvernée des placements
publics.

Exécution depuis le checkout propre de `origin/main` **sur l'hôte staging**,
après mise en service du Cockpit final, avec les six variables d'identité
requises déjà provisionnées dans l'environnement opérateur (ne jamais les
mettre dans la ligne de commande) :

```bash
python3 scripts/go_live/staging_bff_e2e.py \
  --repository-root . \
  --cockpit-url http://127.0.0.1:18004 \
  --registry services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json \
  --registry-sha256 59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6 \
  --expected-sha "$(git rev-parse origin/main)" \
  --student-mode internal \
  --output /srv/nexus-staging/qualification/bff-e2e-internal.json
```

Changer `--student-mode public` et le chemin de sortie seulement après
autorisation, revue, scellement et publication du scope public. Passer alors
le digest du nouveau registre de release. La preuve privée (`0600`) lie
checkout, tree, registre, artefact pilote, population, statuts HTTP, citations
et identités de contenus ; elle ne conserve aucun jeton.

Limite vérifiée sur `ee35544b` : le BFF signe actuellement le pilote immuable
`libre_terminale_maths_nsi_real_v1` (maths et NSI terminale), tandis que le
registre final V4+V5 ne contient pas maths. Sa readiness agrège les deux
collections signées ; le parcours BFF risque donc un 503 avant la recherche
NSI. Le harnais signale cette incompatibilité sans la contourner. Il ne
qualifie pas onze collections : l'acceptance API v2 sur les onze reste
obligatoire. Une évolution gouvernée distincte du scope BFF est nécessaire
pour le chemin Cockpit sur le produit final, et une nouvelle release de
visibilité publique pour le succès élève.

Validation locale au SHA `ee35544bce5af74d6186ea0ef61f6902a2258ffe` :
13 tests Python du harnais, 180 tests Cockpit, Ruff, ESLint, TypeScript,
vérification des contrats et build Next.js réussis. Aucune mesure BFF live
sur le staging final n'est affirmée dans ce lot.
