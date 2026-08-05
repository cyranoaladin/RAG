"""Gate de démarrage — contrôle bloquant des profils de production (LOT44c).

Combine ``load_profile_registry`` et ``verify_profile_manifest`` en un seul
appel destiné à être invoqué **au démarrage d'un processus réel**, avant
que ce processus ne serve la moindre requête : échec explicite (exception
non interceptée) si le manifest est absent, le registre est absent/vide/
invalide, un profil déclaré manque, un profil non déclaré est présent, ou
qu'une empreinte a dérivé.

Aucun paramètre de contournement (pas de ``skip_validation``, pas de
``allow_missing``) : la fonction ne peut être appelée qu'en mode strict.
Ce module ne construit lui-même aucun processus, aucun serveur, aucune
boucle — c'est une fonction pure d'orchestration synchrone, appelée une
fois, qui retourne ou lève.

Portée non couverte par ce lot (LOT44c) : le câblage de cet appel dans le
processus FastAPI réellement déployé en production
(``services/rag-engine/src/ingestor/app_v2.py`` et alentours, livrés par
LOT43) nécessiterait de modifier un fichier d'un lot antérieur, ce qui est
explicitement hors périmètre de cette passe. Ce module fournit donc un
point d'entrée CLI autonome (``__main__`` ci-dessous), directement
invocable (``python -m ingestor.ingestion_profiles.startup_gate``,
utilisable comme étape de pré-démarrage/healthcheck dans un pipeline de
déploiement) sans toucher à aucun fichier LOT43/44a/44b.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from .manifest import ManifestVerification, verify_profile_manifest
from .registry import load_profile_registry


@dataclass(frozen=True)
class StartupGateResult:
    """Preuve qu'un démarrage a été autorisé — jamais construite sans
    passage réel par ``verify_profile_manifest``."""

    manifest: ManifestVerification
    profiles_dir: Path
    manifest_path: Path


def enforce_production_manifest_gate(
    profiles_dir: Path,
    manifest_path: Path,
) -> StartupGateResult:
    """Charge le registre puis vérifie le manifest — échoue explicitement
    si l'un des deux échoue, jamais de valeur de repli.

    - Répertoire de profils absent ou vide → le registre est vide →
      ``verify_profile_manifest`` échoue nécessairement (le manifest ne
      peut jamais être vide, cf. ``manifest.py``) : **aucun démarrage
      silencieux sans aucun profil**.
    - Un seul fichier profil structurellement invalide fait échouer le
      chargement entier du registre (``ProfileRegistryLoadError``,
      propagée sans être interceptée) — jamais un démarrage avec un
      registre partiel.
    - Aucun paramètre ne permet de désactiver tout ou partie de ces
      vérifications.
    """
    registry = load_profile_registry(profiles_dir)
    verification = verify_profile_manifest(registry, manifest_path)
    return StartupGateResult(
        manifest=verification,
        profiles_dir=profiles_dir,
        manifest_path=manifest_path,
    )


def _main() -> int:
    """Point d'entrée CLI autonome — exit code non nul en cas d'échec.

    Usage : ``python -m ingestor.ingestion_profiles.startup_gate
    <profiles_dir> <manifest_path>``. Ne dépend d'aucun autre processus
    LOT43 : peut être invoqué isolément (pré-démarrage, healthcheck CI/CD,
    étape de pipeline de déploiement).
    """
    if len(sys.argv) != 3:
        print(
            "usage: python -m ingestor.ingestion_profiles.startup_gate "
            "<profiles_dir> <manifest_path>",
            file=sys.stderr,
        )
        return 2
    profiles_dir = Path(sys.argv[1])
    manifest_path = Path(sys.argv[2])
    try:
        result = enforce_production_manifest_gate(profiles_dir, manifest_path)
    except Exception as exc:  # noqa: BLE001 - frontière CLI volontaire
        print(f"STARTUP_GATE_FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"STARTUP_GATE_PASSED: {result.manifest.declared_count} profile(s), "
        f"manifest_fingerprint={result.manifest.manifest_fingerprint}, "
        f"provenance={result.manifest.provenance!r}, "
        f"generated_at={result.manifest.generated_at!r}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - couvert par les tests via _main()
    sys.exit(_main())


__all__ = ["StartupGateResult", "enforce_production_manifest_gate"]
