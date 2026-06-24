# Protocole de corpus pilote — Mathématiques terminale spécialité

## 1. Objectif du corpus pilote

Le corpus pilote doit préparer un premier lot contrôlé de ressources de
mathématiques terminale spécialité pour vérifier, plus tard, la chaîne complète
manifest → qualité → readiness → coverage → gate → review → import contrôlé.

Le présent protocole ne lance aucune ingestion documentaire. Il décrit comment
préparer les métadonnées et les contrôles avant un futur lot dédié.

Objectifs du futur corpus :

- vérifier que les métadonnées permettent un filtrage par profil élève ;
- couvrir les notions prioritaires de terminale spécialité ;
- distinguer ressources internes, ressources officielles et documents d'examen ;
- préparer des requêtes de validation cockpit ;
- conserver une traçabilité droits, provenance et références officielles.

## 2. Périmètre pédagogique

Profil cible :

- niveau : `terminale` ;
- voie : `generale` ;
- enseignement : spécialité mathématiques ;
- zone : AEFE Tunisie ;
- statut candidat : scolarisé ;
- contexte d'établissement : `aefe` si applicable ;
- épreuve principale : `bac_specialite_ecrit`.

Types de ressources visés :

- programme officiel ou référence officielle ;
- cours ;
- fiche méthode ;
- exercices ;
- corrigés ;
- annales ou sujets de type bac ;
- barème si disponible.

Notions prioritaires minimales :

- `suites` ;
- `recurrence` ;
- `limites_de_suites` ;
- `fonction_exponentielle` ;
- `fonction_logarithme` ;
- `integrales` ;
- `probabilites_conditionnelles` ;
- `loi_binomiale` ;
- `geometrie_espace_vecteurs` ;
- `algorithmique_python`.

## 3. Documents autorisés

Sont autorisés pour un futur lot d'import contrôlé :

- documents internes Nexus explicitement autorisés ;
- documents produits par Nexus et qualifiés `nexus_proprietaire` ou
  `usage_interne` ;
- documents officiels publics avec provenance et référence institutionnelle ;
- documents d'examen ou annales dont la source, les droits et la session sont
  identifiés ;
- documents fournis localement par un humain dans un dossier de staging dédié.

Chaque document doit avoir un statut de droit, une visibilité et une provenance
avant toute inclusion dans un manifest.

## 4. Documents interdits

Sont interdits :

- manuels commerciaux protégés sans autorisation ;
- documents payants ou derrière authentification ;
- copies d'élèves non anonymisées ;
- fichiers issus du RAG historique copiés sans validation ;
- fichiers `.env`, credentials, exports privés ou uploads sensibles ;
- documents dont les droits sont inconnus si l'objectif est retrieval ;
- documents obtenus par scraping ou téléchargement non validé.

Un document avec `rights=unknown` peut être représenté pour audit, mais il doit
être bloqué avant retrieval et ne doit pas être considéré comme exploitable.

## 5. Métadonnées obligatoires

Chaque ligne de manifest doit pouvoir valider un `DocumentMeta`.

Champs minimaux :

- `doc_id` ;
- `source_uri` ;
- `source_type` ;
- `sha256` ;
- `rights` ;
- `visibility` ;
- `matiere` ;
- `type_doc` ;
- `discovered_at`.

Champs pédagogiques attendus :

- `niveau: terminale` ;
- `voie: generale` ;
- `matiere: mathematiques` ;
- `statut_enseignement: specialite` ;
- `candidat: scolarise` ;
- `epreuve` adaptée au document ;
- `programme_version` ;
- `bo_reference` si connu ;
- `notions` ;
- `competences`.

Champs de référentiel officiel attendus pour documents officiels, réglementaires
ou d'examen :

- `official_level_ref` ;
- `official_subject_ref` ;
- `official_exam_ref` si document d'examen ;
- `candidate_status_ref` ;
- `establishment_context_ref` si AEFE ;
- `official_source_refs` ou `official_claim_refs`.

