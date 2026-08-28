"""Un rôle `student` doit pouvoir lire le corpus effectivement servi.

Ce test manquait, et c'est pourquoi le défaut a traversé tout le pipeline :
construction, scellement, ingestion, CI verte et mise en service, sans que
personne n'ait jamais interrogé sous le rôle auquel le produit est destiné.
Les tests d'intégration existants passaient parce qu'ils emploient des rôles
privilégiés — `teacher`, `admin`, `reviewer`.

Le contrôle porte ici sur **toutes** les visibilités présentes dans les scopes
`_v2` servis, pas sur un échantillon.
"""

from __future__ import annotations

import pytest

from ingestor.retrieval_scope_v2 import allowed_visibilities_for_role


def _visibilites_servies() -> set[str]:
    """Visibilités réellement portées par les scopes `_v2` de production."""
    from nexus_contracts import load_retrieval_scope_registry

    registre = load_retrieval_scope_registry()
    return {
        str(getattr(v, "value", v))
        for identifiant, artefact in registre.items()
        if identifiant.endswith("_v2")
        for v in (artefact.evidence_subject.visibility,)
    }


def test_le_role_student_couvre_toutes_les_visibilites_servies() -> None:
    """Aucune collection servie ne doit être hors de portée d'un élève."""
    servies = _visibilites_servies()
    assert servies, "aucun scope _v2 : le contrôle porterait sur le vide"

    accordees = set(allowed_visibilities_for_role("student"))
    hors_portee = servies - accordees
    assert not hors_portee, (
        f"un profil élève ne peut pas lire les collections en {sorted(hors_portee)} — "
        f"or c'est la visibilité de collections effectivement servies. "
        f"Accordées à `student` : {sorted(accordees)}"
    )


def test_student_n_obtient_pas_les_visibilites_sensibles() -> None:
    """Ouvrir `internal` ne doit pas ouvrir `restricted` ni `private`.

    La décision du 28/08/2026 portait sur `internal` seul. `restricted` et
    `private` désignent autre chose et restent fermés : élargir au-delà de ce
    qui a été décidé serait exactement le glissement que la gouvernance refuse.
    """
    accordees = set(allowed_visibilities_for_role("student"))
    assert "restricted" not in accordees
    assert "private" not in accordees


@pytest.mark.parametrize("role", ["teacher", "reviewer", "admin", "ingest_agent"])
def test_les_autres_roles_sont_inchanges(role: str) -> None:
    """La décision ne touche que `student` : aucun autre rôle n'est élargi."""
    attendu = {
        "teacher": {"public", "internal"},
        "reviewer": {"public", "internal", "restricted"},
        "ingest_agent": {"internal", "restricted"},
        "admin": {"public", "internal", "restricted", "private"},
    }[role]
    assert set(allowed_visibilities_for_role(role)) == attendu
