# LOT 1.2 — Critère de traitement d'une page sans texte extractible

**Posé le 2026-08-31, avant toute mesure de distribution.** Ce document fixe le
critère ; les mesures d'impact qui le suivent ne le modifient pas. Si une mesure
ultérieure le contredit, c'est le critère qui est rediscuté explicitement, jamais
ajusté en silence.

## Le défaut corrigé

`services/rag-pedago/rag_pedago/imports/pii_scanner.py` refusait le document entier
dès qu'**une** de ses pages ne rendait aucun texte :

```python
if any(not page_text.strip() for page_text in pages_text):
    return ... extraction_error="PDF_PAGE_TEXT_EXTRACTION_EMPTY"
```

`any`, non `all`. Une page de séparation suffisait. Le remède n'est pas `all` : sur
`3bc5ff23…`, `all` aurait laissé le balayage PII s'exercer sur 867 caractères d'un
document scanné de 44 pages et prononcer « aucune donnée personnelle » sur un texte
jamais lu. Ce corpus sert des élèves mineurs.

## Le principe

> Une page sans texte extractible est **ignorable** si et seulement si elle est
> structurellement incapable de porter un glyphe. Dans tous les autres cas, elle est
> **refusée**, avec la raison exacte de son refus.

Le refus est conservé partout où il protège ; il est levé là où il ne protégeait rien.

## Le critère, sans seuil

Une page sans texte extractible est **ignorable** si et seulement si, sur son flux de
contenu et récursivement dans tous ses `/Form` XObjects, elle ne contient :

| # | condition | ce qu'elle écarte |
|---|---|---|
| 1 | aucun XObject `/Subtype /Image` | texte photographié (scan, JBIG2, planche) |
| 2 | aucun opérateur d'affichage de texte `Tj` `TJ` `'` `"` | texte présent mais illisible au scanner (encodage cassé, `/ToUnicode` absent) |
| 3 | aucun opérateur de courbe `c` `v` `y` | glyphe vectorisé en courbes |
| 4 | aucun opérateur de tracé libre `m` `l` | glyphe vectorisé en segments |

Toute construction de tracé restante est donc `re` seul — des rectangles à axes
alignés. **Un rectangle n'est pas une lettre**, et aucun producteur de PDF ne
compose un glyphe en rectangles alignés sur les axes.

Aucune de ces quatre conditions n'emploie de seuil. Il n'y a rien à ajuster sur une
distribution.

**Page refusée** → le motif nomme laquelle des quatre a échoué, jamais une catégorie :

| motif | sens |
|---|---|
| `PAGE_IMAGE_NON_LISIBLE` | condition 1 — pages-image, candidat OCR |
| `PAGE_TEXTE_NON_DECODABLE` | condition 2 — opérateurs de texte sans texte extractible |
| `PAGE_TRACE_VECTORIEL` | conditions 3 ou 4 — tracé pouvant porter du texte vectorisé |

## L'instrument

La détection d'image traverse le modèle objet `pypdf` en descendant dans les `/Form`,
et **compte sans décoder** : aucune dépendance à `pillow`. Ce choix n'est pas celui du
meilleur détecteur mais du seul qui puisse s'exercer là où le contrôle doit
s'exercer — dans le conteneur d'ingestion.

Validé contre deux moteurs indépendants, poppler (`pdfimages -list`) et MuPDF
(`mutool info -I`), page pour page sur les deux documents en litige : concordance
exacte.

**Échec bruyant, non négociable.** Si la traversée ne peut pas s'effectuer, le
contrôle refuse et lève ; il ne conclut jamais « aucune image ». Une panne
d'instrument n'est pas un verdict. Un `except` produisant une valeur de repli est
interdit sur un instrument de mesure (R32) — c'est très exactement l'`ImportError:
pillow is required` qui, avalé par un `except` large, avait produit l'inverse de la
vérité lors du diagnostic.

## Attendu, posé d'avance

| document | classement attendu | conséquence |
|---|---|---|
| `8848f073…` (54 p., 121 910 car.) | pages 2 et 54 **ignorables** — `/Fm0` de 0 octet ; un `re f` bleu | document **scanné**, 2 placements conservés |
| `3bc5ff23…` (44 p., 867 car.) | 18 pages **refusées** en `PAGE_IMAGE_NON_LISIBLE` | document **exclu**, motif écrit, candidat OCR |

Production attendue : **488 couples, 320 contenus**. Toute autre valeur arrête le lot.
