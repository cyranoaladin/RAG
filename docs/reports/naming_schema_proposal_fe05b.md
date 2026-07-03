# Proposition de schema de nommage -- extension de `rag_nexus_{matiere}_{niveau}_{statut}`

> Document de recherche (FE-05b). Ne pas merger. A soumettre au lead pour decision.

---

## 1. Les 5 dimensions identifiees

1. **Matiere** (ex. `nsi`, `maths`, `pc`, `francais`, `hggsp`...)
2. **Niveau** (`3e`, `2de`, `1re`, `tle`)
3. **Voie** (`gen`, `stmg`, `college`)
4. **Type d'enseignement** (`tc`, `specialite`, `option`, `specifique`)
5. **Dispositif/type de ressource** (`cours`, `annales`, `grand_oral`, `ece`, `dnb`...)
6. **Session** (`s2026`, `s2027`, `stable`)

---

## 2. Produit cartesien : evaluation de l'explosion combinatoire

Estimation du nombre de collections si toutes les dimensions sont encodees dans le nom :

- Matieres significatives : ~20 (en comptant les sous-options STMG, les arts, les LLCER par langue)
- Niveaux : 4
- Voies : 3
- Types d'enseignement : 4
- Dispositifs : ~13
- Sessions : 3

Produit brut maximal : 20 x 4 x 3 x 4 x 13 x 3 = **37 440** combinaisons.

En pratique, les combinaisons valides sont bien moindres (ex. pas de "HGGSP en 3e", pas de "specialite en 2de"), mais on peut estimer entre **200 et 500 collections reelles**. C'est excessif pour un systeme de retrieval ou chaque collection a un overhead (index, maintenance, monitoring).

---

## 3. Analyse des tensions

### 3.1. Nommage plat vs. metadonnees de chunk

| Approche | Avantages | Inconvenients |
|---|---|---|
| **Tout dans le nom** (`rag_nexus_nsi_tle_gen_specialite_annales_s2027`) | Routage trivial, isolation physique, pas de filtrage necessaire. | Explosion combinatoire, collections quasi vides, maintenance lourde, noms illisibles. |
| **Tout en metadonnees** (une seule collection `rag_nexus_education`) | Simple, pas de proliferation. | Filtrage couteux a l'execution, pas d'isolation, risque de pollution croisee entre niveaux/voies. |
| **Hybride** (2-3 dimensions dans le nom, le reste en metadonnees) | Equilibre entre isolation pertinente et maintenabilite. Routage par nom pour les dimensions a fort pouvoir de discrimination, filtrage par metadonnees pour les dimensions secondaires. | Necessite de definir clairement la frontiere. |

### 3.2. Criteres de decision : qu'est-ce qui va dans le nom ?

Une dimension merite d'etre dans le nom de collection si :

