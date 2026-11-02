# Numéros d'ADR sans fichier — registre

Un numéro d'ADR peut être **référencé avant d'être écrit** : un rapport de lot, un champ
`adr` dans un artefact d'attestation, ou un autre ADR peuvent le citer alors que le fichier
`docs/adr/ADR-NNNN-*.md` n'existe pas.

Tant que cette réservation ne vit qu'en prose, elle est invisible à `git log`, à
`ls docs/adr/` et à toute recherche de fichier — et rien n'empêche un contributeur d'écrire
un ADR sans rapport sous ce même numéro. C'est arrivé.

**Ce fichier est le registre que l'outillage lit.** `scripts/check-adr-numbering.sh` échoue
si un numéro est référencé quelque part dans le dépôt sans avoir ni fichier ni entrée ici.

## Règles

- **Réserver** : ajouter une ligne au bloc ci-dessous *dans le même commit* que la première
  référence au numéro.
- **Honorer** : à la création du fichier `docs/adr/ADR-NNNN-*.md`, **retirer** la ligne. Une
  réservation honorée n'est plus une réservation, et le contrôle échoue si elle traîne.
- **Ne jamais réutiliser** un numéro déclaré ici pour un autre sujet. Prendre le premier
  libre.

## Bloc lu par l'outillage

Catégories : `reserve` (numéro cité, fichier à écrire), `branche` (fichier existant sur une
ref non fusionnée), `sentinel` (numéro fictif, n'aura jamais de fichier).

Le contrôle ne lit **que** l'intérieur des marqueurs ci-dessous, et n'y retient que le
premier champ de chaque ligne. La prose de ce fichier — y compris les numéros cités en
exemple ou en provenance — lui est donc invisible, et ne peut pas réserver un numéro par
accident.

<!-- adr-registry:begin -->
```
ADR-0043  branche   Preuve H2 V2 liée à la chaîne Tier A — statut Proposé, fichier porté par une branche non fusionnée
ADR-0053  reserve   Autorité eduscol_catalogue_par_scope — autorité de fait de source pour le catalogue par scope
ADR-9999  sentinel  Numéro fictif du test du garde-fou de gouvernance — n'aura jamais de fichier, par construction
```
<!-- adr-registry:end -->

## Détail

**`ADR-0043` — porté par une branche, pas une lacune.** Le fichier
`docs/adr/ADR-0043-preuve-h2-v2-liaison-tier-a.md` **existe**, sur la branche
`rag-pedago/tier-a-currentness-byte-identity-20260820`, au statut **Proposé**, soumis au gate
humain et jamais fusionné. Quatre documents fusionnés le citent — et le déclarent tous
explicitement `UNREVIEWED_WIP`, `NON_AUTHORITATIVE`, `NOT_REUSED`. Rien n'est à corriger :
c'est une quarantaine délibérée, correctement signalée partout où le numéro apparaît.

Il figure ici parce que le contrôle ne balaie que la ref courante (`git ls-files`) : un ADR
vivant sur une autre branche y sera toujours vu comme un numéro sans fichier. Étendre le
balayage à toutes les refs coûterait un couplage à l'état de `fetch` pour un gain nul — le
registre est le bon endroit pour porter cette information, et il dit **où** le fichier vit.
À retirer d'ici le jour où la branche fusionne.

**`ADR-0053` — réservation en cours.** Référencé par
`docs/reports/evidence-index/AUTHORITIES.json` et par
`docs/reports/gate_multi_placement_20260829.md`. À retirer d'ici quand le fichier sera écrit.

**`ADR-9999` — sentinelle de test.** Employé par `scripts/tests/test-governance-locks.sh`
pour vérifier qu'un ADR référencé mais inexistant fait échouer le garde-fou. Deux rapports
de lot citent la sortie de ce test. Ce numéro n'aura jamais de fichier : c'est son rôle.
