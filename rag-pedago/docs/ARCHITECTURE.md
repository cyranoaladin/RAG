# Architecture

Le projet est organisé en couches locales, déterministes et testables. Les
couches actuelles travaillent uniquement sur des métadonnées et des fichiers de
référence versionnés.

## Couches

`schema/` contient les modèles Pydantic partagés : documents, chunks, profils,
références officielles, sources et retrieval.

`reference/` charge `data/reference/`, construit un index officiel et résout les
compatibilités directes ou indirectes entre niveaux, examens, sources, claims,
statuts candidats et contextes d'établissement.

`taxonomy/` contient les taxonomies pédagogiques contrôlées, notamment Maths
terminale spécialité et NSI terminale.

`imports/` contient les étapes metadata-only : import manifest, import dossier,
qualité, readiness, coverage, gate, review package, approval et controlled
import.

`ledger/` contient SQLite, migrations, repository, diagnostics et audit runtime.

`reports/` regroupe les rapports Codex versionnés et les rapports runtime
ignorés par Git.

`fixtures/` contient des manifests synthétiques utilisés par les tests.

`docs/` contient les politiques, contrats et guides humains.

`tests/` vérifie les modèles, workflows, contrats et invariants.

## Pipeline actuel

```text
Official Reference
→ DocumentMeta
→ Manifest
→ Quality Policy
→ Readiness
→ Coverage
→ Gate
→ Review Package
→ Approval
→ Controlled Import
→ Audit Ledger
```

Le référentiel officiel soutient les règles qualité. Les manifests déclarent des
`DocumentMeta`. La qualité vérifie droits, références officielles, doublons et
cohérences. Readiness et coverage produisent des rapports. Le gate combine les
décisions. La review humaine fige les hashes. L'import contrôlé écrit seulement
des métadonnées dans le ledger si les conditions sont remplies.

## Ce qui n'existe pas encore

- Parsing documentaire.
- Chunking pédagogique.
- Embeddings.
- Retrieval opérationnel.
- Qdrant.
- PostgreSQL.
- Réponses LLM.
- API cockpit.

Ces capacités nécessitent des lots dédiés et ne doivent pas être introduites par
effet de bord.
