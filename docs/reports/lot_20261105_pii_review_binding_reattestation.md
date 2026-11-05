# Lot 2026-11-05 — ré-attestation des deux autorités de revue PII expirées

## Ce que ce lot est, et ce qu'il n'est pas

**Ce lot ne prend aucune décision PII de fond.** Les deux ensembles de décisions humaines concernés sont inchangés, octet pour octet, depuis leur scellement. Aucun contenu n'entre, ne sort ni ne change de disposition. Ce lot ouvre la fenêtre de revue nécessaire à une **ré-attestation de contenu inchangé** : l'humain re-signe des octets qu'il a déjà jugés.

Ce premier HEAD (H1) **ne contient aucun nouveau reçu**. Il porte uniquement ce rapport. Les deux reçus ne seront produits qu'**après** l'approbation humaine de H1, par l'opérateur détenteur de la clé, et ajoutés dans un second HEAD (H2).

Base : `origin/main=99178e64a9eaa8c758a907d226f23ac2b68c4066`, arbre `cf5b5356ffc5d7ac9426366ae6bf26f128c16995`. Branche issue exactement de ce SHA, worktree propre et détaché.

## Pourquoi un renouvellement est nécessaire

ADR-0035 donne aux reçus de liaison de revue une fenêtre de validité — 30 jours par défaut — et l'assume explicitement : *« une preuve de revue vieillit »*. `nexus_contracts.review_binding` refuse tout reçu dont `now >= expires_at`, avec le message *« a proof of review ages, and a stale one never authorizes a publication »*.

Les deux reçus du dépôt ont franchi leur échéance :

| Reçu | `verified_at` | `expires_at` | État |
| --- | --- | --- | --- |
| `governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json` | 2026-09-23T19:04:55.555052Z | **2026-10-23T19:04:55.555052Z** | expiré |
| `governance/pii-review-bindings/pii-review-2026-09-03-final.json` | 2026-09-03T22:02:48.263884Z | **2026-10-03T22:02:48.263884Z** | expiré |

Trois jobs de CI en dépendent et refusent en conséquence : `services/rag-pedago` (3 échecs sur 3 614 tests), `services/rag-engine`, `governance postgres`. Ils échouent **par péremption, sans aucune modification de code** — `main` n'a reçu aucun commit entre le dernier run vert du 13 octobre et aujourd'hui.

## Pourquoi il est interdit de les redater

ADR-0035 lie le reçu à ses octets : *« Changer un seul de ces champs change le digest canonique, donc invalide »*. Le `binding_digest` est le SHA-256 de la forme canonique du binding, et la signature Ed25519 porte sur ces mêmes octets. Éditer `expires_at` à la main casserait simultanément le digest et la signature — le vérificateur refuserait, et à juste titre.

Surtout, redater reviendrait à **antidater une preuve humaine** : affirmer qu'une revue a été vérifiée à un instant où elle ne l'a pas été. La validation suit un ordre délibéré — canonicité, puis digest, puis ancre de confiance, puis signature, puis fenêtre temporelle — précisément pour qu'*« un reçu dont la signature n'a pas encore été vérifiée n'ait le droit de rien décider, pas même sa propre expiration »*.

Les deux reçus expirés **ne seront ni modifiés ni redatés**. Ils seront remplacés, à leur chemin canonique, par des reçus nouvellement produits contre une revue réelle.

## Pourquoi une nouvelle revue humaine est nécessaire

Le producteur `issue_review_binding_cli.py` ne constate que ce qu'il relit en direct : *« Aucun argument ne permet d'affirmer un fait : chaque champ du reçu est lu depuis GitHub ou dérivé des octets relus. »* Il est fail-closed sur, notamment, une **PR fermée**, une review non approuvée, un HEAD divergent, un reviewer égal à l'auteur, une permission insuffisante.

Or les deux PR d'origine sont fusionnées : **#249** le 2026-09-23 et **#143** le 2026-09-03. `evaluate_trusted_review` refuse une PR fermée (`pull_request_not_open`). Le mode historique de `verify_review` existe mais son contrat le réserve à un binding déjà recomposé par l'enveloppe C depuis un reçu de PR fusionnée ; le producteur de binding ne l'emploie jamais. **Il n'existe donc aucun chemin de renouvellement depuis une PR fusionnée** : une PR neuve et ouverte est obligatoire. C'est l'objet de celle-ci.

## Les deux jeux de décisions sont inchangés, octet pour octet

Vérifié sur `main=99178e64` au 2026-11-05.

### `pii-review-2026-09-22-profile-gate-v3`

