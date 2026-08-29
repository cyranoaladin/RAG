# Attestation de validation du corpus — Nexus

| | |
|---|---|
| **Décideur** | Alaeddine Ben Rhouma, opérateur de la plateforme, pour Nexus |
| **Date d'enregistrement** | 28 août 2026 |
| **Nature** | Enregistrement **a posteriori** d'une décision antérieure |
| **Portée** | L'intégralité du corpus pédagogique Nexus |
| **Référencée par** | ADR-0052 |
| **Effet en base** | `review_status = reviewed` — 26 placements, 730 chunks, 18 collections |

## Ce qui est attesté

L'opérateur atteste que **l'intégralité des documents du corpus a été lue et
validée par Nexus** avant leur ingestion, et que les documents actuellement
servis par la plateforme sont ceux qu'il a sélectionnés et retenus.

Cette attestation vaut pour :

- les **26 documents** déjà ingérés et servis, énumérés ci-dessous par empreinte
  de contenu ;
- **le corpus complet** destiné à l'ingestion, dont ces 26 documents sont un
  sous-ensemble.

La décision de retenir ces contenus est **antérieure** à leur ingestion. Ce
document ne la crée pas : il l'**enregistre**, à la date du 28 août 2026, dans
la forme écrite qui lui manquait.

## Pourquoi cet enregistrement était nécessaire

Le script d'ingestion inscrivait un littéral `"reviewed"` dans ses deux INSERT.
La base portait donc l'affirmation qu'une décision humaine avait eu lieu, sans
qu'aucune trace n'en existe. Le contrat est explicite : `REVIEWED` signifie
« la décision humaine a été validée », là où `RETRIEVAL_ELIGIBLE` n'est qu'un
constat automatique.

**La décision existait ; c'est sa trace qui manquait.** L'écart n'était pas une
fausse affirmation, mais une affirmation non adossée. Ce document ferme cet
écart, et le paramètre `--review-status` — désormais requis et sans défaut —
empêche qu'il se rouvre : chaque ingestion future devra déclarer explicitement
ce qu'elle affirme.

## Portée exacte de ce que cette attestation établit

Par honnêteté envers le lecteur futur, la distinction est posée nettement :

- **Ce qu'elle établit** : un décideur nommé, une décision humaine réelle, une
  portée déclarée, une date d'enregistrement.
- **Ce qu'elle n'établit pas** : elle n'est pas une revue *pièce par pièce
  horodatée*. Elle atteste globalement, ce qui est la forme qu'a effectivement
  prise la décision — un opérateur constituant son propre corpus de référence.

Les deux énoncés valent ensemble. Consigner le second n'affaiblit pas le
premier : il empêche que ce document devienne à son tour un contrôle qui
affirme plus qu'il n'a vérifié.

## Les 18 collections concernées

`rag_nexus_dgemc_terminale_option`, `rag_nexus_francais_premiere_tc`,
`rag_nexus_francais_quatrieme_tc`, `rag_nexus_francais_seconde_tc`,
`rag_nexus_hlp_premiere_specialite`, `rag_nexus_maths_premiere_gen_specialite`,
`rag_nexus_maths_quatrieme_tc`, `rag_nexus_maths_seconde_tc`,
`rag_nexus_maths_terminale_gen_specialite`, `rag_nexus_nsi_premiere_specialite`,
`rag_nexus_nsi_terminale_specialite`, `rag_nexus_pc_premiere_specialite`,
`rag_nexus_pc_terminale_specialite`, `rag_nexus_philo_terminale_tc`,
`rag_nexus_ses_premiere_specialite`, `rag_nexus_ses_terminale_specialite`,
`rag_nexus_svt_premiere_specialite`, `rag_nexus_svt_terminale_specialite`.

## Les 26 documents validés

Empreintes relevées dans la base canonique (projet Compose `nexusrag`) le
28 août 2026. Elles sont vérifiables : `content_sha256` de `rag_artifacts`,
joint aux placements.

