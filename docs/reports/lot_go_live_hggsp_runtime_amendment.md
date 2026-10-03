# Lot go-live — amendement du runtime HGGSP après #279

## Pourquoi

Le CLI d'adoption V2 est **embarqué dans l'image Worker B** (`rag-multilevel-worker-production`). #279 (adoption bornée aux collections du successeur,
ADR-0062) change donc des octets exécutés : fusionner ne suffit pas. L'autorisation #270 et la readiness signée épinglent encore les images du
run `36633288414`, qui n'ont pas ce correctif.

## Provenance : run `37063628014` (workflow_dispatch sur `main`, aucun build sur l'hôte)

| | |
|---|---|
| run / tentative | `37063628014` / 1 |
| commit source | `242d267046f1e9200b009e664410bc7b40816fae` |
| arbre | `dc01b1bfc0d8722a3347da69b72cb5580f337197` |
| artefact (ZIP sha256) | `11251726187` (`989fd82afa4b0f5dca2f170e9ebd899d33d2fe5b69155c819c490acc0bb88691`) |
| inventaire sha256 | `fa8406bb589aec405ca75e2bacd4282469fadc7c1358159827c337e06a7cf84f` |
| Worker A et B | `sha256:318ef58490e8de66a3f0bb0bea4d147cb1a700eaa6648a6b374c940e7b8fc222` (avant : `2228650e2245…`) |
| retrieval (`rag-ingestor`) | `sha256:90cba4293be3a74ff333ea0a3e8c1c2dcc66d8e4ce4c8f8d35df1e887f172abb` (avant : `11aa98d58ebc…`) |
| Dockerfiles | inchangés (worker `feeceb78…`, ingestor `f7f53bab…`) |

Le digest retrieval **change aussi**, bien que son Dockerfile soit inchangé : le contexte de build est le dépôt entier, donc tout commit le fait varier.
Les deux images sont épinglées depuis le même inventaire ; mélanger un Worker B de ce run avec le retrieval d'un autre run casserait l'unicité de la preuve.

## Ce que change cette PR

- `docs/reports/evidence/staging_hggsp_image_provenance.json` : régénérée depuis l'inventaire (même schéma).
- Autorisation #270 amendée (même fichier) : images, bloc `provenance`, `base_commit_sha`, liens au plan et à la preuve, et un bloc **`amendment`** :
  - ce qui est supersédé : run, commit, deux images, et les **empreintes de l'ancienne paire de readiness** (manifeste `70fb399b…`, liaison `ed8d0814…`) ;
  - `carried_over_operations` : migration 020 + rôle adopter, enregistrement des deux r4 (faits persistants, non rejoués) ;
  - `renewed_operations` : `successor_readiness_install`, `successor_preflight` (preuve runtime à renouveler) ;
  - `not_performed_operations` : tout le reste. **Aucune opération non effectuée n'est marquée réussie.**
