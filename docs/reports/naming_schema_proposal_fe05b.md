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

## 6. Conclusion

Le schema `rag_nexus_{matiere}_{niveau}_{voie}_{statut}` avec 3 a 4 segments dans le nom et le reste en metadonnees offre le meilleur compromis entre isolation, maintenabilite et lisibilite. Le produit cartesien reste sous controle (~50-80 collections) tout en permettant un filtrage fin par metadonnees sur les dimensions secondaires (dispositif, session, enseignement specifique).
