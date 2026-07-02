# LOT 25 — Cadrage ré-ingestion heading-aware (K-01→K-05)

**Date** : 2 juillet 2026
**Statut** : cadrage, aucune exécution.
**Principe** : D-LOT25-EST-UN-TEST — DD-02 est une prédiction, pas un acquis.

---

## K-01 — Spec du chunker heading-aware

### Constat : le chunker existe déjà

`services/rag-engine/src/ingestor/pedagogical_chunker.py` est **déjà heading-aware** :
- Parse les `# H1 / ## H2 / ### H3` en arbre de sections (`parse_sections`)
- Produit des chunks avec breadcrumb `[Section › Sous-section]` (`_flatten_section`)
- Subdivise les sections longues avec overlap par phrases (`_subdivide`)

Le LOT 22 ne l'a **pas utilisé** : le script `ingest_nsi_lot22.py` utilise un split par phrases/tokens ad hoc (`chunk_text()`) qui ignore la structure de sections. C'est le cœur de la dette R8.

### Ce qui change au LOT 25

| Aspect | LOT 22 (proxy) | LOT 25 (heading-aware) |
|---|---|---|
| **Structure** | Split par phrases, aucune hiérarchie | Parse H1/H2/H3, arbre de sections, breadcrumb |
| **Compteur tokens** | `AutoTokenizer` e5 réel (480 tokens) | **Idem** — remplacer `_estimate_tokens()` (proxy `words*1.3`) par `AutoTokenizer` e5 |
| **Budget** | 480 tokens e5 | 480 tokens e5 (inchangé) |
| **Contexte** | Aucun | `[Section › Sous-section]` préfixé (aide le rerank à scorer la pertinence) |
| **Outputs .ipynb** | Gardés (dette B9) → base64/images dans les chunks | **Jetés** : seules les cellules markdown + code source conservées, outputs/images exclus |
| **Artefacts PDF** | Non filtrés → 187 chunks base64 quarantinés | **Filtrés** : chunks dont > 50 % du contenu est non-textuel → exclus |
| **Formats** | PDF (pypdf), DOCX (python-docx), ODT (odfpy), TEX, IPYNB | **Idem** — le chunker heading-aware s'applique APRÈS l'extraction de texte |

### Modifications concrètes du code

1. **Remplacer `_estimate_tokens`** par le tokenizer e5 réel (comme LOT 22 `chunk_text()`)
2. **Passer par `parse_sections` → `_flatten_section`** au lieu du split par phrases
3. **Ajouter un pré-traitement .ipynb** : jeter `cell.outputs`, garder `cell.source` de type markdown/code
4. **Ajouter un filtre post-extraction** : rejeter les chunks dont le ratio caractères non-espaces / caractères alphanumériques < 0.5 (attrape base64/artefacts)
5. **Conserver le format Markdown** en entrée du chunker : pour les PDF/DOCX/ODT, l'extraction texte produit du texte brut sans headings → le chunker sera heading-aware SEULEMENT sur les documents qui ont une structure (Markdown, notebooks). Pour les PDF bruts, il tombera en mode linéaire (split par taille) — **c'est un fait à mesurer, pas à masquer**.

### Point d'attention

Le chunker heading-aware sera pleinement efficace sur les **notebooks** (.ipynb avec cellules markdown structurées H1/H2/H3) et les documents **.tex** (structure `\section{}`/`\subsection{}`). Pour les **PDFs** extraits par pypdf, la structure de headings est **perdue** lors de l'extraction (pypdf donne du texte brut). L'amélioration sur les PDFs viendra surtout du **filtrage base64** et du **meilleur comptage tokens**, pas de la hiérarchie.

---

## K-02 — Plan de ré-ingestion réversible (blue/green)

### Stratégie

1. **Table shadow** : créer `rag_chunks_v2` dans la même instance pgvector, avec le même schéma que `rag_chunks`. La table `rag_chunks` (LOT 22) reste intacte et servable.

2. **Ingestion shadow** : le script de ré-ingestion écrit dans `rag_chunks_v2`. Même manifest, même corpus source, même embedding e5-large. Seul le chunker change.

3. **Mesure** (K-03) : les 25 requêtes golden sont exécutées contre `rag_chunks_v2` (en changeant la table dans la requête SQL, pas la collection ni le seuil). La baseline LOT 24 reste sur `rag_chunks`.

4. **Bascule** : si les critères sont remplis (DD-02 confirmé ou partiel), renommer les tables : `rag_chunks` → `rag_chunks_lot22_archive`, `rag_chunks_v2` → `rag_chunks`. Le retrieval v2 reprend automatiquement.

5. **Rollback** : si DD-02 infirmé, supprimer `rag_chunks_v2`. La table `rag_chunks` (LOT 22) reste servable. Aucune perte.

### Garanties

