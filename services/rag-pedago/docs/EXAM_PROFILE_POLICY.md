# Politique de profil d'examen

Le RAG pedagogique doit distinguer le profil d'apprentissage d'un eleve et sa
carte d'examen. Cette separation est essentielle pour Nexus Reussite, en
particulier pour les eleves AEFE, les candidats libres, les eleves en double
cursus et les situations CNED.

## Scolarise, candidat libre et double cursus

Un eleve scolarise suit en general une progression d'etablissement, avec des
documents internes, des controles et un calendrier connu. Un candidat libre ou
individuel doit preparer des epreuves ponctuelles et ne doit pas recevoir des
conseils qui supposent un controle continu interne. Un eleve en double cursus
peut avoir une progression pedagogique utile mais une carte d'examen differente
de celle d'un eleve scolarise en France.

## Carte d'examen obligatoire pour les candidats libres

Pour un candidat libre, la carte d'examen est une information critique :

- session ;
- zone ;
- centre d'examen ;
- statut d'inscription ;
- statut de convocation ;
- modalite ponctuelle A/B ;
- epreuves a passer ;
- epreuves deja validees ;
- options et specialites.

Sans cette carte, le RAG doit rester prudent et produire des warnings plutot
que conseiller une strategie d'examen definitive.

## Warnings

Les warnings signalent une incoherence ou une information manquante sans
bloquer necessairement l'usage pedagogique. Exemples :

- candidat libre sans modalite ponctuelle connue ;
- terminale generale avec moins de deux specialites ;
- premiere generale avec moins de trois specialites ;
- maths expertes sans specialite mathematiques ;
- maths complementaires alors que la specialite mathematiques est conservee.

En mode strict, ces warnings pourront devenir des erreurs avant une action
sensible, par exemple la generation d'un plan officiel de preparation examen.

## Autorite des convocations et textes officiels

Les convocations, inscriptions et textes officiels font foi. Le RAG ne doit pas
deduire seul qu'une epreuve est obligatoire si la carte d'examen ou les textes
ne le confirment pas. En cas d'incertitude, il doit remonter un warning et
orienter vers une verification officielle.

## Eviter les conseils d'epreuves non confirmees

Le retrieval et les futurs agents doivent filtrer les ressources par candidat,
epreuve, session et zone. Ils doivent eviter de recommander une epreuve
pratique, une option ou une modalite qui ne concerne pas le profil confirme de
l'eleve.

## Liaison avec le référentiel officiel

`ExamProfile` peut porter `official_level_ref`, `official_exam_ref` et
`candidate_status_ref`. Ces champs relient une carte d'examen individuelle aux
references officielles structurees dans `data/reference/`.

Pour les candidats libres, la carte d'examen confirmee est obligatoire avant
de donner une reponse definitive sur les epreuves a passer. Les informations
locales IFT/Tunisie marquees `verification_status: pending` doivent rester des
points a verifier manuellement par Nexus.

## Statut candidat et contexte d'établissement

Le statut candidat d'examen ne doit pas être confondu avec le contexte
d'établissement. AEFE, système tunisien, double cursus ou CNED décrivent le
contexte ; `scolarise`, `candidat_individuel`, `cned_reglemente` et
`cned_libre` décrivent la modalité d'examen.

Une réponse à un candidat libre doit s'appuyer sur une carte d'examen confirmée
et sur des claims officielles vérifiées. Sans cela, le RAG doit remonter un
warning et demander vérification.
