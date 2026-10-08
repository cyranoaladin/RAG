# Lot 45 — Paquet de revue pédagogique des oracles V4/V5

**Statut : décision pédagogique requise.** Ce document prépare une seule revue humaine des trois associations question–source contestées. Il ne modifie ni la suite scellée, ni les seuils, ni le retrieval. `QUALITY_PASS=false` reste le verdict de la mesure. Les observations du staging ci-dessous sont des faits **LIVE datés** : elles ne prouvent pas à elles seules l'état du staging au moment d'une décision ultérieure.

## Périmètre et provenance

| Élément | Valeur et portée |
| --- | --- |
| Base de cette PR | `0e47ea707c9dbdf68bc0c181e414da2577d4b332`, tree `b650b5096ad6e42e44c7b17d4ba08a1a7ce8846e` |
| Suite scellée | `services/rag-engine/tests/fixtures/final_v4_v5_acceptance.json`, SHA-256 `89faa10de47134f005c81bc71d8ee879d246af9a2be1d50276253cce4aba5419` |
| Runner | `scripts/go_live/final_retrieval_acceptance.py`, SHA-256 `a0c23e013f3f65563794d373bde90a4d0fcf8f95b7be0400b1b61423d1a6c78d` |
| Registre mixte | `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json`, SHA-256 `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6` |
| Manifeste V4 / V5 | SHA-256 `bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be` / `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf` |
| Mesure d'acceptation | Staging `nexus-staging`, base `ragdb_profile_gate_v4`, rapport opérateur `qualification/final-retrieval-1ab97183.json` produit le `2026-10-08T20:46:32Z` depuis le checkout `1ab971838e90c876bf185da03b67423f9f0a32c9`, SHA-256 du rapport `f955c112aa8686e3b96732e4290933eaa468445b75eff799419d3824fe2bd8a7`, verdict `fail` |
| Sonde dense liée | Rapport opérateur `qualification/dense-mixed-1ab97183.json` du `2026-10-08T20:44:19Z`, SHA-256 `dc7914f2756c0fa53a23b475a66b38f156288b75f7facc10e560ac23285cfe02`, 12 316 visites, 0 manque, 9 égalités débordantes ; empreinte des lignes de retrieval `b3a98b623a2bd08fb990f002edbcbf9fa8a9ae7d1f1a0610aaa9f2ed6d930d11` |
| Runtime des six rejouages ciblés | Image staging `sha256:00398ba7773e95fddbed7b088b083759182af70d2836d60d6056b258eefd588c` construite au checkout `4b62104d9887eb418b6c50b39cde9ddb6d55b884`. Les six requêtes signées ont reproduit les résultats du rapport avant que le checkout distant passe à `0e47ea70` ; l'image et la base n'ont pas été reconstruites pendant ce passage. Aucun de ces rejouages n'est une nouvelle qualification au SHA `0e47ea70`. |
| Vérification ciblée des sources | SQL `BEGIN READ ONLY` directement sur la base staging le `2026-10-08T21:36:15Z` : les sept artefacts cités ci-dessous ont droits `officiel_public`, placement `active`, `reviewed`, `official_snapshot`, visibilité `internal`. Les pages indiquées sont les `page_start`/`page_end` des chunks indexés. Auteur du diagnostic : `automated:Codex`; aucune décision pédagogique humaine n'a encore été enregistrée. |
| Sonde SQL reproductible | `docs/reports/lot_45_go_live_pedagogical_oracle_source_probe.sql`, SHA-256 `547e2072bd2bb47abe09b475908199a7c6ce77f1bb87bbc63c684e2e2d873527`. Sortie canonique à 18 lignes, SHA-256 `0c643de0668c66ac320510882f555b6bd8eca97d11bff686c66232547b614e29`. Identité DB liée à cette sortie : OID `416766`, `8268` chunks, `315` artefacts, `479` placements, dernier `indexed_at` `2026-10-08 06:27:31.940976+00`, dernier placement `2026-10-08 06:28:28.381843+00`. |

Le rapport d'acceptation couvre les 11 collections, 33 cas positifs et 33 négatifs. Ses totaux sont `positive_nonempty=28/33`, `expected_source_hits=27/33`, `out_of_scope_results=0`, `missing_citations=0`, `student_refusals=11/11`, `scope_mismatch_refusals=11/11`, `zero_result_pass=11/11`. La suite, le runner et les trois modules du pipeline (`retrieval_hybrid_v2.py`, `retrieval_pg_v2.py`, `retrieval_v2_endpoint.py`) ne diffèrent pas entre `1ab97183` et la base de cette PR. Les preuves HTTP restent néanmoins attribuées à leur image et à leur heure réelles, pas au nouveau checkout documentaire. Au moment de la sonde SQL, le checkout distant est `0e47ea70` (tree `b650b509`), tandis que l'image API reste celle construite depuis `4b62104d` ; il ne faut pas les présenter comme un runtime reconstruit au checkout distant.

