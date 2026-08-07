"""Revue incrémentale PR#90 (Cubic P3) : surface publique de
``ingestor.ingestion_control`` — vérifie que chaque nom déclaré dans
``__all__`` est réellement importable, et que les exceptions de conflit de
bail destinées à être attrapées par un appelant externe (ex. un futur
scheduler/worker qui importerait le paquet plutôt que ses sous-modules)
sont bien re-exportées au niveau du paquet, pas seulement accessibles via
un import direct du sous-module.
"""
from __future__ import annotations

import ingestor.ingestion_control as ingestion_control


def test_all_names_in_dunder_all_are_actually_importable() -> None:
    missing = [name for name in ingestion_control.__all__ if not hasattr(ingestion_control, name)]
    assert missing == [], f"__all__ declares names not actually present on the module: {missing}"


def test_resource_lease_conflict_error_is_reexported_at_package_level() -> None:
    """Revue incrémentale PR#90 (Cubic P3) : avant ce correctif,
    ``ResourceLeaseConflictError`` n'était importable que via
    ``ingestor.ingestion_control.claim`` — absent de ``__init__.py``/
    ``__all__`` malgré ``claim_resource`` (qui la lève) déjà réexporté au
    niveau du paquet, une incohérence pour un appelant qui voudrait
    attraper cette exception sans connaître le sous-module exact."""
    from ingestor.ingestion_control.claim import ResourceLeaseConflictError as direct_import

    assert ingestion_control.ResourceLeaseConflictError is direct_import
    assert "ResourceLeaseConflictError" in ingestion_control.__all__
