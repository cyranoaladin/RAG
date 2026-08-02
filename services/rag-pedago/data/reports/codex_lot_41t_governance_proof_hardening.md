# Rapport Codex — LOT41T : durcissement des preuves de gouvernance

## Objectif

LOT41T ferme les diagnostics locaux qui pouvaient attribuer une autorité à des
artefacts modifiables par leur appelant. Une approbation GitHub décrite en YAML
ou construite en mémoire, un digest recalculable et les chaînes locales
`quality/gate/review` ne peuvent plus autoriser une transition ou une
publication. Une revendication golden locale complète reste en attente d'un
canal de confiance authentifié.

Le changement est volontairement fail-closed. Il n'active aucune capacité et
ne connecte ni réseau, ni PostgreSQL, ni publisher au service.

## Fichiers créés

- `data/reports/codex_lot_41t_governance_proof_hardening.md` : présent rapport
  de livraison propre à `rag-pedago`.

## Fichiers modifiés

- `configs/pilot_golden_human_review.yml` : retour du manifeste canonique à un
  état `pending` propre ;
- `rag_pedago/governance/pilot_validation.py` : refus explicite sans canal
  GitHub de confiance, attestation de scope et attestations de chaîne ;
- `rag_pedago/governance/pilot_golden.py` : suppression du verdict local
  `HUMAN_REVIEW_APPROVED` et reclassification des revendications complètes en
  `HUMAN_REVIEW_PENDING` ;
- `scripts/pilot_golden_spec_audit.py` : transmission de `sys.argv[1:]` ;
- `scripts/pilot_validation_policy_audit.py` : libellé exact de cardinalité du
  scope taxonomique ;
- `tests/golden_queries/README.md` : clarification qu'un SHA-256 atteste
  l'intégrité, pas l'autorité humaine ;
- `tests/unit/test_pilot_validation_authorization.py` : cas YAML, mémoire,
  opération sans package, contenu hors scope et attestations auto-déclarées ;
- `tests/unit/test_pilot_golden_spec.py` : états pending/invalid, ancien paquet
  complet non authentifié et invocation CLI directe ;
- `tests/unit/test_pilot_validation_policy_audit.py` : verrouillage du libellé
  de cardinalité sans fausse métrique de couverture.

Les errata et le rapport de lot à l'échelle du dépôt sont consignés sous
`docs/reports/` ; ils ne changent aucun comportement propre au service.

## Tests exécutés

Cycles TDD observés avant la présente synthèse :

- autorisation et publication locales : 13 échecs attendus avant correction,
  puis 186 tests réussis ;
- revue golden et CLI : 8 échecs attendus avant correction, puis 280 tests
  réussis ;
- métrique de cardinalité et errata : 6 échecs attendus avant correction, puis
  32 tests réussis.

Vérifications fraîches sur le head `ba551efd599bed405f4c0564dae00683c7790142`,
antérieur au présent rapport :

- `make doctor` : réussi, socle présent et aucun secret interdit détecté ;
- trois suites unitaires ciblées : 498 tests réussis ;
- Ruff : réussi ;
- mypy : 76 fichiers sans erreur ;
- `make test` : 1 756 tests réussis ;
- audit de politique : code `0`, état `DORMANT` ;
- audit golden : code `3`, état `HUMAN_REVIEW_PENDING` ;
- CLI golden avec argument inconnu : code `2` sans stdout.

Le head final incluant ce rapport sera revérifié séparément. Les résultats
ci-dessus ne prétendent donc pas auto-certifier les octets du présent fichier.

## Résultats

- `approval.trusted_channel_unavailable` bloque toute approbation locale
  structurellement valide ;
- `package.scope_attestation_unavailable` bloque tout package sans liaison de
  scope autoritaire ;
- `package.trusted_attestations_unavailable` bloque les états de chaîne
  auto-déclarés ;
- aucune voie locale ne produit `HUMAN_REVIEW_APPROVED` ;
- le manifeste canonique rend `HUMAN_REVIEW_PENDING` ;
- la sortie de politique annonce une cardinalité de 39 notions sans prétendre
  mesurer leur couverture pédagogique ;
- les 18 verrous de gouvernance restent inchangés et fermés selon leur
  baseline ;
- le verdict global reste `GO_LIVE: NO_GO`.

## Limites volontaires

LOT41T n'implémente ni readback GitHub authentifié, ni registre d'autorité, ni
clé privée, ni ledger d'attestations, ni publisher. Il ne qualifie aucun corpus
réel, n'exécute aucune revue humaine et ne transforme aucune ancienne
revendication en preuve nouvelle. Ces absences sont des refus explicites et non
des chemins permissifs.

## Prochaine étape recommandée

LOT41A doit introduire un adaptateur de confiance vérifiant une review GitHub
formelle sur le dépôt, la PR, la base et le head exacts, émise par un reviewer
autorisé distinct de l'auteur et liée à un challenge canonique. LOT42 devra
ensuite lier les attestations indépendantes `quality`, `gate` et `review` au
même contenu, au même scope et aux mêmes items avant toute publication signée.
