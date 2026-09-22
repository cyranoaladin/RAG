"""La sélection de l'artefact batch se fait par identité, pas par date (lot CU).

``find_latest_artifact`` ordonne par ``collected_at``. Cette règle convient
au pipeline de découverte, où une nouvelle collecte remplace la précédente.
Elle ne convient pas au batch : la revue a couvert **un** artefact, et une
version plus récente ne doit pas être publiée à sa place.
"""

from __future__ import annotations

import inspect

from ingestor.ingestion_control import provisioning
from ingestor.ingestion_worker import publication_resume


def test_le_lecteur_par_identite_existe_et_filtre_sur_les_deux_cles() -> None:
    source = inspect.getsource(provisioning.find_authorised_artifact)
    assert "WHERE a.artifact_id = %s AND a.resource_id = %s" in source, (
        "l'artefact doit être cherché par SON identité ET sa ressource : un "
        "identifiant désignant l'artefact d'une autre ressource est un refus"
    )
    assert "ORDER BY" not in source, (
        "aucun ordre ne doit intervenir : il n'y a rien à départager"
    )
    assert "LIMIT" not in source


def test_un_artefact_inconnu_ou_d_une_autre_ressource_est_un_refus() -> None:
    """Pas de repli sur le plus récent quand l'identité ne correspond pas."""
    source = inspect.getsource(provisioning.find_authorised_artifact)
    assert "does not belong to resource" in source
    assert "never falls back to the" in source
    # La fonction ne rend jamais None : l'absence est une erreur, pas un cas
    # nominal que l'appelant pourrait traiter par un repli.
    signature = inspect.signature(provisioning.find_authorised_artifact)
    assert "None" not in str(signature.return_annotation)


def test_worker_b_nomme_l_artefact_quand_le_job_le_designe() -> None:
    source = inspect.getsource(publication_resume.resume_publication)
    assert 'payload.get("artifact_id")' in source
    position_nomme = source.index("find_authorised_artifact(")
    position_dernier = source.index("find_latest_artifact(")
    assert position_nomme < position_dernier, (
        "l'artefact nommé doit être cherché AVANT tout repli sur le plus récent"
    )


def test_le_repli_sur_le_plus_recent_est_documente_comme_non_autorisant() -> None:
    """``latest`` reste disponible pour le pipeline de découverte, mais la
    docstring doit dire qu'il n'est pas une règle d'autorité pour le batch."""
    doc = inspect.getdoc(provisioning.find_latest_artifact) or ""
    assert "n'est pas une règle d'autorité pour le batch" in doc
    assert "find_authorised_artifact" in doc