## 6. Structure de manifest attendue

Le système actuel lit des JSONL validés contre `DocumentMeta`. Un fichier YAML
de préparation peut être utilisé par un humain, mais il devra être transformé en
JSONL avant import.

Exemple de brouillon YAML de staging :

```yaml
items:
  - local_path: "data/staging/pilot_math_terminale/source.pdf"
    source_uri: "file://data/staging/pilot_math_terminale/source.pdf"
    title: "Fiche méthode — suites récurrentes"
    source_type: "upload"
    rights: "usage_interne"
    visibility: "internal"
    niveau: "terminale"
    voie: "generale"
    matiere: "mathematiques"
    statut_enseignement: "specialite"
    candidat: "scolarise"
    zone: "aefe_tunisie"
    type_doc: "fiche_methode"
    epreuve: "bac_specialite_ecrit"
    programme_version: "a_confirmer"
    bo_reference: "a_confirmer"
    official_level_ref: "terminale_generale"
    official_subject_ref: "mathematiques_terminale_specialite"
    official_exam_ref: "bac_specialite_ecrit"
    candidate_status_ref: "scolarise"
    establishment_context_ref: "aefe"
    notions:
      - "suites"
      - "recurrence"
    competences:
      - "raisonner"
      - "calculer"
```

Exemple JSONL attendu par l'import actuel :

```json
{"doc_id":"pilot-maths-ts-suites-001","source_uri":"file://data/staging/pilot_math_terminale/source.pdf","source_type":"upload","sha256":"<sha256_du_fichier>","discovered_at":"2026-06-15T00:00:00+00:00","rights":"usage_interne","visibility":"internal","niveau":"terminale","voie":"generale","matiere":"mathematiques","statut_enseignement":"specialite","type_doc":"fiche_methode","epreuve":"bac_specialite_ecrit","candidat":"scolarise","programme_version":"a_confirmer","bo_reference":"a_confirmer","title":"Fiche méthode — suites récurrentes","notions":["suites","recurrence"],"competences":["raisonner","calculer"],"official_level_ref":"terminale_generale","official_subject_ref":"mathematiques_terminale_specialite","official_exam_ref":"bac_specialite_ecrit","candidate_status_ref":"scolarise","establishment_context_ref":"aefe"}
```

Ne pas créer ce manifest réel tant que les documents sources et leurs droits ne
sont pas validés.

## 7. Règles de droits et visibilité

Règles minimales :

- ressource officielle publique : `rights=officiel_public`,
  `visibility=public` ;
- ressource Nexus interne : `rights=nexus_proprietaire` ou `usage_interne`,
  `visibility=internal` ;
- ressource réservée : `rights=restricted`, `visibility=restricted` ;
- droit inconnu : `rights=unknown`, non récupérable.

Toute ressource propriétaire Nexus doit rester hors contexte public. Toute
ressource élève ou privée doit être exclue du corpus pilote sauf anonymisation et
lot dédié.

## 8. Règles de provenance officielle

Les documents officiels et réglementaires doivent pointer vers le référentiel
local `data/reference/`.

Pour terminale générale spécialité mathématiques :

- `official_level_ref: terminale_generale` ;
- `candidate_status_ref: scolarise` pour le profil cible ;
- `establishment_context_ref: aefe` si la ressource vise l'AEFE ;
- `official_exam_ref: bac_specialite_ecrit` pour les sujets, annales, corrigés
  ou barèmes de spécialité.

Une source ou claim `pending` ne doit pas soutenir seule une règle définitive.

## 9. Règles candidat scolarisé / candidat individuel

Le corpus pilote cible `candidat=scolarise`.

Règles :

- ne pas mélanger `scolarise` et `candidat_individuel` dans le même document ;
- ne pas utiliser `aefe` comme statut candidat ;
- utiliser `establishment_context_ref=aefe` pour le contexte AEFE ;
- isoler les documents candidat individuel dans un futur batch dédié ;
- ne pas conclure sur une carte d'examen individuelle sans review humaine.

