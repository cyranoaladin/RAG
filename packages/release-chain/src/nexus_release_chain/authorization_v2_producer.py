"""Le producteur canonique d'AuthorizationSetV2 — un seul, et il derive.

Pourquoi ce module existe
-------------------------

`AuthorizationSetV2` et `verify_authorization_binding_set_v2` vivent dans le
contrat depuis longtemps. Aucun code ne les appelait : la moitie V2 du contrat
n etait meme pas exportee par `nexus_contracts`. La migration semblait bloquee
faute de producteur ; elle etait bloquee faute de chemin d import.

Ce module est ce producteur. Il y en a UN, et le garde-fou d unicite d autorite
echoue si un second apparait.

Le principe qui gouverne tout le reste
--------------------------------------

Le producteur ne RESSAISIT jamais la liste des contenus autorises. Il la
DERIVE des placements de la release. Une liste ressaisie diverge le jour ou la
release change, et le jour ou elle diverge, l autorisation ne dit plus ce que
la release exige — elle dit ce que quelqu un a tape.

L operateur fournit ce qu il est seul a savoir : l identite de l autorisation,
son empreinte, sa liaison de revue, sa fenetre de validite. Le contenu, lui,
vient de la release.

Le producteur refuse de rendre un set qui ne passerait pas le gate d egalite
d ensemble. Verifier apres coup laisserait exister, ne serait-ce qu un instant,
un document d autorisation faux.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from nexus_contracts import (
    AuthorizationSetError,
    AuthorizationSetMemberV1,
    AuthorizationSetV2,
    ReleaseScopePlacementV2,
    content_set_digest,
    release_placement_binding_key,
    scope_digest,
    verify_authorization_binding_set_v2,
)

__all__ = [
    "AuthorizationFactsV1",
    "AuthorizationV2ProducerError",
    "produce_authorization_set_v2",
]


class AuthorizationV2ProducerError(AuthorizationSetError):
    """Refus du producteur. Sous-classe du refus de contrat : un appelant qui
    attrape deja les refus d autorisation attrape aussi ceux-ci."""


@dataclass(frozen=True)
class AuthorizationFactsV1:
    """Ce que l operateur apporte, et lui seul.

    Aucun champ ne porte de contenu : le contenu vient des placements. Ajouter
    ici une liste de `content_sha256` reintroduirait exactement la saisie que
    ce module existe pour supprimer.
    """

    authorization_id: str
    authorization_digest: str
    review_binding_digest: str
    valid_from: datetime
    valid_until: datetime


def produce_authorization_set_v2(
    *,
    release_scope_placement: ReleaseScopePlacementV2,
    authorization_facts_by_scope_digest: Mapping[str, AuthorizationFactsV1],
    corpus_manifest_sha256: str,
) -> AuthorizationSetV2:
    """Derive le set d autorisations EXIGE par une release scellee.

    `authorization_facts_by_scope_digest` est indexe par empreinte de scope, et
    non par nom : deux scopes de libelle proche ont des empreintes distinctes,
    et c est l empreinte que le gate compare.
    """
    contenus_par_scope: dict[str, list[str]] = {}
    scope_par_digest: dict[str, object] = {}
    for entree in release_scope_placement.placements:
        contenu, empreinte = release_placement_binding_key(entree)
        contenus_par_scope.setdefault(empreinte, []).append(contenu)
        scope_par_digest.setdefault(empreinte, entree.scope)

    exiges = set(contenus_par_scope)
    fournis = set(authorization_facts_by_scope_digest)

    non_autorises = sorted(exiges - fournis)
    if non_autorises:
        raise AuthorizationV2ProducerError(
            "la release exige des scopes qu aucune autorisation ne couvre : "
            f"{non_autorises!r}. Produire le set sans eux rendrait une "
            "autorisation incomplete, que le gate refuserait de toute facon."
        )

    surnumeraires = sorted(fournis - exiges)
    if surnumeraires:
        raise AuthorizationV2ProducerError(
            "des autorisations visent des scopes absents de la release : "
            f"{surnumeraires!r}. Les inclure autoriserait plus que ce que la "
            "release exige — c est la definition d une autorisation trop large."
        )

    membres: list[AuthorizationSetMemberV1] = []
    for empreinte in sorted(exiges):
        faits = authorization_facts_by_scope_digest[empreinte]
        contenus = tuple(sorted(set(contenus_par_scope[empreinte])))
        scope = scope_par_digest[empreinte]
        calculee = scope_digest(scope)
        if calculee != empreinte:
            raise AuthorizationV2ProducerError(
                f"empreinte de scope incoherente : {calculee} != {empreinte}"
            )
        try:
            membres.append(
                AuthorizationSetMemberV1.model_validate(
                    {
                        "authorization_id": faits.authorization_id,
                        "authorization_digest": faits.authorization_digest,
                        "review_binding_digest": faits.review_binding_digest,
                        "scope": scope,
                        "scope_digest": empreinte,
                        "allowed_content_sha256": contenus,
                        "allowed_content_count": len(contenus),
                        # Derivee elle aussi : recalculer l empreinte a partir
                        # des contenus derives interdit qu un ensemble et son
                        # empreinte divergent.
                        "allowed_content_set_sha256": content_set_digest(contenus),
                        "valid_from": faits.valid_from,
                        "valid_until": faits.valid_until,
                    }
                )
            )
        except Exception as exc:  # noqa: BLE001 - frontiere de contrat
            raise AuthorizationV2ProducerError(
                f"membre d autorisation invalide pour le scope {empreinte}: {exc}"
            ) from exc

    ensemble = AuthorizationSetV2.build(
        members=membres,
        corpus_manifest_sha256=corpus_manifest_sha256,
        profile_manifest_digest=release_scope_placement.profile_manifest_digest,
        release_scope_placement_digest=release_scope_placement.digest(),
    )

    # Le gate avant la sortie, jamais apres. Un set faux ne doit pas exister,
    # meme le temps d un retour de fonction.
    verify_authorization_binding_set_v2(
        ensemble, release_scope_placement=release_scope_placement
    )
    return ensemble
