# Official reference explainability

Les décisions de compatibilité officielle doivent être auditables. Un humain
doit comprendre pourquoi une source ou une claim couvre un document, ou pourquoi
elle le bloque.

## Format

Chaque explication suit le modèle `CompatibilityExplanation` :

```json
{
  "ref_id": "education_bac_general",
  "document_refs": ["grand_oral", "mathematiques", "scolarise", "terminale_generale"],
  "compatible": true,
  "matched_ref": "grand_oral",
  "path": ["bac_general", "grand_oral"],
  "reason": "source applies through aggregate bac_general -> grand_oral"
}
```

## Cas compatible

Une source `education_bac_general` peut couvrir un document Grand oral via le
chemin :

```text
bac_general -> grand_oral
```

Le rapport indique `compatible: true`, le `matched_ref` et le chemin retenu.

## Cas incompatible

Une source `education_dnb` sur un document Grand oral produit :

```json
{
  "compatible": false,
  "matched_ref": null,
  "path": [],
  "reason": "no compatible path from dnb ... to document refs"
}
```

Le batch `data/fixtures/manifests/batch_official_mismatch/` contient deux cas
contrôlés :

- source DNB utilisée sur un document Grand oral ;
- claim candidat individuel utilisée sur un document scolarisé.

## Où lire les explications

- rapport readiness : section `Official reference compatibility` ;
- rapport gate : section `Official reference compatibility` et JSON `issues` ;
- rapport controlled import : section `Official reference compatibility` et
  JSON `official_reference_compatibility`.

Les review packages du lot 12 incluent les hashes de ces rapports. Une revue
humaine peut donc être reliée à la version exacte des explications vues au
moment de l'approbation.

## Limites

Les explications portent sur les métadonnées du manifest et le référentiel
officiel. Elles ne valident pas le contenu réel du PDF, d'un sujet, d'un
corrigé ou d'un barème.