## 10. Règles AEFE Tunisie

Pour AEFE Tunisie :

- utiliser `establishment_context_ref: aefe` ;
- ajouter une information de zone dans `extra` tant que `DocumentMeta` ne porte
  pas de champ `zone` dédié ;
- ne pas affirmer de modalité locale Tunisie non confirmée ;
- marquer toute source locale non vérifiée comme `pending` dans le référentiel ;
- vérifier manuellement les calendriers et convocations avant tout conseil
  réglementaire.

Exemple `extra` :

```json
{"zone":"aefe_tunisie","pilot_corpus":"maths_terminale_specialite"}
```

## 11. Contrôles avant import

Avant un futur import :

1. calculer le SHA-256 réel de chaque fichier source ;
2. vérifier que chaque `source_uri` pointe vers un fichier local de staging ;
3. vérifier les droits et la visibilité ;
4. vérifier les refs officielles ;
5. vérifier les notions contre `taxonomy/maths/terminale_specialite.yml` ;
6. lancer un dry-run directory ;
7. lancer readiness ;
8. lancer coverage avec notions prioritaires ;
9. lancer gate ;
10. générer un review package ;
11. obtenir une approbation humaine ;
12. importer seulement en mode manifest-only.

Commandes futures typiques, à adapter :

```bash
python -m rag_pedago.imports.readiness_report data/staging/pilot_math_terminale/manifests --batch-id pilot-maths-terminale
python -m rag_pedago.imports.coverage_report data/staging/pilot_math_terminale/manifests --batch-id pilot-maths-terminale --taxonomy taxonomy/maths/terminale_specialite.yml --priority-notion suites --priority-notion recurrence
python -m rag_pedago.imports.gate_report data/staging/pilot_math_terminale/manifests --batch-id pilot-maths-terminale --taxonomy taxonomy/maths/terminale_specialite.yml
```

Ces commandes ne doivent être lancées qu'après création validée des manifests.

## 12. Validation humaine avant ingestion

La review humaine est obligatoire avant tout import contrôlé d'un corpus réel.

La personne validatrice doit vérifier :

- liste des documents ;
- droits et visibilité ;
- absence de données personnelles ;
- cohérence pédagogique ;
- cohérence AEFE Tunisie ;
- refs officielles ;
- hashes des manifests ;
- statut gate.

L'import contrôlé futur doit utiliser `--require-review`, `--review-package` et
`--review-decision`.

## 13. Critères d’acceptation du futur lot d’import

Le futur lot d'import pilote sera acceptable seulement si :

- aucun `source_uri` n'est ouvert pendant les étapes metadata-only ;
- aucun PDF n'est parsé ;
- aucun appel réseau n'est effectué ;
- les manifests valident `DocumentMeta` ;
- les droits sont qualifiés ;
- aucun document `rights=unknown` n'est récupérable ;
- les notions prioritaires sont couvertes ou les lacunes sont documentées ;
- le gate vaut `ready_for_controlled_import` ou les corrections sont explicites ;
- un review package est généré ;
- une approbation humaine valide le batch ;
- le ledger audite package, décision, tentative et vérifications.

## 14. Requêtes de test attendues après ingestion pilote

Après un futur lot d'ingestion documentaire et retrieval, les requêtes de test
attendues seront :

- "Donne-moi une fiche méthode sur les suites récurrentes en terminale spécialité."
- "Trouve des exercices corrigés sur les probabilités conditionnelles."
- "Prépare un plan de révision bac spécialité maths pour un élève fragile en analyse."
- "Quelles ressources sont pertinentes pour un élève AEFE Tunisie scolarisé ?"
- "Ne propose que des documents avec corrigés."
- "Donne une annale de spécialité maths avec barème si disponible."

Ces requêtes ne sont pas exécutables aujourd'hui : le retrieval opérationnel,
les chunks, embeddings et citations ne sont pas encore implémentés.
