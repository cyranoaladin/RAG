# Lot — reprise de la fenêtre de revue LOT41A publique

Date d'observation UTC : 2026-10-11. Base de cette PR : `origin/main=63330331d56da78c7f418e5d228bf9170fdda938` (arbre `d109431eefabdf306b992646b00e056c7651611a`). Ce rapport ouvre une nouvelle fenêtre de revue ; il ne crée aucune autorisation et ne modifie aucun des onze artefacts métier.

## Événement et état vérifié

La PR #329, approuvée sur le HEAD `7162b7e8d0a4a4872c05996610cf5bfdfb82c187`, a été fusionnée à `2026-10-11T17:47:03Z` pendant l'enregistrement séquentiel des autorisations dans la **nouvelle** cible de qualification publique. `authorize_scope_cli record-authorization` a correctement refusé l'identifiant suivant avec `reason=pull_request_not_open` ; les tentatives ont été arrêtées. La fusion n'est pas annulée et aucun contournement du vérificateur n'est proposé.

Les onze fichiers `governance/authorizations/lot41a-student-public-*-v1.json` du nouveau `main` sont identiques octet pour octet aux onze fichiers de #329. Ils ne contiennent ni numéro de PR ni identité de reviewer : la preuve de revue est créée lors de l'enregistrement, à partir de la PR vivante et du blob Git exact. Ce protocole de reprise a déjà été décrit dans `docs/reports/lot_go_live_ch5_register_lot41a_authorizations_before_merge.md` ; ce lot l'applique sans nouvelle mécanique d'autorisation ni élargissement des droits.

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

## Pin de la cible publique et correction bornée

La cible neuve possède désormais un répertoire de transfert distinct, `servable-text`, en mode 0700. La capture du pin canonique avait refusé la cible : `inet_server_addr()::text` produit `192.168.0.2/32` sur ce PostgreSQL, tandis que Docker expose `192.168.0.2`. Le socket pair `127.0.0.1:15436`, l'IP du conteneur et le port publié concordaient ; seule la comparaison textuelle du masque échouait. Le correctif minimal remplace cette expression SQL par `pg_catalog.host(pg_catalog.inet_server_addr())`, qui rend l'adresse sans masque. Il ne relâche aucun contrôle de conteneur, de socket, de chemin, de base ou de review.

Le test du contrat SQL a d'abord échoué sur le code parent, puis les **41 tests** du pin et Ruff ciblé ont passé après ce seul correctif. Sur la vraie cible, `host(inet_server_addr())` a rendu `192.168.0.2` et la capture a produit le pin canonique `governance/staging_target_pins/student-public-successor-20261011.json`, SHA-256 `6d8b5033a57b0a8d0f3d72e357a229f0c1ffc4d2ed05d1da4745d8ddc49bb45c`. Le script employé a pour SHA-256 `4451add6d77a607a1b06f24c2052ef81b689c27e5986c84a917cf20bfa66f1b4`. Le pin lie la release `student-public-successor-20261010-fcc84331e7700042`, l'ancre A `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`, le conteneur et l'identifiant PostgreSQL ci-dessus, ainsi que l'identité physique du répertoire. Il expire le `2026-10-12T13:09:56.239853Z`, avant A.

Cette capture est **non approuvée**. Le pin ne délivrera un digest utilisable qu'après une review GitHub exacte de cette PR contenant son blob, puis une nouvelle observation indépendante de la même cible par `independent_staging_target_pin.py verify`. Aucun texte n'a été transféré.

## Condition de reprise et de fermeture

Cette PR doit rester **OPEN** après une review `APPROVED` de `abenrhouma` sur sa base, son HEAD et son challenge exacts et après succès du contexte requis `trusted-human-review/head-pinned`. Le vérificateur du pin doit d'abord relire la review et la cible sur l'hôte et rendre le digest attendu. Pour chacun des cinq identifiants absents, l'opérateur emploie exclusivement le CLI canonique `record-authorization` avec `--pull-request` égal au numéro de cette PR, `--expected-head` égal à son HEAD approuvé, et le DSN du seul rôle `ingestion_control_authority` de la cible publique qualifiée. Le CLI relit chaque fois la review vivante et le blob canonique ; aucun fichier local passé librement ne décide du contenu.

Après les cinq écritures, une lecture indépendante doit exiger exactement onze identifiants, les onze digests d'artefacts, les onze preuves de review scellées et valides (six de #329, cinq de cette PR), aucune révocation, aucun surplus, **253 contenus distincts et 377 liaisons de scope**. La fusion de cette PR n'est autorisée qu'après ce contrôle de fermeture et la vérification live du pin. Une erreur ou un changement de HEAD/base arrête les écritures ; elle ne justifie ni `ON CONFLICT`, ni relecture d'une PR fermée comme si elle était ouverte.

Les onze autorisations portent `valid_until=2026-10-12T13:58:41.752Z`. Leur enregistrement ne prolonge pas cette durée : toute phase ultérieure après cette échéance nécessitera une nouvelle ancre d'actualité et de nouvelles autorisations gouvernées. Cette PR ne lance aucun job, transfert, ingestion, publication, exposition étudiante ou déploiement production. `GO_LIVE_READY=false` et `RAG_PRODUCTION_DEPLOYED=false` à cette observation.
