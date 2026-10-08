# ADR-0062 — Coexistence par collection de V4 et du complément HGGSP

- **Statut** : Proposé — arbitrage humain option B du 2026-09-28 ; devient
  accepté après revue du HEAD exact et fusion de la PR de ce lot.
- **Date** : 2026-09-28
- **S'appuie sur** : ADR-0044, ADR-0050, ADR-0055, ADR-0059, ADR-0060 et
  ADR-0061.
- **Contrat** : aucune modification de `nexus-contracts`.

## Fait déclencheur

V4 déclare onze collections et 479 placements dans son manifeste immuable.
La reprise DI a publié les neuf collections dont le mapping de sujets est
valide : 405 placements, 263 artefacts et 5 678 chunks. Les 74 jobs HGGSP de
V4 restent en attente. Ajouter `hggsp` au mapping scellé de V4 changerait son
empreinte et ferait mentir son manifeste. Une release successeur contenant les
onze collections ferait, elle, réadopter ou republier les 405 placements déjà
validés, contrairement à l'arbitrage humain.

## Décision

1. La release `production-profile-gate-2026-2027-v5-hggsp` est un complément
   de V4. Elle contient **exactement** `rag_nexus_hggsp_premiere_specialite`
   et `rag_nexus_hggsp_terminale_specialite`. Elle porte sa propre empreinte
   du mapping de sujets additif et un motif d'évolution citant le commit qui
   contient ces octets. V4 et son mapping restent immuables.
2. Le producteur ne sélectionne cette voie que sur demande explicite :
   source V4, chemin et empreinte du mapping, deux collections et motif.
   Sans ces options, son comportement historique reste inchangé. Le nombre de
   chunks est recalculé depuis les registres scellés ; aucun entier attendu
   ne remplace cette preuve.
3. Le registre de releases `registry_version=2` attribue explicitement à
   chaque release la liste des collections qu'elle **sert**. Le chargeur
   vérifie d'abord intégralement le manifeste, son empreinte, son identité et
   ses autorités, puis projette l'attente de produit sur cette liste. Il
   refuse collection inconnue, doublon, chevauchement entre releases et
   contradiction de modèle. La version 1 continue d'exiger l'égalité entre
   la liste et le manifeste.
4. La lignée mixte de ce lot attribue les neuf collections non HGGSP à V4 et
   les deux collections HGGSP au complément. Les 405 placements V4 restent
   liés à V4 ; les 74 HGGSP seront liés à la nouvelle release. Aucun registre
   implicite ni ordre « dernière release gagnante » ne décide de cette
   propriété.
5. Ce lot n'autorise aucune opération serveur. Une autorisation de staging
   distincte, revue puis fusionnée, devra précéder readiness, scopes r4,
   revue batch, attestations, jobs et publication HGGSP. Les 74 anciens jobs
   V4 sont préservés jusqu'à vérification indépendante du successeur ; leur
   invalidation ultérieure exige une autorité distincte et une preuve de
   l'équivalence de périmètre.

## Conséquences

Le registre mixte peut servir de cible de qualification et de routage par
collection sans modifier les manifests des releases. Le basculement de
production reste interdit par les statuts de promotion et d'activation des
releases de répétition, ainsi que par l'absence d'autorisation de déploiement.
La fermeture de la revue V4 #262 reste un travail ultérieur : son contrôle de
fermeture historique attend les 479 placements de V4 et ne doit pas être
réinterprété silencieusement.
