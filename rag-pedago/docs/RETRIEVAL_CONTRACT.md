# Contrat de retrieval

Le retrieval doit retourner des ressources pertinentes pour un profil eleve
donne, avec filtres forts, droits respectes et citations exploitables.

## Filtrage

Le filtrage doit passer par les payloads et metadonnees, pas par les dossiers.
L'ordre attendu pour les futurs lots est :

1. filtrage strict des payloads ;
2. recherche hybride dense et sparse ;
3. fusion et reranking ;
4. diversification ;
5. verification des droits ;
6. construction des citations.

## Profil eleve

Le profil distingue :

- `niveau` : classe ;
- `voie` : generale, technologique, college, AEFE, etc. ;
- `matieres` : disciplines suivies ;
- `statut_enseignement` : specialite, tronc commun, option ou examen ;
- `candidat` : scolarise, individuel, libre, CNED ou AEFE ;
- `school_year` et `zone` : contexte temporel et geographique.

Un candidat individuel peut recevoir des ressources generales utiles, mais les
documents strictement internes au controle continu ne devront pas etre
priorises sans demande explicite.

## Droits et citations

Une reponse publique ne doit jamais exposer une ressource proprietaire ou
restreinte. Une ressource `rights=unknown` doit etre bloquee. Chaque resultat
retrieval doit pouvoir porter un `chunk_id`, un `doc_id`, un extrait, une
citation et les metadonnees minimales permettant d'auditer la decision.

## Contextes d'exposition

Le retrieval devra evaluer au minimum le contexte de reponse :

- public ;
- interne Nexus ;
- eleve inscrit ;
- parent ;
- eleve proprietaire d'un document prive ;
- enseignant ;
- administrateur.

Un document `commercial_confidential` ne doit pas etre expose dans une reponse
parent. Un document `student_private` ne doit etre visible que par l'eleve
proprietaire ou un administrateur. Un document `nexus_proprietaire` peut etre
utile a un eleve inscrit, mais ne doit pas devenir une ressource publique.

## Confiance source

`SourceTrust` separe les sources officielles verifiees, officielles non
verifiees, validees Nexus, importees non verifiees, generees comme brouillon et
inconnues. Cette information devra etre combinee aux droits : une source de
confiance ne rend pas automatiquement un document exposable si ses droits ne le
permettent pas.

## Réponses réglementaires

Les futures reponses du RAG sur les examens, options, horaires, statuts
candidats et inscriptions devront citer les sources officielles liees au
referentiel `data/reference/`. Une source locale ou institutionnelle marquee
`verification_status: pending` ne doit pas etre presentee comme definitive.

Pour les candidats libres, le retrieval doit privilegier les ressources
autoportantes et signaler qu'une carte d'examen confirmee est necessaire avant
de conclure sur les epreuves obligatoires, les modalites ponctuelles ou les
documents a fournir.

## Claims officielles

Pour une réponse réglementaire, le retrieval devra préférer les résultats
adossés à un `OfficialClaim` vérifié. Si une information ne dispose que d'une
source `pending`, elle doit être signalée comme non confirmée et ne pas être
présentée comme une obligation définitive.

AEFE doit être traité comme un contexte d'établissement, pas comme un statut
candidat. Le filtrage candidat doit utiliser `scolarise`, `candidat_individuel`,
`cned_reglemente` ou `cned_libre`.
