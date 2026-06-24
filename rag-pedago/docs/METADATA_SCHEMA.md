# Schema de metadonnees

Les metadonnees sont le contrat principal du RAG pedagogique. Elles decrivent
ce qu'est une ressource, d'ou elle vient, quels droits s'appliquent, a quel
profil eleve elle correspond et comment elle peut etre citee.

Le RAG ne doit pas dependre des dossiers pour filtrer. Un chemin comme
`maths/terminale` peut aider au diagnostic, mais il ne suffit pas : un fichier
peut etre mal range, deplace, importe depuis un manifest ou provenir d'une
source distante. Les filtres doivent donc utiliser les payloads et metadonnees
validees : `niveau`, `matiere`, `statut_enseignement`, `epreuve`, `candidat`,
`programme_version`, `rights` et `visibility`.

## Champs critiques

Les champs suivants sont obligatoires pour un document servi ou indexable :

- `doc_id`
- `source_uri`
- `sha256`
- `source_type`
- `rights`
- `visibility`
- `matiere`
- `type_doc`

Les champs pedagogiques structurants sont distincts :

- `niveau` : classe ou groupe scolaire vise, par exemple `terminale`.
- `matiere` : discipline, par exemple `mathematiques` ou `nsi`.
- `statut_enseignement` : tronc commun, specialite, option, examen, etc.
- `epreuve` : contexte d'evaluation, par exemple `bac_specialite_ecrit`.
- `candidat` : scolarise, individuel, CNED, AEFE ou commun.

Ces dimensions ne doivent pas etre fusionnees. Une annale de specialite maths
terminale n'est pas seulement un document de maths : elle porte aussi un niveau,
un statut d'enseignement, une epreuve, une session et des droits.

## Droits

`rights` est obligatoire. Une ressource avec `rights=unknown` n'est pas
retrievable par contrat et devra etre bloquee par les couches de retrieval et
d'API. Le lot 2 modele cette regle avec `DocumentMeta.is_retrievable`.

Le lot 2.5 ajoute une matrice de contextes d'acces. Elle distingue notamment :

- `officiel_public` : peut etre servi en contexte public avec citation ;
- `nexus_proprietaire` : reserve aux usages internes, enseignants et eleves inscrits ;
- `usage_interne` : reserve aux operations internes et enseignants ;
- `student_private` : reserve a l'eleve proprietaire et aux administrateurs ;
- `parent_private` : reserve au parent concerne et aux administrateurs ;
- `commercial_confidential` : jamais expose dans une reponse parent ou eleve ;
- `restricted` : reserve aux administrateurs ;
- `unknown` : bloque.

Cette matrice est volontairement portee par les metadonnees et non par le
chemin fichier. Une copie eleve rangee dans un mauvais dossier doit rester
privee si son `rights` l'indique.

## Profil eleve Nexus

`StudentProfile` prepare les usages cockpit Nexus sans rendre tous les champs
obligatoires des le depart. Il peut porter l'etablissement, le statut detaille
AEFE/CNED/double cursus/candidat libre, les specialites, options, objectifs,
besoins, disponibilites, offre Nexus, groupe Nexus, confirmation enseignant et
zone de calendrier scolaire.

Les incoherences non bloquantes produisent des warnings. Exemple :
`maths_expertes_without_maths_specialite` signale une option maths expertes sans
specialite mathematiques conservee.

## Profil d'examen

`ExamProfile` decrit la carte d'examen : session, zone, centre, statut
d'inscription, convocation, modalite ponctuelle, epreuves a passer, epreuves
deja validees, options et specialites. Ce schema est separe de `StudentProfile`
car un eleve peut avoir un profil pedagogique connu mais une carte d'examen
encore incertaine.

## Référentiel officiel

Le lot 9 ajoute des champs optionnels de liaison :

- `official_level_ref`
- `official_exam_ref`
- `official_subject_ref`
- `candidate_status_ref`

Ils pointent vers `data/reference/` et permettent de distinguer une metadonnee
pedagogique d'une reference institutionnelle. Les reponses futures du RAG qui
portent sur des obligations, epreuves, horaires, options ou statuts candidats
devront citer les sources officielles rattachees. Une information reglementaire
non verifiee ne doit pas etre affirmee comme certaine.
