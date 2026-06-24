# Protocole de brouillon réel minimal metadata-only

## 1. Objectif

Ce protocole prépare un futur passage de fixtures synthétiques vers un brouillon
réel metadata-only limité à 1 ou 2 ressources autorisées. Il ne crée pas de
manifest réel prêt pour import et ne traite aucun document source.

Le but est de cadrer le travail humain préalable : collecter des métadonnées,
documenter les droits, valider le contexte pédagogique et garder un verrou
humain avant toute commande plus avancée.

## 2. Ce que ce protocole autorise

Autorisé plus tard, après validation humaine :

- renseigner manuellement 1 à 2 lignes de métadonnées ;
- indiquer un `source_uri` local ou institutionnel déjà autorisé ;
- renseigner un SHA-256 calculé manuellement hors pipeline ;
- renseigner droits, visibilité, provenance, niveau, matière, notions,
  compétences ;
- lancer uniquement des validateurs metadata-only.

## 3. Ce que ce protocole interdit

Interdictions explicites :

- copier un PDF dans le dépôt ;
- ouvrir un PDF ;
- parser un PDF ;
- OCR ;
- embedding ;
- Qdrant ;
- scraping ;
- ingestion documentaire réelle ;
- création de `data/staging` ;
- écriture dans ledger permanent ;
- usage de document du RAG historique ;
- `source_uri` vers `rag-local` ou `rag-ui` ;
- droits inconnus récupérables ;
- source `pending` utilisée seule pour une règle réglementaire.

## 4. Champs obligatoires

Chaque ligne future devra porter au minimum :

- `doc_id` ;
- `source_uri` ;
- `source_type` ;
- `sha256` ;
- `discovered_at` ;
- `rights` ;
- `visibility` ;
- `niveau` ;
- `voie` ;
- `matiere` ;
- `statut_enseignement` ;
- `type_doc` ;
- `epreuve` ;
- `candidat` ;
- `programme_version` ;
- `bo_reference` si applicable ;
- `notions` ;
- `competences` ;
- `official_level_ref` ;
- `official_subject_ref` ;
- `candidate_status_ref` ;
- `establishment_context_ref` ;
- `extra.zone`.

## 5. Conditions de passage vers un futur lot réel

Un futur lot réel ne peut être lancé que si :

- le dépôt est propre ;
- le protocole est relu par un humain ;
- les documents sources sont listés hors dépôt ;
- les droits sont connus ;
- les SHA-256 sont calculés manuellement ;
- aucune donnée personnelle n’est présente ;
- aucun document propriétaire non autorisé n’est inclus ;
- les sources officielles sont vérifiées ;
- le contexte AEFE Tunisie est explicitement validé ;
- le statut candidat scolarisé est cohérent.

## 6. Checklist de validation humaine

- [ ] Le lot contient 1 à 2 ressources maximum.
- [ ] Chaque ressource est listée hors dépôt.
- [ ] Aucun fichier source n’a été copié dans le dépôt.
- [ ] Aucun PDF n’a été ouvert par le pipeline.
- [ ] Aucun document ne vient du RAG historique.
- [ ] Les droits sont explicites et non `unknown`.
- [ ] La visibilité est cohérente avec les droits.
- [ ] Le SHA-256 est calculé manuellement hors pipeline.
- [ ] Le `source_uri` ne pointe pas vers `rag-local`.
- [ ] Le `source_uri` ne pointe pas vers `rag-ui`.
- [ ] Aucun secret, credential ou fichier d’environnement n’est référencé.
- [ ] La zone AEFE Tunisie est confirmée dans `extra.zone`.
- [ ] `establishment_context_ref=aefe` si `extra.zone=aefe_tunisie`.
- [ ] `candidat=scolarise` est cohérent avec `candidate_status_ref=scolarise`.
- [ ] Aucune source `pending` ne soutient seule une règle réglementaire.
- [ ] Aucune donnée personnelle élève n’est présente.
- [ ] Un humain a relu les métadonnées avant tout validateur.

## 7. Critères d’arrêt immédiat

Arrêter si :

- `rights=unknown` ;
- chemin vers `rag-local` ;
- chemin vers `rag-ui` ;
- secret détecté ;
- PDF copié ;
- `data/staging` créé ;
- ledger permanent modifié ;
- source réglementaire `pending` seule ;
- doute sur droits ;
- donnée personnelle élève.

## 8. Commandes futures autorisées

Commandes metadata-only existantes ou futures garde-fous :

```bash
make pilot-template-check
make pilot-compile-check
make pilot-rehearsal
make real-draft-guard-check
```

Ne pas utiliser de commande d’ingestion, scraping, Qdrant, API ou Docker dans ce
cadre.

## 9. Limites

Ce protocole ne valide pas le contenu pédagogique des ressources. Il vérifie
uniquement la discipline metadata-only, les droits, la cohérence minimale du
profil terminale spécialité mathématiques, le contexte AEFE Tunisie et les
verrous humains avant un futur lot réel.

