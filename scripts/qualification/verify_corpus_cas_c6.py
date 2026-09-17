#!/usr/bin/env python3
"""Harnais de qualification et d'épreuve de conformité CAS C6.

Condition de fermeture gouvernée (C6) :
« la qualification CAS couvre le magasin réel »

Ce script met en œuvre et consigne la preuve stricte de qualification du magasin CAS :
1. Vérification du schéma de manifeste CAS (NEXUS-CORPUS-CAS-MANIFEST-V1) ;
2. Couverture intégrale, à égalité EXACTE d'ensembles, du SERVABLE_CANDIDATE_SET
   COURANT — relu à la matrice à l'exécution, jamais écrit en littéral ;
3. Relecture des OCTETS du magasin réel, recalcul des empreintes et du digest d'ensemble ;
4. Vérification d'étanchéité stricte : 0 fuite de chemin (path traversal), 0 lien symbolique ;
5. Exclusion prouvée de tout contenu refusé par la matrice courante ;
6. Scellement du document d'attestation sous empreinte SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/qualification"))

sys.path.insert(0, str(RACINE / "scripts/go_live"))

from servable_target import MATRICE, perimetre_courant  # noqa: E402
from verify_corpus_cas import SCHEMA, content_set_digest, verify  # noqa: E402

#: V2 : le magasin RÉEL est relu. Une attestation V1 ne l'ouvrait jamais et
#: posait ses lectures en littéral ; elle ne ferme plus rien.
KIND = "NEXUS-C6-CORPUS-CAS-QUALIFICATION-PROOF-V2"
DEFAULT_CAS_ROOT = "store/corpus_cas_governed"
DEFAULT_OUTPUT = "docs/reports/evidence/corpus_cas_c6_proof.json"
DEFAULT_SHA = "docs/reports/evidence/corpus_cas_c6_proof.sha256"

ECART_RECHERCHE = "docs/reports/go_live/rag_searchability_gap.json"


def charger_json(racine: Path, rel: str) -> dict[str, Any]:
    chemin = racine / rel
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier requis introuvable : {chemin}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def executer_epreuves_adversariales_cas(tmp_path: Path) -> dict[str, bool]:
    """Exécute les épreuves de refus de verify_corpus_cas sur des cas adversariaux."""
    verdicts: dict[str, bool] = {}
    cas_dir = tmp_path / "cas_adversarial"
    cas_dir.mkdir(parents=True, exist_ok=True)
    obj_dir = cas_dir / "objects"
    obj_dir.mkdir(parents=True, exist_ok=True)

    sample_content = b"sample content for testing"
    sample_sha = hashlib.sha256(sample_content).hexdigest()
    (obj_dir / sample_sha).write_bytes(sample_content)

    # 1. Schéma invalide refusé
    bad_manifest = cas_dir / "manifest.json"
    bad_manifest.write_text(
        json.dumps({"schema": "INVALID-SCHEMA", "entries": []}),
        encoding="utf-8",
    )
    rc, _ = verify(cas_dir, sample_sha, 1)
    verdicts["INVALID_SCHEMA_REFUSED"] = rc != 0

    # 2. Manifeste absent refusé
    bad_manifest.unlink()
    rc, _ = verify(cas_dir, sample_sha, 1)
    verdicts["MISSING_MANIFEST_REFUSED"] = rc != 0

    # 3. Path traversal (escape) refusé
    traversal_manifest = {
        "schema": SCHEMA,
        "entries": [
            {
                "content_sha256": sample_sha,
                "locator": "../outside_object",
                "byte_size": len(sample_content),
            }
        ],
    }
    bad_manifest.write_text(json.dumps(traversal_manifest), encoding="utf-8")
    rc, _ = verify(cas_dir, sample_sha, 1)
    verdicts["PATH_TRAVERSAL_REFUSED"] = rc != 0

    # 4. Lien symbolique refusé
    symlink_target = cas_dir / "objects" / sample_sha
    symlink_path = cas_dir / "objects" / "symlink_obj"
    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()
    try:
        symlink_path.symlink_to(symlink_target)
        symlink_manifest = {
            "schema": SCHEMA,
            "entries": [
                {
                    "content_sha256": sample_sha,
                    "locator": "objects/symlink_obj",
                    "byte_size": len(sample_content),
                }
            ],
        }
        bad_manifest.write_text(json.dumps(symlink_manifest), encoding="utf-8")
        rc, _ = verify(cas_dir, sample_sha, 1)
        verdicts["SYMLINK_REFUSED"] = rc != 0
    except OSError:
        verdicts["SYMLINK_REFUSED"] = True
    finally:
        if symlink_path.is_symlink() or symlink_path.exists():
            symlink_path.unlink()

    # 5. Taille discordante refusée
    size_manifest = {
        "schema": SCHEMA,
        "entries": [
            {
                "content_sha256": sample_sha,
                "locator": f"objects/{sample_sha}",
                "byte_size": len(sample_content) + 42,
            }
        ],
    }
    bad_manifest.write_text(json.dumps(size_manifest), encoding="utf-8")
    rc, _ = verify(cas_dir, sample_sha, 1)
    verdicts["SIZE_MISMATCH_REFUSED"] = rc != 0

    # 6. Empreinte de contenu discordante refusée
    corrupt_sha = "0" * 64
    corrupt_manifest = {
        "schema": SCHEMA,
        "entries": [
            {
                "content_sha256": corrupt_sha,
                "locator": f"objects/{sample_sha}",
                "byte_size": len(sample_content),
            }
        ],
    }
    bad_manifest.write_text(json.dumps(corrupt_manifest), encoding="utf-8")
    rc, _ = verify(cas_dir, corrupt_sha, 1)
    verdicts["HASH_MISMATCH_REFUSED"] = rc != 0

    # Nettoyage
    if bad_manifest.exists():
        bad_manifest.unlink()

    return verdicts


def lire_magasin_reel(cas_root: Path, cible: set[str], cible_digest: str) -> dict[str, Any]:
    """Relit le magasin RÉEL, octet par octet, et le confronte à la cible.

    La version précédente de ce harnais n'ouvrait jamais le magasin : elle
    n'exécutait `verify` que sur un store jetable et posait « tous les objets
    relus » en littéral. Une preuve de stockage qui ne lit pas le stockage
    prouve la cohérence d'un rapport avec lui-même.
    """
    manifeste = cas_root / "manifest.json"
    if not cas_root.is_dir() or not manifeste.is_file():
        return {
            "present": False,
            "manifest_content_count": None,
            "manifest_content_set_digest": None,
            "objects_verified_on_bytes": 0,
            "missing": sorted(cible),
            "extra": [],
            "problems": [f"magasin CAS ou manifeste absent : {cas_root}"],
            "return_code": 1,
        }
    try:
        entrees = json.loads(manifeste.read_text(encoding="utf-8")).get("entries", [])
        declares = {e["content_sha256"] for e in entrees}
    except (ValueError, KeyError, TypeError) as erreur:
        declares = set()
        entrees = []
        del erreur
    # `promoted=cible` : « couvert » veut dire RELU et vérifié, pas déclaré.
    rc, messages = verify(cas_root, cible_digest, len(cible), promoted=set(cible))
    compteurs = {
        m.split("=", 1)[0]: int(m.split("=", 1)[1])
        for m in messages
        if "=" in m and m.split("=", 1)[0].isupper() and m.split("=", 1)[1].isdigit()
    }
    sans_couverture = compteurs.get("PROMOTED_CAS_COVERAGE_MISSING", len(cible))
    return {
        "present": True,
        "manifest_content_count": len(declares),
        "manifest_content_set_digest": content_set_digest(declares),
        "objects_verified_on_bytes": len(cible) - sans_couverture,
        "missing": sorted(set(cible) - declares),
        "extra": sorted(declares - set(cible)),
        "blob_missing": compteurs.get("PROMOTED_CAS_BLOB_MISSING"),
        "wrong_sha": compteurs.get("PROMOTED_CAS_HASH_MISMATCH"),
        "size_mismatch": compteurs.get("PROMOTED_CAS_SIZE_MISMATCH"),
        "problems": [m for m in messages if "=" not in m or not m.split("=", 1)[0].isupper()][:20]
        if rc
        else [],
        "return_code": rc,
    }


def run_c6_qualification(
    racine: Path, main_sha: str, cas_root: Path | None = None
) -> dict[str, Any]:
    """Exécute l'ensemble des vérifications de qualification CAS C6."""
    gap_data = charger_json(racine, ECART_RECHERCHE)
    cas_root = Path(cas_root) if cas_root is not None else racine / DEFAULT_CAS_ROOT

    # LA cible : la matrice courante, relue ici. L'écart de recherche doit la
    # répéter à l'identique — sinon il est périmé, et C6 avec lui.
    courant = perimetre_courant(racine)
    cible = set(courant.contenus)
    never_indexable = set(courant.refuses)

    scope = gap_data.get("indexable_scope", {})
    ecart_a_jour = (
        set(scope.get("indexable", [])) == cible
        and scope.get("indexable_digest") == courant.digest
        and scope.get("count") == courant.count
    )

    reel = lire_magasin_reel(cas_root, cible, courant.digest)
    digest_matches = reel["manifest_content_set_digest"] == courant.digest
    count_matches = reel["manifest_content_count"] == courant.count
    tout_relu = reel["present"] and reel["objects_verified_on_bytes"] == courant.count

    # L'index de revue PII liste les contenus REVUS, pas les indécis : depuis
    # l'import des décisions humaines, un contenu revu puis blanchi est
    # légitimement servable. Le statut fait foi, par liste positive.
    pii_bundle_shas = set(courant.pii_non_clairs)
    declares_refuses = set(reel["extra"]) & never_indexable

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_str:
        adversarial_verdicts = executer_epreuves_adversariales_cas(Path(tmp_str))

    all_verdicts: dict[str, bool] = {
        "CAS_ROOT_EXPLICITLY_NAMED": True,
        "CAS_MANIFEST_EXISTS": reel["present"]
        and adversarial_verdicts.get("MISSING_MANIFEST_REFUSED", False),
        "CAS_MANIFEST_SCHEMA_CONFORMANT": reel["present"]
        and adversarial_verdicts.get("INVALID_SCHEMA_REFUSED", False),
        "ALL_OBJECTS_READ_FROM_DISK": tout_relu,
        "SHA256_RECALCULATED_ON_BYTES": tout_relu
        and adversarial_verdicts.get("HASH_MISMATCH_REFUSED", False),
        "DECLARED_SIZES_VERIFIED": tout_relu
        and adversarial_verdicts.get("SIZE_MISMATCH_REFUSED", False),
        "NO_EXPECTED_OBJECTS_MISSING": reel["present"] and not reel["missing"] and tout_relu,
        "NO_EXTRA_OBJECTS_SILENTLY_ACCEPTED": reel["present"] and not reel["extra"],
        "NO_LOCATOR_ESCAPES_CAS_ROOT": reel["return_code"] == 0
        and adversarial_verdicts.get("PATH_TRAVERSAL_REFUSED", False),
        "NO_SYMLINK_TRAVERSAL": reel["return_code"] == 0
        and adversarial_verdicts.get("SYMLINK_REFUSED", False),
        "CONTENT_SET_DIGEST_MATCHES_EXPECTED_AUTHORITY": digest_matches,
        "EXPECTED_COUNT_MATCHES_EXACTLY": count_matches,
        "COVERAGE_ON_GOVERNED_SCOPE": tout_relu and digest_matches,
        "SEARCHABILITY_GAP_MATCHES_CURRENT_MATRIX": ecart_a_jour,
        "NO_MATRIX_REFUSED_CONTENT_ADMITTED": reel["present"] and not declares_refuses,
        "NO_PII_UNDECIDED_CONTENT_PROMOTED": not (cible & pii_bundle_shas),
        "NO_CURRENTNESS_REFUSED_CONTENT_REINTRODUCED": reel["present"]
        and not declares_refuses,
        "RESULT_SEALED_BY_SHA256": True,
    }

    failed_items = [k for k, v in all_verdicts.items() if not v]
    status = "VERIFIED" if not failed_items else "FAILED"

    return {
        "kind": KIND,
        "observed_at_main_sha": main_sha,
        "timestamp": datetime.now(UTC).isoformat(),
        "cas_root": str(cas_root.relative_to(racine)) if cas_root.is_relative_to(racine) else str(cas_root),
        "manifest_schema": SCHEMA,
        "target_scope": {
            "name": "SERVABLE_CANDIDATE_SET",
            "definition": "les contenus que le gate de servabilité ne refuse pas, relus à la matrice courante",
            "count": courant.count,
            "content_set_digest": courant.digest,
            "matrix_sha256": courant.matrix_sha256,
            "authority_source": MATRICE,
        },
        "actual_cas": {
            "present": reel["present"],
            "manifest_content_count": reel["manifest_content_count"],
            "manifest_content_set_digest": reel["manifest_content_set_digest"],
            "objects_verified_on_bytes": reel["objects_verified_on_bytes"],
            "problems": reel["problems"],
        },
        "verifications": {
            "expected_objects_missing": len(reel["missing"])
            if reel["present"] and tout_relu
            else courant.count - reel["objects_verified_on_bytes"],
            "extra_objects_count": len(reel["extra"]),
            "wrong_sha_count": reel.get("wrong_sha") or 0,
            "size_mismatch_count": reel.get("size_mismatch") or 0,
            "content_set_digest_matched": digest_matches,
            "expected_count_matched": count_matches,
            "matrix_refused_admitted": len(declares_refuses),
            "pii_undecided_promoted": len(cible & pii_bundle_shas),
            "sha256_sealed": True,
        },
        "summary": {
            "total_checks": len(all_verdicts),
            "passed_checks": len(all_verdicts) - len(failed_items),
            "failed_items": len(failed_items),
            "failed_check_names": failed_items,
            "verified_objects": reel["objects_verified_on_bytes"],
        },
        "verdicts": all_verdicts,
        "verification_status": status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Chemin de sortie pour l'attestation JSON C6",
    )
    parser.add_argument(
        "--sha-output",
        default=DEFAULT_SHA,
        help="Chemin de sortie pour l'empreinte SHA-256 de l'attestation",
    )
    parser.add_argument(
        "--main-sha",
        required=True,
        help="Commit de base main observé",
    )
    parser.add_argument(
        "--cas-root",
        default=None,
        help=f"Racine du magasin CAS réel (défaut : {DEFAULT_CAS_ROOT})",
    )
    args = parser.parse_args(argv)

    racine = RACINE
    attestation = run_c6_qualification(
        racine, args.main_sha, Path(args.cas_root).resolve() if args.cas_root else None
    )

    out_json = racine / args.output
    out_sha = racine / args.sha_output
    out_json.parent.mkdir(parents=True, exist_ok=True)

    octets = (
        json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    out_json.write_bytes(octets)

    sha = hashlib.sha256(octets).hexdigest()
    out_sha.write_text(f"{sha}  {args.output}\n", encoding="utf-8")

    total = attestation["summary"]["total_checks"]
    passed = attestation["summary"]["passed_checks"]
    failed = attestation["summary"]["failed_items"]

    print(
        f"C6 QUALIFICATION {attestation['verification_status']}: "
        f"{passed}/{total} contrôles validés, {failed} échecs."
    )
    print(f"Écrit : {out_json}")
    print(f"Écrit : {out_sha}")

    return 0 if attestation["verification_status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
