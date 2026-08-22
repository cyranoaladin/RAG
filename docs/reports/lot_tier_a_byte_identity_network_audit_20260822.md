# Lot — Audit réseau byte-identity Tier A (2026-08-22)

## Addendum (2026-08-22, second pass) — investigation bornée d'une voie alternative, et terminalisation

Une seconde passe, strictement bornée (pas de boucle), a cherché une voie
d'accès légitime alternative avant d'accepter "138/138 bloqués" comme
définitif :

- **Colonnes du TSV de provenance** (`sha256, scope, famille,
  matiere_ou_rubrique, niveau, type_document, annee, statut, titre,
  url_source, objet_source, chemin_technique_existant, chemin_par_scope,
  taille_octets, pages_pdf, integrite`) : aucune URL alternative
  (CDN/archive/téléchargement direct) n'existe pour ces 8 pages —
  `objet_source` est un chemin d'objet interne (`objects/sha256/...`), pas
  une URL primaire alternative.
- Variations légitimes essayées (UA navigateur + `Accept-Language: fr-FR`,
  slash final, http/https) : toujours 403. Page de blocage confirmée comme
  un template Cloudflare standard (`cf-ray` présent, gate JS-cookie
  « Sorry, you have been blocked »), pas une erreur de rate-limit ni de
  maintenance — pas de `Retry-After`, pas de contact, rien suggérant un
  blocage temporaire.
- `robots.txt` reconfirmé : le tiers générique (`User-agent: *`) autorise
  explicitement `/*.pdf$` et `/sites/default/files/`, et les pages article
  elles-mêmes ne sont pas `Disallow`. Le blocage vient de l'infrastructure
  Cloudflare, pas d'une politique déclarée du site.
- **Aucun contournement tenté** (pas de résolution de challenge JS, pas de
  navigateur automatisé, pas de substitution par une copie tierce).

**Conclusion : aucune voie d'accès légitime alternative trouvée.**

### Vocabulaire terminal canonique — recherché, absent

Le vocabulaire attendu (`REVIEW_REQUIRED_AFTER_INVESTIGATION` /
`PRIMARY_SOURCE_UNAVAILABLE`) a été cherché explicitement dans
`currentness_gate.py` et tout `rag_pedago`/`packages/contracts` : **il
n'existe pas**. L'énumération réelle `Currentness` est
`ACTUEL | TRANSITION | A_VERIFIER | ARCHIVE | CONFLICT | UNCLASSIFIED`,
mappée uniquement vers les dispositions
`INGEST | REVIEW_REQUIRED | ARCHIVE_ONLY | QUARANTINE`. `SOURCE_UNAVAILABLE`
est un vocabulaire introduit par ce lot pour son propre artefact d'audit —
pas une valeur de contrat pré-existante.

**Décision de terminalisation (sans inventer de nouvelle valeur de
contrat)** : les 138 items restent à leur statut réel déjà existant
(`A_VERIFIER`/`REVIEW_REQUIRED`) — un statut terminal légitime pour ce
go-live (ne bloque pas indéfiniment, ne devient pas `CURRENT` par défaut).
L'artefact `tier_a_byte_identity_network_audit_20260822.json` (decision
`SOURCE_UNAVAILABLE` par item, 403 Cloudflare documenté) est joint comme
**preuve d'investigation réelle** — ces 138 items ne sont plus
`REVIEW_REQUIRED_NOT_YET_INVESTIGATED` (ils ont été vérifiés en réseau
pour de vrai), ils restent `REVIEW_REQUIRED` avec preuve d'investigation.
Créer une nouvelle valeur d'énumération (`REVIEW_REQUIRED_AFTER_INVESTIGATION`)
serait un changement de contrat de taxonomie sur `currentness_gate.py` —
hors périmètre de ce lot en lecture seule, non fait unilatéralement ;
signalé ici pour décision de l'opérateur propriétaire de ce contrat,
conformément à la règle d'escalade d'AGENTS.md.

```
TIER_A_NOT_INVESTIGATED=0   # les 138 ont été réellement vérifiés en réseau
TIER_A_ALL_CURRENT=false    # honnête -- zéro promotion, ce n'est pas l'objectif de ce lot
NEW_TAXONOMY_VALUE_INTRODUCED=false
```

## 1. Périmètre

Entrée : les 138 `content_sha256` de `byte_identity_audit_input` dans
`docs/reports/tier_a_set_algebra_reconciliation_20260822.json`
(`input_set_sha256=152bd6fc0f2441beff9a8f41744c0f58289f1c05900fe607c19be32f4f3f2a89`).
Aucune donnée de la branche quarantinée `rag-pedago/tier-a-currentness-byte-identity-20260820`
n'a été réutilisée.

## 2. Provenance des URLs — trouvée, pas devinée

`multilevel_currentness_evidence.yml` ne porte aucune URL. La vraie
provenance existe dans un registre versionné hors dépôt mais fourni avec le
corpus scellé lui-même :
`~/Téléchargements/NEXUS_RAG_GDRIVE_READY/00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-complet.tsv`
(2956 lignes, colonne `url_source`, clé `sha256`).

**Couverture : 138/138** — chaque `content_sha256` de l'audit a une entrée
exacte dans ce catalogue, avec un `url_source` réel (`eduscol.education.gouv.fr`).
`SOURCE_URL_REGISTRY_MISSING=false`.

Les 138 items pointent vers seulement **8 URLs distinctes** (plusieurs
`content_sha256` — documents PDF différents — sont référencés depuis la même
page article Eduscol).

## 3. Probe réseau — diagnostic systémique complet

