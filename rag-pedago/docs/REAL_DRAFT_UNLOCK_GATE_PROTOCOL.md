# Protocole de gate combiné — human unlock + real draft metadata

## 1. Objectif

Le gate combiné ne donne toujours pas le droit de parser ou ingérer des
documents. Il vérifie seulement la cohérence entre une autorisation humaine
synthétique ou metadata-only et un brouillon metadata-only candidat.

## 2. Entrées attendues

- fichier human unlock JSON ;
- fichier metadata candidate JSONL ;
- aucun document source ;
- aucun PDF ;
- aucune lecture `source_uri`.

## 3. Conditions de validation

Le gate combiné est valide seulement si :

- `human_unlock_guard` valide l’autorisation ;
- `real_draft_guard` valide le brouillon metadata-only ;
- nombre d’items du brouillon <= `max_items` de l’autorisation ;
- chaque item respecte :
  - `allowed_subject` ;
  - `allowed_level` ;
  - `allowed_track` ;
  - `allowed_teaching` ;
  - `allowed_zone` ;
  - `allowed_candidate_status` ;
- chaque item contient `extra.manual_human_review_required=true` ;
- chaque item contient un `batch_id` ou équivalent cohérent avec l’autorisation si le champ existe ;
- aucun `rights=unknown` ;
- aucun chemin interdit ;
- aucune source `pending` seule ;
- aucun secret ;
- aucun document réel ;
- aucun `data/staging`.

## 4. Conditions de refus

Refuser si :

- autorisation absente ;
- autorisation invalide ;
- brouillon invalide ;
- nombre d’items supérieur à `max_items` ;
- matière différente ;
- niveau différent ;
- voie différente ;
- enseignement différent ;
- zone différente ;
- statut candidat différent ;
- droits inconnus ;
- absence de validation humaine ;
- présence de chemin interdit ;
- présence de marqueur sensible ;
- source `pending` seule ;
- tentative d’utiliser `file://` réel ;
- tentative de produire un manifest prêt pour ingestion.

## 5. Limites

Le gate combiné ne valide pas le contenu pédagogique du document. Il ne valide
que le cadre metadata-only, les droits, le périmètre et la cohérence de
gouvernance.

