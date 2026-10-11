# Lot — reprise de la fenêtre de revue LOT41A publique

Date d'observation UTC : 2026-10-11. Base de cette PR : `origin/main=63330331d56da78c7f418e5d228bf9170fdda938` (arbre `d109431eefabdf306b992646b00e056c7651611a`). Ce rapport ouvre une nouvelle fenêtre de revue ; il ne crée aucune autorisation et ne modifie aucun des onze artefacts métier.

## Événement et état vérifié

La PR #329, approuvée sur le HEAD `7162b7e8d0a4a4872c05996610cf5bfdfb82c187`, a été fusionnée à `2026-10-11T17:47:03Z` pendant l'enregistrement séquentiel des autorisations dans la **nouvelle** cible de qualification publique. `authorize_scope_cli record-authorization` a correctement refusé l'identifiant suivant avec `reason=pull_request_not_open` ; les tentatives ont été arrêtées. La fusion n'est pas annulée et aucun contournement du vérificateur n'est proposé.

Les onze fichiers `governance/authorizations/lot41a-student-public-*-v1.json` du nouveau `main` sont identiques octet pour octet aux onze fichiers de #329. Ils ne contiennent ni numéro de PR ni identité de reviewer : la preuve de revue est créée lors de l'enregistrement, à partir de la PR vivante et du blob Git exact. Ce protocole de reprise a déjà été décrit dans `docs/reports/lot_go_live_ch5_register_lot41a_authorizations_before_merge.md` ; ce lot l'applique sans nouvelle mécanique ni élargissement des droits.

Lecture directe de la cible dédiée `nexus-public-qual-20261011`, base `ragdb_student_public_qual`, identifiant PostgreSQL `7695463567278473254`, conteneur Docker `5fe53fb652d8876d4e0701f58a7fdb0b145c93ae733d0e80ad2a89adce19131e` : schéma RAG 006, schéma `ingestion_control` 020, **6 autorisations présentes**, aucune révoquée. Le rôle `ingestion_control_authority` peut insérer ; le rôle worker ne le peut pas. Les six lignes ont été comparées aux SHA-256 des artefacts de #329 ; leur preuve de revue scellée se parse, redérive son challenge et concorde avec son digest, la PR #329, la review `5484158645`, la base et le HEAD approuvés. Une sauvegarde lisible de la cible neuve avant ces écritures a pour SHA-256 `46c119be8ad643865d1826041cae8426ae112dbef29d60ac0697887367b453df`. La comparaison d'inventaire Docker n'a relevé aucun service ou volume étranger touché.

Déjà enregistrés :

- `lot41a-student-public-dgemc-terminale-option-v1`
- `lot41a-student-public-hggsp-premiere-specialite-v1`
- `lot41a-student-public-hggsp-terminale-specialite-v1`
- `lot41a-student-public-hlp-premiere-specialite-v1`
- `lot41a-student-public-hlp-terminale-specialite-v1`
- `lot41a-student-public-nsi-premiere-specialite-v1`

Restent à enregistrer, sans créer de doublon ni modifier les six premières lignes :

- `lot41a-student-public-nsi-terminale-specialite-v1`
- `lot41a-student-public-ses-premiere-specialite-v1`
- `lot41a-student-public-ses-terminale-specialite-v1`
- `lot41a-student-public-svt-premiere-specialite-v1`
- `lot41a-student-public-svt-terminale-specialite-v1`

## Condition de reprise et de fermeture

Cette PR doit rester **OPEN** après une review `APPROVED` de `abenrhouma` sur sa base, son HEAD et son challenge exacts et après succès du contexte requis `trusted-human-review/head-pinned`. Pour chacun des cinq identifiants absents, l'opérateur emploie exclusivement le CLI canonique `record-authorization` avec `--pull-request` égal au numéro de cette PR, `--expected-head` égal à son HEAD approuvé, et le DSN du seul rôle `ingestion_control_authority` de la cible publique qualifiée. Le CLI relit chaque fois la review vivante et le blob canonique ; aucun fichier local passé librement ne décide du contenu.

Après les cinq écritures, une lecture indépendante doit exiger exactement onze identifiants, les onze digests d'artefacts, les onze preuves de review scellées et valides (six de #329, cinq de cette PR), aucune révocation, aucun surplus, **253 contenus distincts et 377 liaisons de scope**. La fusion de cette PR n'est autorisée qu'après ce contrôle de fermeture. Une erreur ou un changement de HEAD/base arrête les écritures ; elle ne justifie ni `ON CONFLICT`, ni relecture d'une PR fermée comme si elle était ouverte.

Les onze autorisations portent `valid_until=2026-10-12T13:58:41.752Z`. Leur enregistrement ne prolonge pas cette durée : toute phase ultérieure après cette échéance nécessitera une nouvelle ancre d'actualité et de nouvelles autorisations gouvernées. Cette PR ne lance aucun job, transfert, ingestion, publication, exposition étudiante ou déploiement production. `GO_LIVE_READY=false` et `RAG_PRODUCTION_DEPLOYED=false` à cette observation.