1. **Fort pouvoir de discrimination** : les contenus sont radicalement differents d'une valeur a l'autre (un cours de NSI n'a rien a voir avec un cours de francais).
2. **Volume significatif** : assez de chunks pour justifier une collection separee.
3. **Besoin d'isolation** : on veut garantir qu'un retrieval ne melange jamais certaines valeurs (ex. ne jamais retourner du contenu STMG a un eleve de voie generale, sauf demande explicite).
4. **Stabilite** : la dimension ne change pas souvent (le niveau est stable, la session change chaque annee).

Evaluation par dimension :

| Dimension | Discrimination | Volume | Isolation | Stabilite | Verdict |
|---|---|---|---|---|---|
| **Matiere** | Tres fort | Fort | Fort | Stable | **NOM** |
| **Niveau** | Fort | Moyen | Fort | Stable | **NOM** |
| **Voie** | Fort (gen vs stmg) | Moyen | Fort | Stable | **NOM** (sauf college = implicite avec niveau 3e) |
| Type d'enseignement | Moyen | Variable | Moyen | Stable | **METADATA** (sauf cas maths, ou la distinction tc/spe/option est critique -- le routage par matiere suffit si on a des slugs distincts : `maths_tc`, `maths_spe`, `maths_comp`, `maths_exp`) |
| Dispositif/ressource | Faible (cours et annales sur le meme programme) | Variable | Faible | Stable | **METADATA** |
| Session | Faible (meme contenu, coefficients differents) | Faible | Faible | **Instable** (change chaque annee) | **METADATA** |

---

## 4. Recommandation

### Schema propose

```
rag_nexus_{matiere}_{niveau}_{voie}_{statut}
```

Ou :
- `{matiere}` : slug normalise de la matiere (voir tableau dimension 3 du document FE-05a). Pour les matieres qui changent de nature, utiliser des slugs distincts : `maths` (spe), `maths_tc` (tronc commun STMG ou ens. scientifique), `maths_comp` (option complementaires), `maths_exp` (option expertes).
- `{niveau}` : `3e`, `2de`, `1re`, `tle`.
- `{voie}` : `gen`, `stmg`. Omis pour `3e` et `2de` (pas de voie a ce stade, ou implicite).
- `{statut}` : `specialite`, `tc`, `option` -- **seulement si la matiere est ambigue** (ex. maths). Pour la majorite des EDS, le statut est implicite (HGGSP est toujours une specialite). On pourrait l'omettre quand non ambigu.

### Exemples concrets

| Collection | Contenu |
|---|---|
| `rag_nexus_nsi_tle_gen_specialite` | NSI terminale voie generale (cours + annales + pratique) |
| `rag_nexus_nsi_1re_gen_specialite` | NSI premiere voie generale |
| `rag_nexus_maths_tle_gen_specialite` | Maths specialite terminale gen |
| `rag_nexus_maths_1re_gen_tc` | Maths tronc commun (ens. scientifique) premiere gen |
| `rag_nexus_maths_tle_gen_option` | Maths complementaires + maths expertes terminale (ou 2 collections separees) |
| `rag_nexus_maths_1re_stmg_tc` | Maths tronc commun premiere STMG |
| `rag_nexus_francais_3e_tc` | Francais 3e (pas de voie) |
| `rag_nexus_droiteco_tle_stmg_specialite` | Droit et economie terminale STMG |
| `rag_nexus_msdgn_tle_stmg_specialite` | MSDGN terminale STMG (les 4 enseignements specifiques en metadata) |
| `rag_nexus_philosophie_tle_gen_tc` | Philosophie terminale gen |
| `rag_nexus_grand_oral` | Collection transversale Grand oral (niveau+voie+session en metadata) |
| `rag_nexus_dnb` | Collection transversale DNB (matiere en metadata) |

### Metadonnees de chunk (toujours presentes)

Les dimensions NON encodees dans le nom doivent etre systematiquement presentes dans les metadonnees de chaque chunk :

```yaml
metadata:
  matiere: "nsi"
  niveau: "tle"
  voie: "gen"
  type_enseignement: "specialite"   # tc | specialite | option | specifique
  dispositif: "annales"             # cours | annales | grand_oral | ece | pratique_nsi | eaf | eam | dnb | indiv | rattrapage | projet_stmg
  session: "s2027"                  # s2026 | s2027 | stable
  enseignement_specifique: null     # gestion_finance | mercatique | rhc | sig (STMG uniquement)
  sous_option_arts: null            # arts_plastiques | cinema_av | danse | hist_arts | musique | theatre | cirque
  langue_llcer: null                # allemand | anglais | anglais_amc | espagnol | italien | portugais | ...
```

### Estimation du nombre de collections

Avec ce schema, on obtient environ **50 a 80 collections** pour couvrir l'ensemble du referentiel (toutes matieres x niveaux x voies pertinents). C'est un nombre gerable qui :

- permet un routage rapide par nom de collection,
- evite les collections vides ou quasi vides,
- maintient l'isolation entre matieres/niveaux/voies,
- delegue le filtrage fin (dispositif, session, enseignement specifique) aux metadonnees, ou le cout de filtrage est faible sur des collections deja bien ciblees.

---

## 5. Questions ouvertes pour le lead

1. **Grand oral et DNB** : collections transversales (1 chacune, filtrage par metadata) ou eclatement par matiere/niveau ?
2. **Maths en 4 slugs** (`maths`, `maths_tc`, `maths_comp`, `maths_exp`) ou en 1 slug avec `type_enseignement` en metadata ?
3. **Voie en 2de** : la 2de est commune (gen+techno). Faut-il la tagger `gen_techno` ou omettre la voie ?
4. **Enseignements specifiques STMG** (gestion-finance, mercatique, RHC, SIG) : metadata dans `rag_nexus_msdgn_tle_stmg_specialite`, ou 4 collections separees ?
5. **Collections transversales pour candidats individuels** : une collection `rag_nexus_indiv` ou un flag metadata `candidat_individuel: true` dans les collections existantes ?
6. **Limite de collections dans pgvector** : verifier que 50-80 collections ne posent pas de probleme de performance avec le backend cible.

---

## 6. Gouvernance du champ session (FE-05c, D-SESSION-DECLAREE-JAMAIS-DEVINEE)

### Regle de remplissage

Le champ `session` est une metadonnee de chunk a **forte consequence pedagogique** : un coefficient faux est pire qu'un coefficient absent. Un eleve qui prepare le grand oral avec un coef 10 alors que sa session est S2027 (coef 8) est induit en erreur.

**Regle** :

1. **Si la source porte explicitement la session** (le referentiel marque `[S2026]` ou `[S2027]`, un sujet de bac porte la session dans son en-tete, un arrete mentionne la session d'application) : on reprend la valeur declaree.
2. **Sinon** : `session = NULL` + `review_status = needs_review` + flag `session_a_qualifier = true`. **Jamais** une valeur devinee depuis le contenu (un cours de maths ne "ressemble" pas a une session).
3. Un agent autonome ne qualifie **jamais** la session. C'est un acte de revue humaine (enseignant).

### Impact retrieval

| Situation | Comportement |
|---|---|
| Eleve filtre par session (ex. "coefficients S2027") | Seuls les chunks avec `session = 's2027'` sont retournes. Les chunks `session = NULL` sont **exclus** du filtre session — ils ne font pas autorite sur un coefficient session-dependant. |
| Recherche sans filtre session | Tous les chunks sont retournes (le contenu pedagogique hors coefficients est stable entre sessions). |
| Chunk `session = NULL` + `session_a_qualifier = true` | Servi normalement pour le contenu pedagogique, mais **jamais** comme source autorisee pour un coefficient ou une modalite d'examen session-dependante. Le flag signale au reviewer humain qu'il reste a qualifier. |

### Champs concernes par session

Seuls certains elements changent entre S2026 et S2027 :
- Coefficients du grand oral (10→8 gen, 14→12 stmg)
- Existence/absence de l'epreuve anticipee maths
- Modalites de rattrapage maths anticipees

Le contenu de cours (programme, notions) est **identique** entre sessions. La session ne qualifie pas le contenu mais les **modalites d'evaluation**.

---

## 7. Perimetre v1 et extensibilite des series (FE-05d, D-PERIMETRE-EXPLICITE)

### Perimetre v1 declare

Le perimetre v1 de la taxonomie couvre :
- **Voie generale** : 13 EDS, tronc commun, options (maths complementaires/expertes, DGEMC, LVC, LCA, arts, EPS)
- **Voie technologique STMG** : EDS fixes (SGN, management, droit-eco, MSDGN), tronc commun STMG
- **College 3e** : tronc commun unique, DNB

**Hors scope v1** (decide, pas oublie) :
- ST2S, STI2D, STL, STD2A, STHR, S2TMD — non detaillees dans le referentiel source
- Voie professionnelle — hors perimetre Nexus v1

### Extensibilite de la convention de nommage

L'axe `{voie}` dans `rag_nexus_{matiere}_{niveau}_{voie}_{statut}` est un slug libre. Ajouter une serie technologique = ajouter un nouveau slug de voie :

| Serie | Slug voie | Exemple de collection |
|---|---|---|
| Generale | `gen` | `rag_nexus_maths_tle_gen_specialite` |
| STMG | `stmg` | `rag_nexus_droiteco_tle_stmg_specialite` |
| ST2S (futur) | `st2s` | `rag_nexus_biophys_tle_st2s_specialite` |
| STI2D (futur) | `sti2d` | `rag_nexus_i2d_tle_sti2d_specialite` |
| STL (futur) | `stl` | `rag_nexus_biochimie_tle_stl_specialite` |

Aucune collection STMG existante ne collisionne avec une future serie : le slug `stmg` est un segment distinct dans le nom, et les matieres STMG (`droiteco`, `msdgn`, `sgn`, `management`) sont specifiques a cette serie. Un futur `rag_nexus_maths_tle_st2s_tc` ne collisionne pas avec `rag_nexus_maths_tle_stmg_tc`.

### Verification anti-collision

| Collection STMG | Future collection autre serie | Collision ? |
|---|---|---|
| `rag_nexus_maths_1re_stmg_tc` | `rag_nexus_maths_1re_st2s_tc` | Non (voie differente) |
| `rag_nexus_maths_tle_stmg_tc` | `rag_nexus_maths_tle_sti2d_tc` | Non (voie differente) |
| `rag_nexus_droiteco_tle_stmg_specialite` | — | Matiere specifique STMG, pas de risque |
| `rag_nexus_msdgn_tle_stmg_specialite` | — | Matiere specifique STMG, pas de risque |

**Conclusion** : la convention est extensible sans refonte. L'ajout d'une serie = nouveaux slugs voie + matieres specifiques, sans collision.

---

## 8. Maths multi-nature : routage sans ambiguite (FE-05e)

### Le probleme

"Mathematiques" designe 4 realites pedagogiques distinctes selon le contexte :

| Nature | Niveau | Voie | Type ens. | Programme |
|---|---|---|---|---|
| Maths TC college/lycee | 3e, 2de | college, gen+stmg | tc | Programme unique |
| Maths TC STMG | 1re, Tle | stmg | tc | Programme specifique STMG (3 h) |
| Maths ens. scientifique | 1re gen (sans spe) | gen | tc | 1h30 integree, sujet anticipe [S2027] |
| Maths specialite | 1re, Tle | gen | specialite | Programme EDS (4 h → 6 h) |
| Maths complementaires | Tle | gen | option | Pour eleves SANS spe maths (3 h) |
| Maths expertes | Tle | gen | option | Pour eleves AVEC spe maths (3 h) |

Un document "maths" doit router vers la **bonne** collection, pas seulement par le mot "maths".

### Regle de routage

Le routage se fait par le triplet **(niveau, voie, type_enseignement)**, pas par le seul slug matiere :

| Document | niveau | voie | type_ens | Collection cible |
|---|---|---|---|---|
| Cours maths 3e | 3e | — | tc | `rag_nexus_maths_3e_tc` |
| Cours maths 2de | 2de | — | tc | `rag_nexus_maths_2de_tc` |
| Cours maths spe 1re | 1re | gen | specialite | `rag_nexus_maths_1re_gen_specialite` |
| Cours maths ens. scientifique 1re | 1re | gen | tc | `rag_nexus_maths_1re_gen_tc` |
| Cours maths TC STMG 1re | 1re | stmg | tc | `rag_nexus_maths_1re_stmg_tc` |
| Cours maths spe Tle | tle | gen | specialite | `rag_nexus_maths_tle_gen_specialite` |
| Cours maths complementaires Tle | tle | gen | option | `rag_nexus_maths_tle_gen_option_comp` |
| Cours maths expertes Tle | tle | gen | option | `rag_nexus_maths_tle_gen_option_exp` |
| Cours maths TC STMG Tle | tle | stmg | tc | `rag_nexus_maths_tle_stmg_tc` |

### Verification : pas de collision

**Exemple 1** : un cours de maths expertes Tle et un cours de maths TC 1re.
- Maths expertes → `rag_nexus_maths_tle_gen_option_exp` (niveau=tle, voie=gen, statut=option)
- Maths TC 1re → `rag_nexus_maths_1re_gen_tc` (niveau=1re, voie=gen, statut=tc)
- **Collections differentes** ✓ — pas de confusion possible.

**Exemple 2** : un cours de maths spe 1re et un cours de maths ens. scientifique 1re.
- Maths spe 1re → `rag_nexus_maths_1re_gen_specialite`
- Maths ens. scientifique 1re → `rag_nexus_maths_1re_gen_tc`
- **Collections differentes** ✓ — le statut (specialite vs tc) les separe.

**Exemple 3** : un cours de maths TC STMG 1re et un cours de maths spe gen 1re.
- Maths STMG 1re → `rag_nexus_maths_1re_stmg_tc`
- Maths spe gen 1re → `rag_nexus_maths_1re_gen_specialite`
- **Collections differentes** ✓ — la voie (stmg vs gen) ET le statut les separent.

### Implication pour l'ingestion

Le routage maths exige que **les 3 metadonnees (niveau, voie, type_enseignement)** soient renseignees a l'ingestion. Le mot "maths" seul est insuffisant. C'est coherent avec la regle F-01 : les metadonnees structurantes sont declarees, pas devinees.

Si un document de maths est ingere sans que la voie ou le type d'enseignement soit rensegne, il tombe en `needs_review` avec un flag signalant l'ambiguite — jamais route par defaut vers une collection arbitraire.

---

## 9. Conclusion

Le schema `rag_nexus_{matiere}_{niveau}_{voie}_{statut}` avec 3 a 4 segments dans le nom et le reste en metadonnees offre le meilleur compromis entre isolation, maintenabilite et lisibilite. Le produit cartesien reste sous controle (~50-80 collections) tout en permettant un filtrage fin par metadonnees sur les dimensions secondaires (dispositif, session, enseignement specifique).
