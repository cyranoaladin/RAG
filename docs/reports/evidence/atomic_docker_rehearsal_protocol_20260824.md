# Description de l'observation — rehearsal Docker synthétique du 24 août 2026

## Nature de la preuve

Le rehearsal porte sur une fixture synthétique signée V1. Les fichiers
effectivement consommés sont vérifiés byte-identical à l'intérieur de chaque
bundle par leurs SHA-256 et par le manifeste du bundle. Cette preuve valide le
chemin V1 de la fixture uniquement. Elle ne prouve ni le protocole readiness V2,
ni les vrais fichiers de release, ni les futures images de production. En
l'absence du harnais et d'un transcript versionnés, son statut pour la release
V2 reste explicitement `UNVERIFIED`.

Le résultat canonique est
`docs/reports/evidence/atomic_docker_rehearsal_20260824.json`. Le SHA-256 du
harnais temporaire observé était
`b4e1ca4330fca43f0ea4fcd8fd162c777f8d5dd8d8fea09084c4c549b418e037`.

## Exigences d'un futur harnais reproductible V2

1. Créer un répertoire temporaire privé en mode `0700`, hors des répertoires
   de production.
2. Générer en mémoire une clé Ed25519 éphémère réservée à la fixture. Ne jamais
   l'écrire dans Git, le bundle, les logs ou un fichier persistant ; ne fournir
   au vérificateur que son ancre publique durant le processus.
3. Choisir un `COMPOSE_PROJECT_NAME` unique préfixé
   `nexus-go-live-rehearsal-` et refuser explicitement le nom de projet de
   production.
4. Construire trois bundles V2 : un bundle valide, un bundle dont un
   fichier Compose est altéré après calcul du manifeste, et un bundle signé
   dont le digest Compose déclaré est faux.
5. Résoudre Compose, canonicaliser ses octets, calculer les SHA-256 de chaque
   fichier, signer le readiness manifest V2 et lier tous ces digests dans le
   manifeste de bundle.
6. Photographier les conteneurs déjà actifs par identifiant, heure de
   démarrage, projet et service.
7. Exécuter les vérifications des deux bundles invalides sans mutation Docker ;
   elles doivent refuser respectivement le mauvais digest et le mauvais
   readiness manifest.
8. Déployer le seul bundle valide avec la CLI vérifiée, attendre que ses deux
   services synthétiques soient healthy, puis comparer la photographie Docker.
   Aucun service étranger ne doit avoir disparu ou redémarré.
9. Exécuter `docker compose down --timeout 10` uniquement avec les trois fichiers
   Compose et l'env-file de la fixture. `--remove-orphans` n'est jamais utilisé.
10. Refaire la photographie, exiger zéro conteneur de fixture restant et zéro
    changement sur les services étrangers, puis écrire le JSON canonique trié.

## Limite de reproductibilité

Le harnais temporaire original n'est pas archivé : il contenait un chemin
machine absolu et une graine privée de test déterministe, incompatibles avec
les règles de versionnement. La présente description en conserve les opérations
et le SHA-256 de provenance sans persister la clé, mais elle n'est ni un harnais
exécutable ni un transcript horodaté. L'artefact JSON conserve l'observation V1
originale sous `synthetic_v1_observation` et publie séparément les verdicts V2 à
`null`. Un nouveau rehearsal de la vraie release reste obligatoire après freeze
des images et manifests.