| Dimension | Valeur attestée par le reçu expiré | Valeur actuelle sur `main` | Égalité |
| --- | --- | --- | --- |
| SHA-256 de l'artefact | `1b70d91b52d207d301d87076573593cb0899ed2b52d6e2963fbcf8fcd3472a66` | identique | **oui** |
| Git blob SHA-1 | `e799429ed0b64dfd3fade562963ad97e8a51e505` | identique | **oui** |

`decision_set_id = pii-review-2026-09-22-profile-gate-v3` · `corpus_manifest_sha256 = 5ce13fac8b74e12ac9538a710b733aeb6a78f3d49434a44ac49e4c0b38296df7` · `review_index_sha256 = abdd15256eba9ed5717529327131b0afe6f5de17189180bd082fd2a9bfeadb55` · **22 décisions, 22 `content_sha256` distincts, 22 `APPROVED`, 0 `REFUSED`**, triées par SHA croissant.

Un seul commit dans l'historique de ce fichier : `b2ffbc7a` (squash de #249). Jamais modifié depuis.

### `pii-review-2026-09-03-final`

| Dimension | Valeur attestée par le reçu expiré | Valeur actuelle sur `main` | Égalité |
| --- | --- | --- | --- |
| SHA-256 de l'artefact | `2b1974259b1ac4a2a21766b71f3ed586df22722cb969f07bdb3fb0bdaafda469` | identique | **oui** |
| Git blob SHA-1 | `684e09d015ff7c53e1ee315977ffe0cb476bda37` | identique | **oui** |

`decision_set_id = pii-review-2026-09-03-final` · `corpus_manifest_sha256 = 5ce13fac8b74e12ac9538a710b733aeb6a78f3d49434a44ac49e4c0b38296df7` · `review_index_sha256 = bcb4c6f4327631a6265e5fbfa16c94a10cb1760a90683f10dff6da385aa6ad13` · **23 décisions, 23 `content_sha256` distincts, 23 `APPROVED`, 0 `REFUSED`**, triées par SHA croissant.

Un seul commit dans l'historique de ce fichier : `1a476ca0` (squash de #143). Jamais modifié depuis.

### Les deux jeux sont distincts et ne doivent pas être confondus

Populations différentes — 22 contre 23 contenus — et index de revue différents (`abdd1525…` contre `bcb4c6f4…`), parce qu'il s'agit de deux campagnes distinctes. Ils partagent en revanche le **même `corpus_manifest_sha256`** et les **mêmes trois instruments**. Renouveler l'un sans l'autre ne fermerait pas la dette : `services/rag-pedago/tests/test_build_release_pii_projection.py` charge le jeu 09-03 comme `REAL_RECEIPT` (l.31) et le v3 comme `CURRENT_RECEIPT` (l.36). Le rouge se déplacerait au lieu de disparaître.

## Les trois instruments PII sont inchangés

Vérifiés indépendamment, par chemin, contre les valeurs attestées — identiques pour les deux jeux.

| Instrument | Chemin | Empreinte attestée | Empreinte actuelle | Égalité |
| --- | --- | --- | --- | --- |
| Politique PII | `services/rag-pedago/configs/pii_gate_policy.yml` | `d09cbfd23a4fcc3a744cdaeddf60a22863dfe64e0cc4c26e375309b21984e484` | identique | **oui** |
| Scanner | `services/rag-pedago/rag_pedago/imports/pii_scanner.py` | `388e3ed475625bc44b4fc74827b8950bc1932314f7b1468a27c491905fa54e94` | identique | **oui** |
| Politique de pages | `packages/pdf-page-policy/src/nexus_pdf_page_policy/__init__.py` | `82e1de44719bf06bbd6bbff8bae121a6d654ce434d08e225cd386508d9661d02` | identique | **oui** |

Chacun des deux jeux impose en outre, par ADR-0047, que **toutes** ses décisions portent les mêmes instruments : vérifié, une seule valeur distincte par champ sur les 22 comme sur les 23 décisions.

### Les autorités annexes aussi

- `corpus_manifest_sha256 = 5ce13fac…` : présent et inchangé à `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/corpus_manifest_authority.json`.
- `review_index_sha256 = abdd1525…` (v3) et `bcb4c6f4…` (09-03) : présents et inchangés, le second à `docs/reports/evidence-index/pii_review_index_20260903.json`.

## Pourquoi il s'agit d'une ré-attestation, et non d'une instruction de fond