Avant la décision pédagogique groupée, l'opérateur doit **relire en direct** le même staging, vérifier cible DB, image API, checkout et empreintes des manifests, puis rejouer la sonde SQL ci-dessous. Si la population, les sept sources, les quatre contrôles de substance ou les six comptes lexicaux diffèrent, il faut suspendre la décision sur cette version du paquet et réconcilier la preuve. La sonde n'écrit rien et ne remplace pas la recette HTTP finale.

Les **manifests finaux** V4 et V5 identifiés par les SHA-256 ci-dessus portent eux aussi `visibility=internal` et `currentness=official_snapshot` pour les placements ici examinés ; ces champs ont été relus dans les manifests de sujets de l'union finale. Une éventuelle visibilité `public` ou currentness `current` d'un référentiel source antérieur ne constitue pas la visibilité du placement final servi. La décision étudiante ne doit donc pas être inférée de ces référentiels ni des droits `officiel_public`.

Commande exacte depuis la racine du checkout sur l'hôte staging, avec les accès existants et sans afficher de secret :

```bash
docker exec -i nexus-staging-pgvector-1 sh -c 'exec psql -X -q -At -F "|" -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d ragdb_profile_gate_v4' < docs/reports/lot_45_go_live_pedagogical_oracle_source_probe.sql > lot45-evidence.out
sha256sum lot45-evidence.out
```

La sortie scellée contient la ligne d'identité `DB|ragdb_profile_gate_v4|416766|8268|315|479|…`, sept lignes `SOURCE`, puis `HLP1_SAME_CHUNK|0`, `HLPT_ARENDT_ARTIFACTS|2`, `HLPT_ARENDT_TRAVAIL_SAME_CHUNK|0`, `SVT_ORACLE_MUTAT_PROTEIN_SAME_CHUNK|0` et six lignes `LEXICAL|…|0`. Les contrôles négatifs sont des **tests lexicaux ciblés**, pas une preuve qu'aucune autre formulation pédagogique n'existe dans tout le corpus.

## Les trois décisions pédagogiques à prendre ensemble

### HLP première — distinguer « persuader » et « convaincre »

- **Question scellée** : « Quelle différence entre persuader et convaincre ? » Collection `rag_nexus_hlp_premiere_specialite`, cas `notion`.
- **Oracle actuel** : `e772ccd8d680588dcd898c2e10fd7603fa540027b4140f3c4318fc5d90badf8e`, *Une rhétorique à fonds multiples : jeux et enjeux de la parole en quatre études* (31 chunks, p. 1–12).
- **Preuve de substance** : p. 8, « Qui Cinna cherche-t-il à persuader ici ? » ; p. 9, analyse des moyens pathétiques ; p. 12, « convaincre Auguste de conserver le pouvoir » désigne l'effet d'un argument particulier. Les passages examinés ne démontrent pas la **différence** entre les deux notions. Le contrôle ciblé reproductible `HLP1_SAME_CHUNK|0` constate qu'aucun chunk revu et actif de cette collection ne contient conjointement les deux radicaux `persuad` et `convainc` ; il ne prouve pas qu'aucune autre formulation pédagogique n'existe.
- **Résultat observé** : HTTP 200, zéro résultat dans le rapport scellé et lors du rejouage ciblé. Le document attendu ressort pourtant pour la requête voisine sans accents de la même collection : son existence et son autorisation sont établies.
- **Décision humaine exacte** : **valider ou rejeter le constat que cet artefact ne prouve pas la distinction demandée**. Si rejet, fournir `content_sha256`, page(s) et passage qui l'enseigne explicitement. Si validé, désigner une autre source gouvernée avec page(s) opposables, ou déclarer une lacune de corpus ; une future suite devra alors définir un nouvel oracle pédagogique avant sa prochaine mesure.

### HLP terminale — « le travail chez Hannah Arendt »