Contrôles de connectivité générale (pour exclure un sandbox sans accès
réseau) :
```
https://1.1.1.1/           -> 301 (réel)
https://www.google.com/    -> 200 (réel)
DNS eduscol.education.gouv.fr -> résout (4 adresses IPv6, Cloudflare)
```
→ Le sandbox a un accès Internet sortant réel et fonctionnel. Ce n'est
**pas** un cas "zéro accès réseau" — le probe ne s'arrête donc pas là.

Test de la cible réelle, plusieurs configurations :
```
curl par défaut                         -> HTTP 403 (Cloudflare)
User-Agent navigateur + Accept headers  -> HTTP 403 (identique)
--http1.1 au lieu de HTTP/2             -> HTTP 403 (identique)
robots.txt du domaine                   -> HTTP 200, autorise User-agent: * avec Crawl-delay: 10
```

Le corps de la réponse 403 fait exactement **5499 octets** sur les 8 URLs
testées (page de blocage Cloudflare standard, `server: cloudflare`,
`cf-ray:` présent), avec un contenu légèrement différent par URL (nonce/ray-id
intégré, d'où des SHA256 de corps différents malgré une taille identique) —
signature caractéristique d'un blocage anti-bot au niveau CDN, pas d'un
problème réseau local, pas d'un 404/410 réel, pas d'une indisponibilité
serveur (5xx).

**Diagnostic retenu** : blocage anti-automatisation Cloudflare au niveau
infrastructure (probablement scoring sur l'IP/ASN du sandbox ou fingerprint
TLS/HTTP non-navigateur), **au-delà** de la politique déclarée dans
`robots.txt` (qui autorise explicitly `User-agent: *` avec un simple
crawl-delay). Ce n'est ni un problème DNS, ni TLS, ni un manque d'accès
réseau local, ni un vrai 404/indisponibilité du contenu lui-même.

**Aucune tentative de contournement** (pas de résolution de challenge
JavaScript, pas de spoofing d'empreinte TLS, pas de proxy résidentiel) —
un 403 authentique et reproductible est un constat légitime à documenter,
pas un obstacle à contourner.

`NETWORK_PROBE_PASS=false` au sens strict (aucune des 8 URLs distinctes n'a
donné une réponse exploitable pour comparaison d'octets), mais le diagnostic
est complet et univoque : ce n'est pas une panne réseau du sandbox.

## 4. Exécution complète malgré le probe négatif

Contrairement à un simple échantillon, **les 8 URLs distinctes (= 100 % des
sources réelles couvrant les 138 `content_sha256`) ont été interrogées
individuellement pour de vrai**, avec respect du `Crawl-delay: 10` du
`robots.txt`. Chaque `content_sha256` porte donc un résultat HTTP réel pour
son URL exacte — aucun résultat n'a été extrapolé ou deviné à partir d'un
sous-échantillon.

Résultat : 8/8 URLs → HTTP 403 Cloudflare, de façon identique.

## 5. Décisions terminales

Aucune promotion `CURRENT_BYTE_IDENTICAL` n'est possible sans réponse
exploitable. Décision appliquée aux 138 items, individuellement justifiée par
leur propre requête HTTP réelle :

```
CURRENT_BYTE_IDENTICAL=0
CHANGED_SOURCE=0
SOURCE_NOT_FOUND=0
SOURCE_UNAVAILABLE=138
AMBIGUOUS_SOURCE=0
CONFLICT=0
TOTAL=138
```

**`SOURCE_UNAVAILABLE` ≠ `NOT_CURRENT`.** Les 138 items restent `pending` :
aucune promotion, aucune démotion, aucun archivage. Ils gardent leur statut
`currentness=unclassified`/`a_verifier` antérieur, avec preuve d'échec
d'audit réseau versionnée.

## 6. Comparaison avec le WIP quarantiné

Le WIP quarantiné avait produit `SOURCE_UNAVAILABLE=138/138` sans diagnostic
systémique documenté. Cette reproduction indépendante arrive **au même
total** mais avec une différence importante : la cause est maintenant
précisément établie (blocage Cloudflare anti-bot réel et reproductible,
sandbox avec accès réseau fonctionnel) plutôt que supposée. Le nombre
identique (138/138) n'est donc pas un signal que le WIP était fiable par
construction — c'est une coïncidence de résultat final vérifiée
indépendamment avec une méthode et une preuve différentes (8 requêtes HTTP
réelles documentées ici, cause racine identifiée).

## 7. Suivi humain nécessaire

Aucune source primaire n'a pu être vérifiée par octets dans ce lot. Pour
lever ce blocage, une option hors périmètre de cet agent : exécuter l'audit
depuis une IP/réseau non soumise au même scoring anti-bot Cloudflare (poste
opérateur humain, navigateur réel), ou obtenir un accord d'accès dédié avec
Eduscol/Cloudflare. Ceci reste un **HUMAN GATE** distinct — aucune tentative
d'évasion technique n'a été faite ni ne doit l'être.

## 8. Booléens finaux

```
SOURCE_URL_REGISTRY_MISSING=false
NETWORK_PROBE_PASS=false
NETWORK_PROBE_DIAGNOSIS=CLOUDFLARE_BOT_PROTECTION_403_DOMAIN_WIDE
ALL_DISTINCT_URLS_REAL_HTTP_CHECKED=true (8/8)
BYTE_IDENTITY_CURRENT=0
BYTE_IDENTITY_CHANGED=0
BYTE_IDENTITY_NOT_FOUND=0
BYTE_IDENTITY_UNAVAILABLE=138
BYTE_IDENTITY_AMBIGUOUS=0
BYTE_IDENTITY_CONFLICT=0
SUM_EQUALS_INPUT_COUNT=true (138=138)
GOVERNANCE_LOCKS_TOUCHED=false
REAL_AUTHORITY_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
PGVECTOR_WRITES=0
```
