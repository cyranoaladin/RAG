# Lot — lecture de l'inventaire candidat des dérivés étudiants

Base de travail : `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`, dans un worktree et un environnement Python isolés. Ce lot ne crée ni release active, ni transfert d'octets, ni écriture staging ou production.

Le lecteur `load_student_public_candidate_inventory` accepte le type `NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1` uniquement si le fichier correspond au SHA-256 attendu. Il contrôle la structure complète, les autorités SHA, les comptes, l'ordre et l'unicité des collections, artefacts et placements, la provenance URL Éduscol, la distinction entre SHA du PDF source et SHA du texte dérivé, le type MIME texte et un chemin strict `<sha-du-dérivé>.txt`. Il produit les placements et les clés `(content_sha256, source_placement_id)` nécessaires à Worker A. Le chemin `01_EDUSCOL_OFFICIEL/` reste propre au lecteur PDF V1 et est refusé pour ce nouveau type.

Worker A choisit ce lecteur seulement pour le nouveau `inventory_kind`. Le format historique `MULTILEVEL_CANDIDATE_INVENTORY_V1` suit toujours son ancien indexeur ; tout type inconnu est refusé. La garde `release_mode=candidate` reste active avant toute écriture d'ingestion : cette branche de lecture ne promeut pas une candidate release.

## Vérifications

- TDD : deux tests rouges ont montré l'acceptation d'un type inconnu et l'exception non contrôlée d'un port URL invalide ; les corrections rendent les 15 tests du nouveau lecteur verts.
- Suite ciblée ingestion scellée, placements multi-niveaux, contrat d'ingestion réel et nouveau lecteur : 163 tests réussis.
- Ruff : aucune erreur sur les trois fichiers modifiés ou ajoutés.
- Inventaire réel préparé par le lot indépendant `bfd57253b55048d84f00b6d0eb97869c699ae749`, SHA-256 `711379db9e8bc822a0295d17f77bced80a5cf1fbe527f30ac627fccdd59c139f` : 11 collections, 253 dérivés, 377 placements et 377 jointures Worker A. Cette lecture ne constitue pas une preuve de transfert des fichiers.
- Régression V1 : l'inventaire PDF V4 de référence conserve 479 placements et tous ses chemins historiques.

## Limite de ce lot

Les SHA du catalogue V4/V5, des reçus et des dérivés sont validés comme identifiants et cohérents dans l'inventaire, mais leurs fichiers externes ne sont pas vérifiés par ce lecteur seul. L'étape d'autorisation et de transfert doit les lier aux octets réels. La preuve `currentness` multi-niveaux actuelle est liée à l'inventaire PDF V1 et à ses autorités ; elle ne vaut pas automatiquement pour les nouveaux dérivés. Une preuve de currentness dédiée, liée aux identités et à la release successeur, est nécessaire avant toute activation.