Six vérifications indépendantes concordent, pour chacun des deux jeux : SHA-256 de l'artefact, Git blob SHA-1, unicité du commit dans l'historique du fichier, les trois instruments à leur chemin actuel, le manifeste de corpus, l'index de revue. **Rien de ce qui a été revu en septembre n'a bougé. Seule l'horloge a tourné.**

Ce que l'humain atteste en re-signant : que ces artefacts, à ces octets exacts, restent sa décision ; que les 22 et 23 dispositions `APPROVED` restent valides ; que les instruments sont bien ceux qu'il entendait ; que le manifeste de corpus décrit toujours le corpus visé. Aucune migration, table, colonne, endpoint, log ni export n'entre dans ce périmètre : ces jeux portent sur des **contenus** et leurs pages, pas sur un schéma de données.

## Une seule PR est légitime pour les deux renouvellements

Établi par le code, non supposé.

1. **La review lie la PR et son HEAD, pas l'artefact.** Le challenge d'ADR-0025 est construit sur un payload à huit clés — `repository`, `pull_request`, `base_ref`, `base_sha`, `head_sha`, `author`, `reviewer`, `protocol`. Aucune référence à un artefact, à un `decision_set_id` ni à un chemin.
2. **Chaque artefact est lié indépendamment à son émission.** Le producteur dérive le chemin du seul `--decision-set-id`, relit les octets au HEAD approuvé via `fetch_blob_at_ref`, et scelle les empreintes propres à cet artefact. Le code l'affirme : *« Deux natures d'artefact, un seul pipeline. »*
3. **Rien n'exige que la PR modifie l'artefact.** Aucune notion de fichier modifié, de diff ou d'artefact touché dans le producteur ni dans le validateur. L'artefact est lu au HEAD approuvé, quel qu'il soit — et les deux jeux sont déjà sur `main`.
4. **Côté consommateur**, `require_matches_authorization` ne contrôle que l'égalité du dépôt, de l'`authorization_id` et des digests. Contrôle d'empreinte, jamais de provenance de PR.

Deux invocations du CLI, deux `--decision-set-id`, un même HEAD approuvé : les deux reçus sont alors chacun lié à ses propres octets, sous la même revue humaine.

## Aucune clé privée nulle part

La clé de signature est détenue par l'opérateur, **hors Git, hors CI, hors serveurs et hors artefacts de build**, avec sauvegarde chiffrée et restauration vérifiée exigées avant usage opérationnel. Le producteur ne la lit que depuis la variable d'environnement `NEXUS_REVIEW_BINDING_SIGNING_KEY`, jamais depuis un fichier du dépôt, jamais générée, **jamais imprimée — pas même tronquée**.

Aucune clé n'est présente dans ce dépôt, dans cette PR, dans ses journaux ou dans ses artefacts. La préparation de ce lot n'a procédé à aucune recherche, lecture ni localisation de cette clé. L'étape de signature est **humaine** et interviendra après l'approbation de H1.

## Séquence restante

1. Approbation humaine de **H1** par `abenrhouma`, avec le challenge exact de H1.
2. Opérateur détenteur de la clé, deux invocations contre ce même H1, l'une par `decision_set_id`, validité 30 jours, clé `review-binding-v1-2026-08-25`.
3. Vérification hors ligne des deux reçus — canonicité, digest, ancre de confiance, signature, fenêtre — avant tout commit.
4. Ajout des deux reçus dans cette PR → **H2**. L'approbation de H1 sera automatiquement écartée (`dismiss_stale_reviews`), ce qui est normal : le reçu est une preuve scellée hors ligne, vérifiée par signature et digest, jamais par une nouvelle interrogation de GitHub. C'est exactement ce que montre #249, dont la review citée par le reçu apparaît aujourd'hui `DISMISSED` sans invalider le reçu.
5. Approbation fraîche sur **H2**, avec un challenge recalculé — il intègre `base_sha`, donc il change si `main` bouge.
6. Commentaire `/nexus-trusted-review` pour republier le statut épinglé au HEAD : une soumission de review ne déclenche pas le workflow.
7. Contrôle des contextes requis avant toute fusion.

## Périmètre explicitement exclu

Ce lot ne traite **pas** : l'exception d'audit `braces` du Cockpit ; les PR **#345**, **#346** et **#347** ; la campagne d'actualité **A3** ; le ménage des **worktrees** ; la **production**. Il ne déploie rien et ne touche aucune cible.

Il ne ferme que la dette du reçu PII. Une fois les deux reçus renouvelés, six des sept contextes requis de #345/#346/#347 devraient passer au vert ; `services/cockpit` resterait rouge sur l'exception `braces`, dette distincte.