- **Question scellée** : « Que signifie le travail chez Hannah Arendt ? » Collection `rag_nexus_hlp_terminale_specialite`, cas `notion`.
- **Oracle actuel** : `2ef53e02a4e1aff55d251484af299dc9a68831fc008a5003b8773cf88dfd323b`, *Sujet zéro n°4 commenté (extrait de « Condition de l'homme moderne », Hannah Arendt)* (11 chunks, p. 1–5).
- **Preuve de substance** : p. 2–4, l'extrait et le commentaire portent sur « l'artifice humain », la technique et la condition terrestre. Les deux chunks contenant « travail » dans cet artefact parlent par exemple du « cours du travail d'interprétation » et des compétences à travailler, non du concept arendtien. Seuls deux artefacts de cette collection mentionnent Arendt dans les chunks revus ; aucun chunk ne rapproche `Arendt` et `travail`. Aucun candidat de remplacement substantiel n'est établi dans le corpus final par ce contrôle ciblé.
- **Résultat observé** : HTTP 200, zéro résultat dans le rapport et lors du rejouage. Les cas factuel et sans accents, qui demandent la *Condition de l'homme moderne*, retrouvent bien l'artefact actuel ; cette réussite ne valide pas la question sur le travail.
- **Décision humaine exacte** : **valider ou rejeter le constat que l'oracle actuel traite un autre concept**. Si rejet, fournir `content_sha256`, page(s) et passage établissant la définition arendtienne du travail. Si validé, nommer une ressource gouvernée substantielle ou déclarer la lacune de corpus ; ne pas substituer une simple référence au titre de l'œuvre.

### SVT première — mutation de l'ADN et protéine

- **Question scellée** : « Comment une mutation de l'ADN peut-elle modifier une protéine ? » Collection `rag_nexus_svt_premiere_specialite`, cas `factual`.
- **Oracle actuel** : `1ea3df5ec2e428b297007de865ac550f1cee14a5eccea2ec65b07841b0f35d31`, *L'information génétique, sa transmission, son expression, sa variation* (19 chunks, p. 1–10).
- **Preuve de substance** : p. 5, « Les mutations sont des phénomènes aléatoires » ; p. 6, « triplets de nucléotides déterminant la séquence d'acides aminés ». Le lien causal demandé doit être reconstitué entre deux passages d'un guide de notions ; aucun des chunks de cet artefact ne contient conjointement `mutat` et `protéin`. Cela rend l'oracle discutable pour une question qui demande **comment** la mutation modifie la protéine.
- **Candidat gouverné plus direct, mais à réserver à la revue** : `3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6`, *Variation génétique et santé — Risque de transmission de la mucoviscidose…* (26 chunks, p. 1–13), même collection, droits `officiel_public`, placement `official_snapshot/reviewed/active/internal`. La p. 3 indique qu'un variant d'intron « modifie ainsi la protéine CFTR », puis précise que « cette subtilité n'est bien sûr pas à porter à la connaissance des élèves ». C'est un **exemple causal pour un enseignant**, pas une preuve que le passage puisse être servi tel quel au public étudiant. Les droits `officiel_public` ne valent ni autorisation de visibilité `student`, ni validation pédagogique de ce contenu pour les élèves.
- **Résultat observé** : HTTP 200, zéro résultat dans le rapport et lors du rejouage. L'oracle actuel est trouvé pour les cas sans accents et de notion du même sujet.
- **Décision humaine exacte** : **choisir si les p. 5–6 de l'oracle actuel suffisent à enseigner le lien causal demandé**. Sinon, décider séparément si le candidat CFTR p. 3 convient comme preuve **réservée à l'enseignant** et s'il peut, malgré l'avertissement explicite, alimenter un parcours **étudiant** ; à défaut, désigner une autre source substantielle adaptée aux élèves ou déclarer la lacune. Toute visibilité étudiante exige sa propre autorisation gouvernée. Le contenu de la future question et son expected source doivent être fixés et revus **avant** un nouveau run de qualité.

La revue peut rendre **une seule réponse APPROVED sur le HEAD exact**, avec les trois décisions suivantes, chacune accompagnée d'un `content_sha256` et de page(s) si elle conteste le constat ou désigne une nouvelle preuve. Le challenge trusted-human-review recalculé en direct doit être sur sa propre ligne dans le corps de cette même review. L'auteur déclaré ci-dessous est comparé au reviewer GitHub réellement authentifié ; après dépôt, l'opérateur conserve le login, l'identifiant, le commit revu et l'horodatage de la review retournés par GitHub. Un verdict anonyme n'est pas une autorisation :

```text
HLP_PREMIERE_DISTINCTION=ORACLE_INVALIDE | PREUVE_VALIDE_FOURNIE
HLP_TERMINALE_TRAVAIL=ORACLE_INVALIDE | PREUVE_VALIDE_FOURNIE
SVT_PREMIERE_MUTATION_PROTEINE=ORACLE_ACTUEL_SUFFISANT | CANDIDAT_CFTR_ENSEIGNANT_SEUL | CANDIDAT_CFTR_ETUDIANT_APPROUVE_AVEC_JUSTIFICATION | AUTRE_PREUVE_REQUISE
DECISION_AUTHOR_GITHUB=<login du réviseur pédagogique habilité>
```

`ORACLE_INVALIDE` n'autorise pas une suppression opportuniste du cas : il ouvre une décision de contenu et une nouvelle version scellée de la suite. Aucune de ces décisions ne transforme rétroactivement le rapport rouge en vert.

## Trois défauts sur des questions à source substantielle

| Cas scellé | Source attendue et passage probant | Résultat réel | Qualification |
| --- | --- | --- | --- |
| HGGSP terminale, `factual` : « Quelles formes prennent les conflits armés contemporains ? » | `50cdfb015febbbc184334b3ff66162b3e2ca234c29d2d3bd9051fd16142a82bf`, *Faire la guerre, faire la paix…*, p. 7 : « guerres civiles, des conflits intra-étatiques » ; le passage explique aussi les logiques criminelles/idéologiques. Source substantielle V5 (109 chunks). | HTTP 200, zéro résultat deux fois ; les cas sans accents et de notion retrouvent cet artefact. | **Défaut de retrieval**, pas absence de corpus. |
| HLP première, `factual` : « Comment la rhétorique aide-t-elle à convaincre un auditoire ? » | `e772ccd8d680588dcd898c2e10fd7603fa540027b4140f3c4318fc5d90badf8e`, p. 9 : « moyens que la rhétorique met au service du pathétique » ; le passage analyse figures, questions et persuasion. Source pédagogique concrète, même si le mot « auditoire » n'y apparaît pas. | HTTP 200, zéro résultat deux fois ; le cas sans accents retrouve cet artefact. | **Défaut de retrieval** pour une demande de procédés, sans garantir que la source suffise à une définition abstraite de « convaincre ». |
| SES première, `notion` : « Qu'est-ce que l'équilibre concurrentiel ? » | `202ef17f4c78e680b41ea2feda10cbb28e01b3f6f170d8c4e958bdb89708ef14`, *Comment un marché concurrentiel fonctionne-t-il ?*, p. 3 : « Le prix d'équilibre sur un marché concurrentiel » résulte de la confrontation offre/demande, illustrée par l'intersection des courbes. | Un seul résultat, `06e491d369c5164d9f746176edeef45363cef53d3de2d5fb55153e6e96f98f2e`, p. 3, programme général qui **mentionne** l'équilibre ; score de reranking `2.4456887245`. La source plus explicative attendue manque. | **Défaut de sélection/qualité du classement**, pas absence de corpus ni citation manquante. |

Le SQL lexical canonique (`plainto_tsquery('french', question)`) ne retourne **aucun chunk** pour ces six questions dans leur collection. Il impose notamment `quel`, `comment`, `aide-t-el` ou `est-ce` comme termes obligatoires ; de plus, le passage « d’équilibre » est indexé `d’équilibr` alors que la requête « équilibre » donne `équilibr`. Dans le pipeline actuel, une réponse vide peut survenir **avant** le reranking si la fusion ne produit aucun candidat, ou **après** si tous les scores restent sous le seuil inclusif de `1.90`. Les HTTP 200 ne distinguent pas ces chemins et aucun logit par candidat n'a été mesuré ici ; la cause précise de ces cinq vides reste à établir par diagnostics de canaux ciblés. La sonde exhaustive dense prouve l'absence de manque sur ses 12 316 visites, pas le rappel des six requêtes pédagogiques. Changer la normalisation lexicale, les candidats, le classement ou le seuil constituerait une évolution de sémantique : **ADR → tests → golden complète scellée avant mesure → charge C0 à nouveau**.

## Conséquence opérationnelle

Ce paquet ne constitue ni `QUALITY_PASS`, ni qualification du chemin Cockpit/BFF, ni autorisation de visibilité étudiant. Les sources citées restent `internal`. La prochaine revue doit statuer sur les trois oracles contestés dans une seule décision pédagogique, puis un lot technique séparé pourra traiter les défauts de retrieval démontrés sans abaisser a posteriori les critères d'acceptation.
