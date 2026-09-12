# LOT BF — dettes constatées, avec antériorité prouvée

## 1. Quatre épreuves du gate de readiness dépendent du disque de l'hôte

**Épreuves concernées** (`scripts/tests/test_go_live_readiness.py`) :

- `test_tout_ferme_donne_go_live_ready`
- `test_assert_ready_rend_zero_seulement_si_tout_est_ferme`
- `test_le_plan_se_ferme_quand_tout_se_ferme`
- `test_fermer_la_gouvernance_ne_rend_pas_le_corpus_interrogeable`

**Symptôme.** Chacune pose une fixture où toutes les dimensions de gouvernance
sont closes, puis attend `go_live_ready=true` (ou une liste de refus précise).
Le gate ajoute `disk_policy_ok` à `blocking_reasons`, et l'attente tombe. Dans
les quatre cas, `disk_policy_ok` est le **seul** élément en trop.

**Cause.** `_disque()` mesure l'espace libre réel via
`shutil.disk_usage(REPO_ROOT)`. La fixture contrôle le contenu du dépôt, pas le
système de fichiers qui l'héberge. `DISQUE_LIBRE_MINIMUM_OCTETS` vaut 40 GiO ;
la machine est à **34,89 GiO libres**. La condition ne peut donc pas être
satisfaite, quelle que soit la fixture.

**Antériorité prouvée.** Les quatre échouent à l'identique sur un checkout
vierge de `main` au commit parent `ae5eb76caab5638dab54bd5b64f59b73fda4d34e`,
sans aucune modification de ce lot : `4 failed, 92 passed`. Elles passaient plus
tôt dans la même session, quand l'espace libre était encore au-dessus du seuil.

**Ce que ce lot n'a pas fait, et pourquoi.**

- Aucun `docker system prune`, `docker builder prune` ni `docker volume prune` :
  interdits par le mandat. 78 Go d'images et 137 Go de cache de build sont
  récupérables, mais cette décision appartient à l'humain.
- Aucune neutralisation de la mesure disque dans le gate. Une variable
  d'environnement de contournement serait exactement le moyen de rendre un
  go-live vert sur une machine qui n'a pas la place de le servir.
- Aucun assouplissement des quatre épreuves. Elles disent vrai : sur cette
  machine, « tout est fermé » est faux.

**Ce que la base dédiée de ce lot pèse.** 47 Mo. Elle n'est pas la cause : le
seuil était déjà franchi avant sa création.

**Fermeture.** Libérer de l'espace au-dessus de 40 GiO, ou décider que le seuil
de 40 GiO n'est pas le bon — mais alors par un changement assumé du gate, pas
par un contournement dans les épreuves.

**Cause identifiée (lot BG).** L'audit de récupération nomme l'origine : **24
images Docker sans étiquette et non référencées**, dont **16 créées dans les six
dernières heures**, à 3,18 Go pièce. Ce sont des restes de reconstructions
Node/Playwright appartenant à **d'autres chantiers** de la machine
(`agent-*`, `entitlement-bug-investigation-*`, `core-v2-auth-*`), pas à ce
dépôt. Aucune n'est référencée par un conteneur. Le franchissement du plancher
est donc un effet de voisinage, et non une dérive de ce chantier : les artefacts
produits par ce lot pèsent 47 Mo.

Voir `docs/reports/go_live/DISK_RECOVERY_AUDIT.md` pour l'inventaire classé et
les commandes nommées une par une. Aucune n'a été exécutée.

**FERMÉE (lot BH).** Deux opérations autorisées nommément par l'humain :

1. `docker rmi` sur huit images sans étiquette — gain **mesuré : nul**. La taille
   affichée par `docker images` est virtuelle ; ces images partageaient leurs
   couches avec des images encore étiquetées. L'estimation de 49,5 Gio était une
   borne haute, et le fait l'a démentie. C'est consigné comme tel dans le
   rapport, avec le verdict `ESTIMATION_DEMENTIE_PAR_LA_MESURE`.
2. `docker buildx prune --force`, après vérification qu'aucun build n'était en
   cours — gain **mesuré : 70,6 Gio**. Le cache de build ne porte aucune donnée :
   seul son temps de reconstruction est perdu.

Espace libre 30,4 Gio → **101,0 Gio**. `disk_policy_ok` passe de `false` à
`true` et disparaît de `blocking_reasons`.

**Les quatre épreuves repassent au vert** : sur l'arbre livré ici,
`pytest scripts/tests/` rend **276 passed, 0 failed**. Leur échec était bien
causé par l'espace disque de l'hôte, et par rien d'autre — le retour au vert
sans toucher à une ligne de test en est la preuve.

Le chiffre porte sur l'arbre FINAL, épreuves ajoutées par ce lot comprises.
Une première rédaction consignait 269, mesuré avant l'ajout de ces épreuves :
un résultat antérieur ne peut pas attester que ce qui a été ajouté depuis
passe.

## 2. `ruff check` depuis la racine signale 8 `UP038` préexistants

`services/rag-pedago/rag_pedago/governance/reference_programme.py`,
`.../imports/raw_pii_guard.py`, `.../scripts/campagne_actualite_url.py`,
`.../scripts/decouvrir_liaisons_programme.py`.

La CI lint chaque service avec **sa** configuration ; la configuration racine
est plus stricte. Les huit sont présents à l'identique sur `ae5eb76`.
`ruff check scripts/` — le périmètre modifié par ce lot — est propre.

## 3. `pytest scripts/tests/` n'était exécuté nulle part en CI

La CI nomme ses épreuves une à une dans `repository controls` ; elle ne lance
pas la suite pytest de `scripts/tests/`. Un garde-fou ajouté là pouvait donc
rester vert pour toujours sans jamais tourner — c'est ce qui est arrivé au
garde-fou de fraîcheur du snapshot livré en #195.

**Traité dans ce lot** pour le seul fichier concerné
(`test_readiness_artifacts_coherence.py`), désormais exécuté par
`repository controls`. Le reste de la suite reste hors CI : dette ouverte.

## 4. Le plancher disque est de nouveau franchi, cette fois par ce chantier

**Constat.** `disk_policy_ok=false`, 37,74 Gio libres contre un plancher de
40 Gio. Les quatre épreuves de `test_go_live_readiness.py` qui attendent
`go_live_ready=true` sur une fixture close échouent pour cette seule raison,
comme au lot BF : `disk_policy_ok` est le seul élément en trop.

**Cause, et elle est de ce chantier cette fois.** La campagne a rapatrié un
miroir Drive en lecture seule (1,7 Go) et dupliqué l'artefact de modèle (9 Go)
parce que l'artefact existant échouait la vérification canonique — son
inventaire omettait `manifest.json`.

**Ce qui a été rendu.** La copie de l'artefact a été ramenée de 9 Go à 2,2 Go
en retirant les variantes `onnx`, `openvino` et `pytorch_model.bin`, que
`sentence-transformers` n'utilise pas : il charge `model.safetensors`.
L'inventaire a été régénéré selon la règle canonique et l'artefact passe
toujours `verify_embedding_artifact`. **6,8 Go rendus.** L'artefact d'origine
n'a pas été touché.

**Ce qui n'a pas été touché, et pourquoi.** Le miroir Drive (1,7 Go) reste
nécessaire pour rejouer le re-découpage. Les 86 Go d'images Docker
récupérables appartiennent à d'autres chantiers de la machine : leur cycle de
vie ne se décide pas depuis ce dépôt.

**Fermeture.** Libérer environ 2,3 Gio de plus, ou décider que le plancher de
40 Gio n'est pas le bon — mais alors par un changement assumé du gate.