- Vérificateur : constantes d'images, de provenance et d'empreintes (preuve, plan, autorisation) ; le bloc `amendment` est comparé exactement.
- Runbook : digests, run et section « Amendement du runtime ». Il est lié par SHA, donc recalculé.
- `hggsp_successor_readiness.py` : nouvelles images et commit source (la readiness signée lie les images).
- **Supersession de la readiness** (aucun mécanisme n'existait : l'installation refusait toute divergence distante) :
  - `scripts/go_live/readiness_install_remote.sh` : exécuté sur l'hôte, toute la décision y est (installation / déjà installée / **supersession** / refus).
    - La paire distante n'est remplacée que si ses **deux** fichiers portent les empreintes pinnées dans `amendment`. L'ancienne paire est **archivée**
      (`readiness/superseded/<horodatage>-<empreinte>/`, copie vérifiée, les deux fichiers en lecture seule) avant les renommages.
    - **Entrées validées avant tout nettoyage** : noms (basename simple, ni `..` ni `/`), empreintes, horodatage, destination (chemin absolu, répertoire réel).
      Le nettoyage de sortie n'existe qu'ensuite et ne supprime que les deux fichiers déposés.
    - **Dépôt entrant** : répertoire réel, jamais un lien symbolique (même cassé), enfant direct de la destination, nommé `.incoming-*`. Le nettoyage le
      revérifie avant de supprimer : un lien vers la destination ferait sinon supprimer la paire active, qui porte les mêmes noms.
    - **Remplacement interrompu** : les deux renommages ne sont pas atomiques ensemble. La restauration prépare d'abord les **deux** anciens fichiers sous des
      noms temporaires, vérifiés, puis les renomme, puis revérifie les deux empreintes. Si elle n'aboutit pas, le script **refuse en donnant l'état exact des
      deux fichiers** (`manifeste=… liaison=…`) et dit que la paire active n'est pas garantie valide ; il ne prétend jamais qu'une paire est restaurée sans
      l'avoir vérifié, et ne laisse aucun temporaire.
    - **Installation fraîche interrompue** : l'annulation est vérifiée ; le message dit l'état réel (aucune paire active, ou paire partielle à corriger à la main)
      et ne promet plus un fichier à récupérer dans un dépôt que la sortie nettoie.
    - Un fichier seul, une empreinte inconnue, une paire mixte, l'absence de pin ou un lien symbolique sont refusés sans rien modifier.
  - `scripts/go_live/retire_runtime_markers.sh` : **renomme** (jamais ne supprime) les marqueurs `.done` du préflight puis de la readiness en
    `*.done.superseded-<horodatage>`, dans cet ordre (un état interrompu ne peut pas rejouer l'installation en sautant le préflight). Chaque renommage est
    **vérifié** (`mv -n` ne dit pas s'il a déplacé). Le journal est **transactionnel avec les marqueurs** : les deux lignes `SUPERSEDE` sont composées et
    ajoutées en une seule écriture, et au premier échec (renommage, écriture, écriture partielle) les marqueurs sont restaurés **et** le journal ramené à sa
    taille initiale, de sorte qu'il ne reste jamais une ligne affirmant une supersession dont les `.done` ont été restaurés.
    Les marqueurs 020 et r4 ne sont jamais touchés.
  - `staging_hggsp_complementary.sh supersede-runtime` : vérifie l'autorité active, la nouvelle readiness locale et l'ancienne paire distante
    (lecture seule), puis retire les marqueurs. En `--dry-run` il dit explicitement ce qu'il **ne** vérifie **pas** (paire distante, état des marqueurs).
    `run` installe ensuite la nouvelle paire et rejoue le préflight.

## Après fusion (aucune de ces étapes n'est exécutée par cette PR)

1. Nouveau worktree sur le commit de fusion ; contrôles d'autorisation sur ce HEAD.
2. **Disque** : l'orchestrateur exige les deux nouvelles images présentes localement aux digests exacts. Elles pèsent plusieurs Gio chacune
   (l'ingestor ~5,5 Go) ; le disque était à ~41 Gio. Prévoir le pic avant tout tirage ; supprimer les images supersédées est une décision humaine distincte.
3. Signer **localement** la nouvelle paire de readiness (`sign_staging_hggsp_successor_readiness.sh`, clé hors dépôt) dans un **nouveau**
   répertoire (`HGGSP_READINESS_LOCAL`) : l'ancienne paire locale est conservée comme preuve.
4. `supersede-runtime`, puis `run --until successor_preflight`, puis la suite (adoption bornée, liaison, proposition de revue batch).
5. Un jeton GitHub de lecture d'un jour est requis pour les contrôles live.

## Qualification (exécutée sur ce code, depuis `scripts/qualification/tests`)

| Commande | Résultat |
|---|---|
| `pytest test_hggsp_runtime_supersession.py` | 50 passed |
| `pytest test_staging_hggsp_authorization.py` | 65 passed |
| `pytest test_hggsp_successor_readiness.py` | 11 passed |
| `pytest test_staging_hggsp_orchestrator.py test_staging_hggsp_chain.py test_worker_b_guard.py --deselect …::test_premerge_run_fails_before_ssh` | 86 passed, 3 skipped |

Total des quatre commandes : 212 passed, 3 skipped. `test_premerge_run_fails_before_ssh` est écarté : dette connue, non hermétique.

- `test_hggsp_runtime_supersession.py` exécute réellement les deux scripts sur des répertoires temporaires, sans SSH ni Docker. Six mutations volontaires des
  scripts (restauration, lien symbolique, nettoyage de sortie, garde du dépôt entrant, vérification du renommage, annulation sur journal) font chacune échouer
  au moins un test ; deux mutations antérieures (archivage, pin) en font échouer 2 et 6.
- `test_staging_hggsp_authorization.py` : refus sur chaque altération du bloc `amendment`, valeurs exactes du runtime et de la readiness supersédés,
  égalité exacte des groupes d'opérations avec les opérations moins la signature, cohérence des images entre autorisation, orchestrateur, readiness et runbook.

Limites : la supersession est éprouvée en local sur des répertoires, pas sur le serveur ; elle suppose `mv -T` atomique sur un même système de fichiers
(le dépôt entrant est créé dans `readiness/`). Aucune clé n'a été lue et aucune readiness signée.
