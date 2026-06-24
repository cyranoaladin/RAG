# Templates corpus pilote — mathematiques terminale specialite

Ce dossier contient uniquement des modeles de preparation manuelle pour un futur
manifest pilote reel metadata-only.

## Ce que l'humain doit preparer

Avant tout futur import, un humain doit renseigner pour chaque ressource :

- l'identifiant stable `doc_id` ;
- le chemin local futur dans un dossier de staging valide ;
- le `source_uri` correspondant ;
- le SHA-256 reel du fichier source ;
- les droits et la visibilite ;
- le type documentaire ;
- les notions et competences ;
- les references officielles applicables ;
- la decision de review humaine.

## Emplacement futur des documents reels

Les documents reels pourront etre places plus tard dans un dossier dedie, par exemple :

```text
data/staging/pilot_math_terminale/
```

Ce dossier n'est pas cree par le lot 15C. Aucun PDF ou document reel ne doit etre ajoute
tant qu'un lot dedie n'a pas ete valide.

## Calcul futur des SHA-256

Le champ `sha256` doit etre calcule plus tard sur les octets exacts du fichier source.
Le kit ne calcule pas les hashes automatiquement afin d'eviter toute lecture de document.

Exemple futur, a lancer seulement dans un lot autorise :

```bash
sha256sum data/staging/pilot_math_terminale/source.pdf
```

## Champs obligatoires

Chaque entree devra pouvoir devenir un `DocumentMeta` valide avec au minimum :

- `doc_id`
- `source_uri`
- `source_type`
- `sha256`
- `discovered_at`
- `rights`
- `visibility`
- `matiere`
- `type_doc`

Pour ce pilote, les champs pedagogiques attendus sont :

- `niveau: terminale`
- `voie: generale`
- `matiere: mathematiques`
- `statut_enseignement: specialite`
- `candidat: scolarise`
- `programme_version`
- `notions`
- `competences`

## Droits acceptables

Valeurs attendues pour le pilote :

- `officiel_public` pour une reference officielle publique ;
- `nexus_proprietaire` pour une ressource Nexus proprietaire ;
- `usage_interne` pour une ressource strictement interne.

Un document `rights=unknown` ne doit jamais etre recuperable. Il doit etre qualifie ou
exclu avant tout import controle.

## AEFE Tunisie

Pour une ressource visant les eleves AEFE Tunisie scolarises :

- utiliser `candidat: scolarise` ;
- utiliser `candidate_status_ref: scolarise` ;
- utiliser `establishment_context_ref: aefe` ;
- renseigner `extra.zone: aefe_tunisie`.

AEFE est un contexte d'etablissement, pas un statut candidat.

## Candidat scolarise et candidat individuel

Le corpus pilote cible `scolarise`. Les ressources candidat individuel doivent rester dans
un lot separe, avec refs et review dediees.

## Sources pending

Une source ou claim `pending` ne doit jamais soutenir seule une decision reglementaire.
Les documents officiels et d'examen doivent citer une source ou claim verifiee quand la
metadonnee est definitive.

## Validation offline

Le validateur du lot 15C controle uniquement la forme du brouillon :

```bash
python -m rag_pedago.imports.pilot_manifest_template docs/templates/pilot_math_terminale/pilot_manifest.template.yml
```

Il ne lit pas les `source_uri`, ne calcule pas de hash et ne verifie pas l'existence des
fichiers sources.
