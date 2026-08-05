"""Persistance éventuelle des résultats de validation (LOT44c).

Réutilise exclusivement la table ``ingestion_control.workflow_events``
(LOT44b, migration 003, déjà commitée — jamais modifiée). Aucune nouvelle
table, aucune nouvelle migration : ``event_type``/``payload`` (JSONB) sont
déjà génériques et suffisent à porter un résultat de validation structuré.

``candidate_id``/``artifact_id`` n'ont pas de colonne dédiée dans
``workflow_events`` (schéma figé LOT44b) : ils sont portés dans ``payload``
quand l'appelant les fournit, jamais ajoutés comme colonne.

Ne committe pas la transaction : responsabilité de l'appelant (même
convention que les quatre primitives LOT44b).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from .validation import ValidationResult

#: Valeur de ``workflow_events.event_type`` réservée aux résultats de
#: validation de profil — une chaîne libre parmi d'autres, la colonne ne
#: porte aucune contrainte CHECK sur son contenu (LOT44b, 003).
PROFILE_VALIDATION_EVENT_TYPE = "profile_validation"

#: Version du contrat de ``payload`` pour ``PROFILE_VALIDATION_EVENT_TYPE``
#: — portée dans le payload lui-même (``event_contract_version``), jamais
#: dans le schéma SQL (``workflow_events`` reste générique, LOT44b figé).
#: Toute évolution incompatible de la structure du payload (champ retiré,
#: type changé) doit incrémenter cette valeur ; un ajout de champ optionnel
#: ne le nécessite pas (même logique que le SemVer d'ADR-0002, appliquée
#: ici à un contrat de payload JSONB plutôt qu'à un modèle Pydantic).
#: Toujours présent dans le payload, jamais optionnel (vérifié par test).
PROFILE_VALIDATION_EVENT_CONTRACT_VERSION = "1"

#: Plafond explicite de taille du payload sérialisé — pas seulement un
#: nombre théorique de champs. ``record_validation_result`` refuse
#: d'insérer un payload qui dépasse cette taille plutôt que de laisser
#: PostgreSQL l'accepter silencieusement (JSONB n'a pas de limite propre
#: en pratique, hors la limite de ligne TOAST de PostgreSQL, ~1 Go —
#: beaucoup trop permissif pour servir de garde-fou applicatif). 256 Kio
#: est très large par rapport à la forme actuelle d'un payload (au plus
#: une vingtaine de champs scalaires + une liste d'``issues`` bornée par
#: le nombre de champs de ``CollectionProfile``/``ResourceScope``), mais
#: reste un plafond réel et testé, pas une estimation non vérifiée.
MAX_PAYLOAD_BYTES = 262_144


class PayloadTooLargeError(ValueError):
    """Le payload sérialisé dépasse ``MAX_PAYLOAD_BYTES`` — rejet explicite
    avant toute tentative d'insertion, jamais une troncature silencieuse."""


