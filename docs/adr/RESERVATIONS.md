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

Le contrôle ne lit **que** l'intérieur des marqueurs ci-dessous, et n'y retient que le
premier champ de chaque ligne. La prose de ce fichier — y compris les numéros cités en
exemple ou en provenance — lui est donc invisible, et ne peut pas réserver un numéro par
accident.

<!-- adr-registry:begin -->
```
ADR-0043  lacune    Autorisation de composition multi-autorisation — déclaré accepté et cité comme non supersédé, fichier jamais écrit
ADR-0053  reserve   Autorité eduscol_catalogue_par_scope — autorité de fait de source pour le catalogue par scope
ADR-9999  sentinel  Numéro fictif du test du garde-fou de gouvernance — n'aura jamais de fichier, par construction
```
<!-- adr-registry:end -->

## Détail

**`ADR-0043` — lacune, non réservation.** Un ADR déclaré accepté et cité comme opposable par
le fichier `ADR-0044`, ainsi que par deux rapports de lot, mais dont le fichier n'a jamais
été écrit. Il est consigné ici pour que la lacune cesse d'être silencieuse — pas pour la
légitimer. À écrire ou à requalifier.

**`ADR-0053` — réservation en cours.** Référencé par
`docs/reports/evidence-index/AUTHORITIES.json` et par
`docs/reports/gate_multi_placement_20260829.md`. À retirer d'ici quand le fichier sera écrit.

**`ADR-9999` — sentinelle de test.** Employé par `scripts/tests/test-governance-locks.sh`
pour vérifier qu'un ADR référencé mais inexistant fait échouer le garde-fou. Deux rapports
de lot citent la sortie de ce test. Ce numéro n'aura jamais de fichier : c'est son rôle.