- Le corpus LOT 22 reste interrogeable **pendant toute la ré-ingestion**
- La bascule est une opération de renommage SQL atomique (`ALTER TABLE ... RENAME TO`)
- Le rollback est instantané (supprimer la table shadow)

---

## K-03 — Protocole de mesure

### Baseline figée (D-BASELINE-LOT24-FIGEE)

Les 4 questions faibles, scores LOT 24 (config dense→rerank→seuil +1.90) :

| Question | Score LOT 24 |
|---|---|
| Jointure SQL | +2.30 |
| Boucle while | +4.86 |
| Récursivité | +3.77 |
| Processus/ordonnancement | +4.53 |

Marge in/out LOT 24 : 0.79. Seuil : +1.90.

### Protocole

1. Ré-ingestion dans `rag_chunks_v2` (chunker heading-aware, même e5-large, même 480 tokens)
2. Exécuter les **25 requêtes golden** contre `rag_chunks_v2` avec la config retrieval identique (dense→rerank ms-marco-MiniLM-L-6-v2, même seuil)
3. Produire le tableau :

| Question | LOT 24 | LOT 25 | Δ | Verdict |
|---|---|---|---|---|
| Jointure SQL | +2.30 | ? | ? | > +5 ? |
| ... | ... | ... | ... | ... |

4. **Verdict DD-02** :
   - (a) Les 4 montent > +5 → DD-02 **confirmé**, le chunking était la cause
   - (b) Certaines montent, d'autres non → DD-02 **partiellement confirmé**, analyser les non-montées
   - (c) Aucune ne monte → DD-02 **infirmé**, investiguer (K-05)

5. Recalculer la marge in/out et le seuil optimal sur la nouvelle distribution.

---

## K-04 — Effet du contenu re-servable, mesuré à part

### Étape 1 : ré-ingestion SANS le quarantiné

D'abord, ré-ingérer uniquement les 1 762 docs déjà servables (sans ProjetPopArt ni les 187 base64). Mesurer les 25 requêtes. C'est l'effet **pur** du chunker.

### Étape 2 : ajouter le re-servable

Ensuite, ré-ingérer ProjetPopArt (avec outputs jetés → que le texte markdown/code) et les 187 docs base64 (avec filtrage artefacts). Mesurer les mêmes 25 requêtes. Comparer à l'étape 1.

### Métriques d'isolation

- Étape 1 vs LOT 24 = **effet chunker seul**
- Étape 2 vs étape 1 = **effet contenu re-servable seul**
- Si étape 2 introduit du bruit (scores baissent) → le contenu réintroduit est problématique → il reste quarantiné

### Volumétrie attendue

- ProjetPopArt : texte markdown/code du notebook, sans images base64. Estimé ~5-15 chunks (vs 1 418 avant). Si > 100 → suspect, investiguer.
- Les 187 docs base64 : re-chunkés avec filtre. Estimé ~150-170 chunks propres (la plupart ont du texte réel autour du base64 filtré).

---

## K-05 — Plan de repli si DD-02 infirmé

### Si les 4 questions ne montent pas (issue c)

**Protocole d'investigation, pas de bricolage** :

1. **Vérifier le chunk remonté** : pour chaque question faible, montrer le meilleur chunk LOT 25 vs le meilleur LOT 22. Le chunk LOT 25 est-il réellement meilleur (contient la définition/explication au lieu d'un passage adjacent) ? Si oui mais le score ne monte pas → le rerank a une limite, pas le chunker.

2. **Tester la formulation** : reformuler les 4 questions (mots-clés au lieu de question élève) et mesurer. Si la reformulation donne > +5 → le rerank est sensible à la formulation, pas au chunking.

3. **Examiner le contenu** : pour « clé étrangère » et « jointure SQL », montrer les 5 meilleurs chunks du corpus sur ces sujets. Sont-ils des passages de cours explicatifs, ou des exercices/sujets bac qui mentionnent le sujet sans le définir ? Si le corpus ne contient que des exercices → c'est une dette de contenu (pas assez de cours explicatifs), pas de chunking.

4. **Comparer les modèles** : tester un autre CrossEncoder (ex. `ms-marco-MiniLM-L-12-v2`, plus gros) sur les 4 questions. Si les scores montent → le rerank MiniLM-L-6 a une limite sur ces formulations.

### Engagement

L'agent s'engage à rapporter le résultat mesuré, quel qu'il soit. Un DD-02 infirmé est un résultat scientifique valide qui oriente la suite (enrichissement de contenu, changement de modèle, reformulation du jeu de test), pas un échec à masquer.

---

## STOP — Cadrage rendu, en attente de validation lead

K-01 à K-05 préparés. Aucune exécution, aucun code de ré-ingestion écrit. En attente du go lead pour ouvrir l'exécution du LOT 25.