def canonical_json_bytes(payload: dict[str, object]) -> bytes:
    """Sérialisation JSON réellement canonique et déterministe, utilisée
    pour mesurer la taille du payload avant insertion.

    Paramètres explicites, chacun justifié :
    - ``sort_keys=True`` : ordre des clés indépendant de l'ordre
      d'insertion dans le ``dict`` Python — deux appels construisant le
      même contenu dans un ordre différent produisent le même octet-flux.
    - ``ensure_ascii=True`` (défaut Python, rendu explicite) : tout
      caractère non-ASCII est échappé en ``\\uXXXX`` — la taille mesurée
      ne dépend jamais de l'encodage de la locale d'exécution.
    - ``separators=(",", ":")`` : aucun espace superflu — la taille
      mesurée est la taille minimale réelle, pas gonflée par un
      formatage lisible.
    - ``allow_nan=False`` : ``NaN``/``Infinity``/``-Infinity`` rejetés
      explicitement (``ValueError``) plutôt que sérialisés en JSON non
      standard — fail-closed, aucune valeur non représentable en JSON
      strict n'entre jamais dans ``workflow_events``.

    Distinct de la représentation JSONB effectivement stockée par
    PostgreSQL : ``psycopg.types.json.Jsonb`` délègue à PostgreSQL la
    normalisation binaire JSONB à l'écriture (espaces/ordre de clés
    normalisés par PostgreSQL lui-même) — cette fonction ne mesure que
    la taille du flux JSON envoyé, une approximation sûre et cohérente
    avec la limite ``MAX_PAYLOAD_BYTES`` (la représentation JSONB binaire
    n'est jamais strictement plus grande que le JSON textuel équivalent
    pour ce type de contenu majoritairement scalaire).
    """
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def record_validation_result(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    result: ValidationResult,
    actor: str,
    resource_id: UUID | None = None,
    candidate_id: UUID | None = None,
    artifact_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> UUID:
    """Journalise un résultat de validation comme ``workflow_events``.

    - ``job_id`` : jamais renseigné par cette fonction (reste ``NULL``,
      cohérent avec ADR-0025 — aucun producteur automatique en LOT44c).
    - ``from_state``/``to_state`` : ``NULL`` — cet événement n'est pas une
      transition d'état de ressource ; aucun appel à ``cas_transition``
      n'est effectué ici (LOT44c ne déclenche aucune transition).
    - ``idempotency_key`` : **détection de doublon, pas une idempotence
      complète** (contrat B, explicitement choisi — cf. ADR-0026). Une
      répétition avec la même clé **échoue** (``UniqueViolation``, index
      partiel unique de LOT44b, colonne seule) ; elle ne renvoie jamais le
      résultat déjà enregistré et **ignore le contenu du payload** — même
      clé + payload différent échoue identiquement à même clé + payload
      identique. La même clé réutilisée pour un ``run_id`` ou un
      ``resource_id`` différent échoue tout autant : l'unicité porte
      uniquement sur la valeur de la clé, jamais sur une combinaison avec
      d'autres colonnes. ``None`` par défaut — un enregistrement ordinaire
      n'en reçoit pas automatiquement, seul un appelant qui sait produire
      un événement potentiellement rejoué en fournit une explicitement.
    - **Taille du payload** : mesurée via ``canonical_json_bytes()``
      (JSON canonique — ``sort_keys=True``, ``ensure_ascii=True``,
      ``separators=(",", ":")``, ``allow_nan=False``) ; rejetée avant
      toute insertion (``PayloadTooLargeError``) si elle dépasse
      ``MAX_PAYLOAD_BYTES`` — un plafond réel et mesuré, pas seulement un
      nombre de champs supposé petit. Réserve : cette vérification n'est
      appliquée que par cette fonction — un futur code qui insérerait
      directement dans ``workflow_events`` sans passer par elle
      contournerait la limite (aucune contrainte SQL équivalente sur
      la migration 003, gelée).
    """
    payload: dict[str, object] = {
        "kind": PROFILE_VALIDATION_EVENT_TYPE,
        "event_contract_version": PROFILE_VALIDATION_EVENT_CONTRACT_VERSION,
        "status": result.status,
        "collection": result.collection,
        "profile_version": result.profile_version,
        "profile_fingerprint": result.profile_fingerprint,
        "issues": [
            {"code": issue.code, "path": issue.path, "message": issue.message}
            for issue in result.issues
        ],
    }
    if candidate_id is not None:
        payload["candidate_id"] = str(candidate_id)
    if artifact_id is not None:
        payload["artifact_id"] = str(artifact_id)

    canonical_payload = canonical_json_bytes(payload)
    serialized_size = len(canonical_payload)
    if serialized_size > MAX_PAYLOAD_BYTES:
        raise PayloadTooLargeError(
            f"payload is {serialized_size} bytes, exceeds MAX_PAYLOAD_BYTES={MAX_PAYLOAD_BYTES}"
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.workflow_events
                (run_id, job_id, resource_id, event_type, from_state, to_state,
                 actor, payload, idempotency_key)
            VALUES (%s, NULL, %s, %s, NULL, NULL, %s, %s, %s)
            RETURNING event_id
            """,
            (
                run_id,
                resource_id,
                PROFILE_VALIDATION_EVENT_TYPE,
                actor,
                Jsonb(payload),
                idempotency_key,
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - INSERT ... RETURNING toujours une ligne
            raise RuntimeError("workflow_events insert did not return event_id")
        event_id: UUID = row[0]
        return event_id


@dataclass(frozen=True)
class DriftCheckResult:
    """Résultat d'une comparaison d'empreinte contre l'historique persisté.

    Une simple primitive de calcul SHA-256 (``profile_fingerprint``) ne
    constitue pas, à elle seule, une détection de dérive : cette fonction
    est ce qui compare réellement une empreinte courante à la dernière
    empreinte persistée pour la même identité ``(collection,
    profile_version)`` et rend un verdict explicite.
    """

    drift_detected: bool
    has_history: bool
    previous_fingerprint: str | None
    previous_event_id: UUID | None
    current_fingerprint: str


def detect_profile_drift(
    conn: psycopg.Connection,
    *,
    collection: str,
    profile_version: str,
    current_fingerprint: str,
    exclude_event_id: UUID | None = None,
) -> DriftCheckResult:
    """Compare l'empreinte courante d'un profil à la dernière empreinte
    persistée pour la même identité ``(collection, profile_version)``.

    - **Lecture seule** : un seul ``SELECT``, aucune écriture, aucune
      primitive de concurrence LOT44b nécessaire (pas de claim, pas de CAS).
    - **Ordre totalement déterministe** : ``ORDER BY occurred_at DESC,
      event_id DESC`` — ``event_id`` (UUID généré par ``gen_random_uuid()``
      à l'insertion, jamais ``NULL``) sert de départage immuable quand
      plusieurs événements partagent exactement le même ``occurred_at``
      (cf. Décision 6, ADR-0026 : PostgreSQL ``now()`` = début de
      transaction). Cela rend la **requête** reproductible (deux appels
      successifs sur les mêmes données renvoient toujours la même ligne) —
      cela ne restaure PAS un ordre chronologique réel entre deux
      événements réellement simultanés : ``event_id`` n'est pas corrélé à
      l'ordre d'écriture, seulement stable et unique. Aucune colonne de
      séquence n'existe dans le schéma LOT44b figé pour faire mieux.
    - **Événement courant exclu explicitement** : ``exclude_event_id``
      permet à un appelant qui vient d'insérer son propre événement (via
      ``record_validation_result``) de l'exclure de la comparaison —
      sans ce paramètre, appeler cette fonction *après* avoir enregistré
      le résultat courant comparerait l'empreinte à elle-même et
      renverrait toujours ``drift_detected=False`` de façon triviale.
      Convention recommandée : appeler ``detect_profile_drift`` **avant**
      ``record_validation_result`` pour la même identité ; si l'ordre
      inverse est nécessaire, fournir ``exclude_event_id``.
    - **Aucun historique** (``has_history=False``) : première validation
      connue pour cette identité — jamais traité comme une dérive.
    - **Événements sans empreinte ignorés** : un événement dont
      ``profile_fingerprint`` est ``NULL`` (``profile_unknown``,
      ``profile_disabled``, ou ``technical_error`` — cf. ``validation.py``,
      la frontière ``technical_error`` ne propage jamais l'empreinte
      calculée en interne) est exclu par le ``WHERE ... IS NOT NULL`` : la
      comparaison remonte au dernier événement qui portait réellement une
      empreinte, jamais à un événement qui n'en avait pas.
    - **Écritures concurrentes** : deux appels concurrents à
      ``record_validation_result`` sans clé d'idempotence partagée créent
      simplement deux lignes indépendantes (``INSERT`` sans verrou,
      sûr nativement en PostgreSQL) ; un ``detect_profile_drift`` exécuté
      pendant que l'une des deux transactions n'est pas encore commitée ne
      la voit pas (isolation de transaction standard), donc ne peut
      raisonner que sur l'historique déjà visible/commité.
    - **Historique identique** : ``drift_detected=False``.
    - **Historique différent** : ``drift_detected=True`` — le contenu du
      profil a changé entre deux exécutions sous la même identité
      ``(collection, profile_version)``, ce qui contredit la convention
      « toute nouvelle définition porte une nouvelle version » (ADR-0026,
      décision 1). Cette fonction **constate** la dérive, elle ne
      l'empêche pas et ne rejette rien elle-même : c'est à l'appelant
      (futur LOT44d+) de décider de la réaction (alerte, blocage, etc.).
    - Requête filtrée sur les champs JSONB du payload (pas d'index dédié
      sur ``payload`` — schéma LOT44b figé) : acceptable au volume actuel
      (zéro donnée de production), à réévaluer si le volume d'événements
      justifie un index fonctionnel dans un futur lot.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT payload->>'profile_fingerprint', event_id
            FROM ingestion_control.workflow_events
            WHERE event_type = %s
              AND payload->>'collection' = %s
              AND payload->>'profile_version' = %s
              AND payload->>'profile_fingerprint' IS NOT NULL
              AND (%s::uuid IS NULL OR event_id != %s)
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT 1
            """,
            (
                PROFILE_VALIDATION_EVENT_TYPE,
                collection,
                profile_version,
                exclude_event_id,
                exclude_event_id,
            ),
        )
        row = cur.fetchone()

    if row is None:
        return DriftCheckResult(
            drift_detected=False,
            has_history=False,
            previous_fingerprint=None,
            previous_event_id=None,
            current_fingerprint=current_fingerprint,
        )

    previous_fingerprint: str = row[0]
    previous_event_id: UUID = row[1]
    return DriftCheckResult(
        drift_detected=previous_fingerprint != current_fingerprint,
        has_history=True,
        previous_fingerprint=previous_fingerprint,
        previous_event_id=previous_event_id,
        current_fingerprint=current_fingerprint,
    )


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "PROFILE_VALIDATION_EVENT_CONTRACT_VERSION",
    "PROFILE_VALIDATION_EVENT_TYPE",
    "DriftCheckResult",
    "PayloadTooLargeError",
    "canonical_json_bytes",
    "detect_profile_drift",
    "record_validation_result",
]
