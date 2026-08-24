# Protocole reproductible — rehearsal Docker atomique du 24 août 2026

## Nature de la preuve

Le rehearsal porte sur une fixture synthétique signée V1. Les fichiers
effectivement consommés sont vérifiés byte-identical à l'intérieur de chaque
bundle par leurs SHA-256 et par le manifeste du bundle. Cette preuve valide le
chemin de vérification et la mécanique atomique Docker ; elle ne prétend pas
que la fixture est la future release de production, ni que ses digests sont
ceux des futures images de production.

Le résultat canonique est
`docs/reports/evidence/atomic_docker_rehearsal_20260824.json`. Le SHA-256 du
harnais temporaire observé était
`b4e1ca4330fca43f0ea4fcd8fd162c777f8d5dd8d8fea09084c4c549b418e037`.

## Reproduction sûre

1. Créer un répertoire temporaire privé en mode `0700`, hors des répertoires
   de production.
2. Générer en mémoire une clé Ed25519 éphémère réservée à la fixture. Ne jamais
   l'écrire dans Git, le bundle, les logs ou un fichier persistant ; ne fournir
   au vérificateur que son ancre publique durant le processus.
3. Choisir un `COMPOSE_PROJECT_NAME` unique préfixé
   `nexus-go-live-rehearsal-` et refuser explicitement le nom de projet de
   production.
4. Construire trois bundles synthétiques : un bundle valide, un bundle dont un
   fichier Compose est altéré après calcul du manifeste, et un bundle signé
   dont le digest Compose déclaré est faux.
5. Résoudre Compose, canonicaliser ses octets, calculer les SHA-256 de chaque
   fichier, signer le readiness manifest V1 et lier tous ces digests dans le
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
les règles de versionnement. Le présent protocole en conserve les opérations et
le SHA-256 de provenance sans persister la clé. L'artefact JSON est la copie
byte-identical du résultat produit ; il n'est pas un transcript horodaté des
commandes Docker et ne remplace pas le rehearsal de la vraie release après
freeze des images et manifests.
