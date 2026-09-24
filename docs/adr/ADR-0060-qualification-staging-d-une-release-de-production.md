# ADR-0060 — Qualifier sur le staging les octets exacts d'une release de production

- **Statut** : Proposé — décision de principe prise par le propriétaire le
  2026-09-24 (option A) ; devient Accepté par la review humaine `APPROVED` du
  HEAD exact de la PR qui l'introduit.
- **Date** : 2026-09-24
- **S'appuie sur** : ADR-0035 (reçus de revue), ADR-0047 (décisions PII),
  ADR-0055/0059 (actualité, adoption par un successeur), ADR-0057 (readiness
  de répétition), LOT41A (autorisations de scope)
- **Contrat** : aucun changement de `nexus-contracts` ; une migration de
  contrôle (019)

## Le fait qui force la décision

Worker B ne pouvait publier aucune release `production-profile-gate` sur le
staging. En répétition, il exigeait un manifeste de profils *de staging* dont
l'empreinte égale celle que déclare la release — or une release de production
déclare l'empreinte canonique de son manifeste *de production* ; il vérifiait
la chaîne PII avec des clés de *test* — or le reçu réel de V3 est signé par la
clé de revue de production ; et il exigeait des autorisations liées au contenu
(LOT41A-V2) — or les placements acquis portent des autorisations V1. Une
variante « staging » de V3 aurait qualifié autre chose que ce qui sera servi.

## Décision

**Séparer la cible d'exécution des autorités vérifiées.**

| Dimension | Règle |
|---|---|
| Cible d'exécution | staging cloisonné ; environnement `rehearsal` ; ses bases, rôles et accès |
| Candidat | la release exacte, par ses empreintes |
| Profils | ceux que la release déclare, jamais des profils de test |
| Preuves documentaires | les autorités réelles de la release, vérifiées avec leurs ancres |
| Autorité d'exécution | une readiness de **staging** qui nomme la release ; aucune readiness ni activation de production |

1. **Qualification liée à une release.** Worker B, sous une readiness
   `NEXUS-STAGING-READINESS-V1` vérifiée, obtient une `ReleaseBoundQualification`
   si et seulement si la readiness nomme l'identifiant de release, l'empreinte
   du manifeste de release chargé et l'image qui s'exécute. Elle ne se
   construit que depuis ce résultat vérifié ; aucun argument ne l'active.
2. **Profils.** Sous qualification, la répétition consomme le manifeste de
   profils de production de *cette* release, vérifié par le même chargeur que
   la production ; un manifeste de staging y est refusé. Sans qualification,
   rien ne change. La production ne connaît pas ce mode.
3. **Chaîne PII.** Sous qualification, la chaîne documentaire de la release
   est vérifiée avec les clés publiques qui l'ont réellement signée
   (environnement de vérification `production` de l'ancre de revue). Vérifier
   une signature n'exerce aucune clé privée et n'autorise aucune exécution de
   production. Une clé de test reste irrecevable pour cette chaîne ; une
   répétition ordinaire reste sur les clés de test.
4. **Autorité de publication.** Un placement adopté conserve l'autorisation
   qui a fondé son acquisition. La migration 019 ajoute, en ajout seul, une
   autorité de **publication** par placement adopté (LOT41A-V2, contenu nommé,
   même collection), liée par l'attestor après revérification vivante.
   `load_adopted_rows` la propage aux faits batch, tout ou rien par
   successeur. Aucun payload historique n'est réécrit, aucune autorisation
   n'est choisie par ancienneté.
5. **Chemin batch.** La vérification d'une attestation batch exige désormais
   une autorité liée au contenu : LOT41A-V2, contenu dans la liste positive,
   même collection — ce que le chemin unitaire exigeait déjà.

## Ce qui ne change pas

La production, ses readiness, ses clés et ses contrôles. L'interdiction de
publier V2. Toute exigence qui refuse aujourd'hui un mélange non nommé.

## Conséquences

* Onze autorisations de publication LOT41A-V2 sont dérivées des r2 et des
  placements de la release qualifiée — r4 pour V4 (`build_lot41a_r4_authorizations.py`,
  ADR-0061) ; elles sont versées par leur propre PR, enregistrées pendant
  qu'elle est ouverte et approuvée.
* L'image worker doit être reconstruite depuis le commit qui porte ce code.
* L'amendement staging nomme les opérations ajoutées : liaison des autorités
  de publication, enregistrement des r4, migration 019.
