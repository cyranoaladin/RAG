# ADR-0046 — Foyer unique du prédicat structurel « page PDF sans texte »

- Statut : Proposé (2026-09-02). Devient Accepté par une review humaine
  `APPROVED` du Code Owner selon ADR-0025, sur le HEAD exact de la PR qui le
  porte. Ce document n'autorise aucun corpus, n'active aucune ingestion et ne
  lève aucun verrou de gouvernance.
- Périmètre : LOT 1.2 — critère de traitement d'une page sans texte extractible
  (`docs/reports/lot_1_2_critere_page_sans_texte.md`), contrat de partition des
  pages (`ignored_empty_pages`).
- S'appuie sur : ADR-0001 (séparation des plans), AGENTS.md (« un service
  n'importe jamais directement le code d'un autre service »).

## Contexte

Le contrat approuvé le 31 août 2026 fait de `ignored_empty_pages` une sortie
DÉRIVÉE d'un prédicat structurel faisant autorité : une page sans texte
extractible n'est ignorable que si son flux de contenu, `/Form` XObjects
invoqués compris, ne porte ni image, ni opérateur de texte, ni tracé pouvant
porter un glyphe. Ce prédicat est exécuté deux fois dans la chaîne :

- par le scanner PII de `rag-pedago`, qui décide quelles pages le balayage de
  données personnelles peut légitimement ignorer et qui alimente le préflight
  du producteur de release ;
- par l'extracteur de `rag-engine`, qui décide à l'ingestion quelles pages
  restent vides à leur position physique (numérotation des citations).

Au 1er septembre, ces deux exécutions étaient deux COPIES du même code, dans
deux services qui n'ont pas le droit de s'importer. Elles étaient « jumelles »
et épinglées par des tests séparés, avec des codes de motif différents
(`PAGE_IMAGE_NON_LISIBLE` d'un côté, une phrase française de l'autre) et deux
modes de panne différents (exception d'un côté, chaîne de refus de l'autre).
La revue indépendante du LOT 1.2 a refusé cet état : deux implémentations
« maintenues synchronisées par tests » restent deux autorités, et une
divergence future entre PII, production et extraction serait invisible tant
qu'aucun test ne l'attrape sur le PDF réel qui la provoque.

## Décision

Le prédicat vit dans un package technique neutre, hors des deux services et
hors du contrat de retrieval :

```text
packages/pdf-page-policy/            distribution `nexus-pdf-page-policy`
  src/nexus_pdf_page_policy/         module `nexus_pdf_page_policy`
```

Il expose un verdict canonique et rien d'autre :

- `POLICY_ID = "NEXUS-PDF-PAGE-POLICY-V1"` ;
- les trois motifs fermés `PAGE_IMAGE_NON_LISIBLE`, `PAGE_TEXTE_NON_DECODABLE`,
  `PAGE_TRACE_VECTORIEL`, par priorité décroissante, et le code de panne
  `PAGE_INSPECTION_FAILED` ;
- `inspecter_structure`, `motif_de_refus_page`, `classer_pages_sans_texte` ;
- `policy_source_sha256()`, empreinte des octets du module, pour que les preuves
  nomment le prédicat qui les a rendues.

Règles :

1. **Une seule définition.** Ni `rag-pedago` ni `rag-engine` ne conserve de
   copie, même dormante. Chaque service porte un test d'identité d'objet
   (`service.classer_pages_sans_texte is nexus_pdf_page_policy.…`) et un
   témoin « même verdict sur les mêmes octets » ; un doublon local redevient
   rouge.
2. **Le package rend un verdict, il ne décide rien d'autre.** Il ne lit aucun
   fichier, n'écrit rien, ne connaît ni la PII, ni le chunking, ni la release,
   ni le retrieval. Il n'entre pas dans `packages/contracts`, dont l'autorité
   est la représentation et la validation structurelle du contrat.
3. **Une panne n'est jamais un verdict** (R32) : `PageInspectionError` remonte ;
   les deux services refusent alors le document avec `PAGE_INSPECTION_FAILED`.
4. **Provenance.** Les preuves PII nouvelles enregistrent `page_policy_id` et
   `page_policy_sha256` (champs additifs). `pii_scanner_sha256` conserve son
   sens historique — l'empreinte du scanner — et n'est pas réinterprété
   rétrospectivement : les preuves antérieures restent lisibles telles quelles.
5. **Installation.** Le package est installé comme `nexus-contracts` : éditable
   sans re-résolution dans les venvs de service (`make install`), copié puis
   installé dans les images qui embarquent l'extracteur, éprouvé par la CI
   locale sous ses propres tests. Il ne fixe qu'une borne basse de `pypdf` ;
   chaque service garde sa version épinglée dans son lock. Les mêmes 20
   épreuves passent sous `pypdf 4.2.0` (engine) et `6.14.2` (pedago).

## Conséquences

- Le producteur de release n'a plus deux listes dérivées à comparer : PII et
  préflight appellent le même prédicat. La comparaison prévue par la conception
  du 31 août devient une auto-comparaison et n'est pas implémentée.
- `release_readiness` ne réexécute pas le prédicat : il vérifie la liste
  explicite et scellée du manifest (canonicalité, disjonction, partition).
- Un changement du critère est un changement de `POLICY_ID`, un nouvel ADR et
  une nouvelle production ; jamais une retouche locale dans un service.
- Dette laissée visible : `services/rag-engine/requirements.lock` épingle
  `pypdf==4.2.0` alors que le producteur exige `6.14.2` (verrou LOT 1b). Ce
  package ne tranche pas cette divergence ; il la rend mesurable par ses
  épreuves sous les deux runtimes.

## Preuves

- `packages/pdf-page-policy/tests/test_page_policy.py` : 20 épreuves sur des
  PDF réellement construits (page vide, rectangle seul, image, image en ligne,
  opérateurs de texte sans glyphe, courbe, segment, priorités, `/Form` vide,
  `/Form` peignant une image, XObject introuvable, document illisible).
- `services/rag-pedago/tests/test_pii_scanner_pages_sans_texte.py::TestFoyerUnique`
  et `services/rag-engine/tests/test_pdf_runtime_extractor.py::TestSharedPagePolicy`.