| # | `content_sha256` | Collection | Document |
|---|---|---|---|
| 1 | `e591a87aee633ca3b2593e2d4fd5b183e518ebe0f9d4861e4cdfe0f494f39439` | `rag_nexus_dgemc_terminale_option` | telechargez-le-programme-de-dgemc-en-terminales-generale-et-technologique-pdf-930-41-ko.pdf |
| 2 | `b88b5c685ec05d44b0c22d64f491443759fc0f544fe9ad33e626fb6cc29bf65a` | `rag_nexus_francais_premiere_tc` | premieres-generale-et-technologique-bo-special-n-1-du-22-janvier-2019-modifie-en-2020-pdf-279-4-ko.pdf |
| 3 | `73c001b93cf2151924da5245c4d740b56a5194c17e29c37cda2e1c0593711fae` | `rag_nexus_francais_quatrieme_tc` | attendus-de-fin-d-annee-en-francais-en-4e-pdf-1-05-mo.pdf |
| 4 | `b54b6422d0eb2fb906e6ad6c79a2e95e6cae00e3fa113da5f7499eee4cc53ae7` | `rag_nexus_francais_seconde_tc` | seconde-generale-et-technologique-bo-special-n-1-du-22-janvier-2019-modifie-en-2020-pdf-275-51-ko.pdf |
| 5 | `c4e3cc6fb201f4dabc78fa47206c1b498b3ed46496cf05165a74e0ecd8856fb1` | `rag_nexus_francais_seconde_tc` | fiche-c-enseigner-explicitement-la-comprehension-de-l-ecrit-ou-des-ecrits.pdf |
| 6 | `4433fee96b6e803c71edf2764d99bd269e649dcff646aee97327fdfeed143f13` | `rag_nexus_hlp_premiere_specialite` | exemple-de-sujet-commente-sujet-zero-n-2-sur-le-theme-de-la-parole-pdf-153-37-ko.pdf |
| 7 | `60eeb7dd1ee55d1ed2bb2c7671ecf3c971aeef6996db2bc7cd9c7919ae4b19ac` | `rag_nexus_hlp_premiere_specialite` | litterature-l-apprentissage-de-l-oral-au-service-de-l-etude-des-textes-pdf-211-27-ko.pdf |
| 8 | `64f5b3427dee3b23d421fe03cb2f3aac75e0e47cee31be91b197d4e09c012987` | `rag_nexus_hlp_premiere_specialite` | philosophie-l-apprentissage-de-l-oral-au-service-de-l-etude-des-textes-pdf-157-47-ko.pdf |
| 9 | `9357dfdebca347264787dfebacb674666d87660b82f789657ddd230c7ff224aa` | `rag_nexus_hlp_premiere_specialite` | exemple-de-sujet-commente-sujet-zero-n-3-sur-le-theme-des-representations-du-monde-pdf-172-29-ko.pdf |
| 10 | `5303df0fcf6335f06d00c969a61dcd82cc3fdfd105271ae5c2ef580ff49b6c08` | `rag_nexus_maths_premiere_gen_specialite` | programme-d-enseignement-de-specialite-de-mathematiques-de-la-classe-de-premiere-de-la-voie-generale.pdf |
| 11 | `d0edabd6a21d6345d36d32c5506ddcf225e819ddca25d27c1ecc3f97b87a8966` | `rag_nexus_maths_quatrieme_tc` | attendus-de-fin-d-annee-en-mathematiques-en-4e-pdf-1-47-mo.pdf |
| 12 | `05c5403d45bfc3631fa13b5c334822de09bcd68d850d0611044045cddba270de` | `rag_nexus_maths_seconde_tc` | programme-d-enseignement-de-mathematiques-de-la-classe-de-seconde-generale-et-technologique.pdf |
| 13 | `eb8369e7c1611e90f51491fecc5a7c2081a9c57f9c7fbb08d0414677b56ce16f` | `rag_nexus_maths_terminale_gen_specialite` | specialite-de-terminale-generale-bo-special-n-8-du-25-juillet-2019-pdf-475-8-ko.pdf |
| 14 | `7ca9a32e1823be6c1120cb0417324c3cb01688d1d194c7614a88ea851ccc60b0` | `rag_nexus_nsi_premiere_specialite` | specialite-numerique-et-sciences-informatiques-en-premiere-bo-special-n-1-du-22-janvier-2019-pdf-300-73-ko.pdf |
| 15 | `10ce34666edd722a3d8d86642a9f1ac205c7a9d128d6142a17effcba2fb85e69` | `rag_nexus_nsi_terminale_specialite` | specialite-numerique-et-sciences-informatiques-en-terminale-bo-special-n-8-du-25-juillet-2019-pdf-196-38-ko.pdf |
| 16 | `db43d342edf55e162d0153028b43287e4ece0ce81b4dc75f0730bf368b98c0f0` | `rag_nexus_pc_premiere_specialite` | specialite-de-premiere-generale-bo-special-n-1-du-22-janvier-2019-pdf-383-44-ko.pdf |
| 17 | `c07f8b2db9d22a6c2b9ab8386cf7ba323bc2c56abacb3f560dd97d02b383de18` | `rag_nexus_pc_terminale_specialite` | specialite-de-terminale-generale-bo-special-n-8-du-25-juillet-2019-pdf-527-5-ko.pdf |
| 18 | `03f268dc1f2628dbc76c58921ed868624437f06a15432ea055fff844f12aaf91` | `rag_nexus_philo_terminale_tc` | l-evaluation-des-travaux-en-classe-de-philosophie-pdf-136-84-ko.pdf |
| 19 | `846962c15217af5cfe7ba40b173e94cb225d2153ffd3131d23b2c60a2b5e9a17` | `rag_nexus_philo_terminale_tc` | les-exercices-en-classe-de-philosophie-pdf-171-6-ko.pdf |
| 20 | `b5ed52b1a4754298f7ecdbc56cb886a438c580ebd04284be0ca878b82e7c62db` | `rag_nexus_philo_terminale_tc` | recommandations-concernant-le-travail-dans-les-classes-de-philosophie-pdf-136-23-ko.pdf |
| 21 | `e7cf3bdb7a1c3831ccc465d842d8ab0dacb688d565cb35510aee4eac4f2bf5f9` | `rag_nexus_philo_terminale_tc` | l-etude-des-textes-et-des-uvres-en-classe-de-philosophie-pdf-150-99-ko.pdf |
| 22 | `f0dec90cafd512cb754fb71ed33dbf0a48f0e67a166be35b5b16a1daa6dd006d` | `rag_nexus_philo_terminale_tc` | la-construction-des-cours-notions-auteurs-reperes-pdf-184-72-ko.pdf |
| 23 | `06e491d369c5164d9f746176edeef45363cef53d3de2d5fb55153e6e96f98f2e` | `rag_nexus_ses_premiere_specialite` | specialite-ses-de-premiere-generale-bo-special-n-1-du-22-janvier-2019-pdf-174-71-ko.pdf |
| 24 | `2f1035c74db485d12e80d7c887cb9090807be32e5f79a6074d2decb1073ec154` | `rag_nexus_ses_terminale_specialite` | specialite-ses-de-terminale-generale-bo-special-n-8-du-25-juillet-2019-pdf-193-63-ko.pdf |
| 25 | `8eb0e41f95bf4aca37e6231c06109579faf6bf410d6bd2bc210574e66e2762fa` | `rag_nexus_svt_premiere_specialite` | specialite-svt-de-premiere-generale-bo-special-n-1-du-22-janvier-2019-pdf-405-48-ko.pdf |
| 26 | `d2cbd06f2e8099d9080f17f3abb5b0fc90460b86b3c11f808b99daa01f77f897` | `rag_nexus_svt_terminale_specialite` | specialite-svt-de-terminale-generale-bo-special-n-8-du-25-juillet-2019-pdf-455-06-ko.pdf |
Tous proviennent du fonds **Éduscol officiel** (programmes, attendus de fin
d'année, ressources d'accompagnement, sujets zéro commentés).

## Vérification

```bash
docker exec nexusrag-pgvector-1 psql -U raguser -d ragdb -tAc "
  SELECT review_status, count(*) FROM rag_artifact_placements GROUP BY 1;"
# attendu : reviewed | 26
```

## Ce qui s'appuie sur ce document

- **ADR-0052** le référence comme trace de la décision de revue.
- L'invocation d'ingestion passe `--review-status reviewed` **adossée à cette
  attestation** : c'est elle qui autorise la valeur, non un défaut de code.
- Toute ingestion ultérieure sous `reviewed` doit pouvoir se rattacher à une
  attestation — celle-ci, ou une suivante déposée dans `docs/reviews/`.
