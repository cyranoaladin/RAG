"""Reprise du staging sur le corpus DÉJÀ acquis et rehaché.

L'acquisition a abouti : 2473 PDF matérialisés, 1,73 Go, manifeste scellé.
C'est l'étape de staging qui est tombée — sur MON défaut (une DSN passée
là où le magasin attend une connexion ouverte). Re-télécharger 1,7 Go pour
corriger une faute d'orchestration serait du gâchis, et surtout ce serait
moins probant : `materialise` rehache ce qu'il vient de TÉLÉCHARGER, alors
que l'arbre sur disque porte les octets que l'acquisition a ÉCRITS PUIS
rehachés. On lit donc le disque — ce que la tranche exige déjà : « le
découpage lit les octets écrits par l'acquisition, pas ceux téléchargés ».

La reprise ne se croit pas sur parole : elle recalcule le manifeste scellé
sur l'arbre et le confronte à l'empreinte qu'a publiée l'acquisition. Si
un seul octet a bougé depuis, on s'arrête.

Rien de ce qui garde n'est réécrit. `classify_from_hints` refuse toujours
un chemin ambigu ; son refus n'est plus compté comme une panne mais
comme ce qu'il est — un objet que la SOURCE elle-même déclare inclassable,
et qui part en disposition explicite, nommé par son `drive_file_id`.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ["NEXUS_PEDAGO_ROOT"])


# --- Les autorités obligatoires, AVANT tout import qui en dépend --------
# Un contrôle placé après ces imports rendrait une trace Python là où le gate
# doit nommer l'autorité manquante : le défaut serait identique, le message
# inutilisable.
_PEDAGO_PRELUDE = Path(os.environ["NEXUS_PEDAGO_ROOT"])
_RACINE = _PEDAGO_PRELUDE.parents[1]
_PEDAGO = _PEDAGO_PRELUDE

_ENGINE = _RACINE / "services" / "rag-engine"

_AUTORITES: tuple[tuple[str, Path, bool, str], ...] = (
    # nom, chemin, obligatoire, portée d'effet
    ("SCHEMA_VERSION", _PEDAGO / "rag_pedago" / "governance" / "drive_staging_pg.py",
     True, "stockage"),
    ("EXTRACTOR_CONFIG_SHA256", _PEDAGO / "rag_pedago" / "governance" / "drive_extraction.py",
     True, "texte,chunk"),
    ("CHUNKER_CONFIG_SHA256", _PEDAGO / "rag_pedago" / "governance" / "drive_slice.py",
     True, "chunk,classification"),
    ("TAXONOMY_AUTHORITY_SHA256", _PEDAGO / "rag_pedago" / "governance" / "drive_slice.py",
     True, "classification,placement"),
    ("PII_SCANNER_SHA256", _PEDAGO / "rag_pedago" / "imports" / "pii_scanner.py",
     True, "servabilite"),
    ("PII_POLICY_SHA256", _PEDAGO / "configs" / "pii_gate_policy.yml",
     True, "servabilite"),
    ("DOCUMENT_TYPE_MAPPING_SHA256",
     _ENGINE / "configs" / "mappings" / "eduscol_multilevel_document_types.yml",
     True, "taxonomie,placement,release"),
    ("LEVEL_MAPPING_SHA256",
     _ENGINE / "configs" / "mappings" / "eduscol_multilevel_levels.yml",
     True, "taxonomie,placement"),
    ("SUBJECT_MAPPING_SHA256",
     _ENGINE / "configs" / "mappings" / "eduscol_multilevel_subjects.yml",
     True, "taxonomie,placement"),
    ("RIGHTS_POLICY_SHA256", _PEDAGO / "configs" / "rights_evidence_registry.yml",
     True, "servabilite"),
    ("PYTHON_LOCK_SHA256", _PEDAGO / "requirements.lock", True, "runtime"),
)

_manquantes = [
    (nom, chemin) for nom, chemin, requis, _ in _AUTORITES
    if requis and not chemin.is_file()
]
if _manquantes:
    raise SystemExit(
        "CAMPAGNE_REFUSEE : "
        + f"{len(_manquantes)} autorité(s) obligatoire(s) absente(s) — "
        + ", ".join(f"{nom} ({chemin})" for nom, chemin in _manquantes)
        + ". Une campagne qui les remplacerait par un sentinelle produirait "
        "une preuve dont la lignée ne dit pas ce qui l'a décidée."
    )




import psycopg  # noqa: E402
from nexus_pdf_ocr import describe_runtime  # noqa: E402

from rag_pedago.governance.drive_extraction import (  # noqa: E402
    TEXT_NORMALISATION_ID,
    extraction_gouvernee,
)

# La couche textuelle reste la voie ordinaire ; l'océrisation n'intervient
# que lorsqu'elle est absente, et le runtime est RELEVÉ, jamais supposé.
_OCR_RUNTIME = describe_runtime()
extract_pdf_pages = extraction_gouvernee(_OCR_RUNTIME)

# Le scanner PII faisant autorité, sur le MÊME texte que le découpage. Deux
# extractions donneraient deux vérités : un document pourrait être déclaré
# propre sur un texte et indexé sur un autre.
from rag_pedago.imports.pii_scanner import (  # noqa: E402
    load_patterns_from_config,
    scan_text_for_pii,
)

_PII_PATTERNS = load_patterns_from_config(
    Path(os.environ["NEXUS_PEDAGO_ROOT"]) / "configs" / "pii_gate_policy.yml"
)
from rag_pedago.governance.drive_slice import (  # noqa: E402
    SOURCE_KIND,
    DriveClassificationError,
    StagedArtifact,
    StagedProvenance,
    classify_from_hints,
    make_chunks,
)
from rag_pedago.governance.drive_staging_pg import (  # noqa: E402
    PostgresStagingStore,
    staging_dsn,
)
from rag_pedago.governance.sealed_corpus import generate_sealed_manifest  # noqa: E402

REPORT = Path(os.environ["NEXUS_DRIVE_INGESTION_REPORT"])
DESTINATION = Path(os.environ["NEXUS_DRIVE_DESTINATION"])
INVENTORY = Path(os.environ["NEXUS_DRIVE_INVENTORY"])
EXPECTED_MANIFEST = os.environ["NEXUS_DRIVE_MANIFEST_SHA256"]

started = time.monotonic()

# --- L'arbre acquis est-il TOUJOURS celui que l'acquisition a scellé ? ---
manifest = generate_sealed_manifest(DESTINATION)
if manifest.manifest_sha256 != EXPECTED_MANIFEST:
    raise SystemExit(
        f"MANIFEST_DRIFT attendu={EXPECTED_MANIFEST} "
        f"observé={manifest.manifest_sha256} — l'arbre a bougé depuis "
        "l'acquisition ; reprendre le staging dessus attesterait des octets "
        "que personne n'a prouvés"
    )
def _version_pypdf() -> str:
    import pypdf

    return str(pypdf.__version__)


def _politique_de_page() -> tuple[str, str, str]:
    """Identité, empreinte et version canonique de pypdf, ou refus.

    La politique décide de ce qu'est une page structurellement vide : elle
    intervient donc dans la preuve d'extraction ET dans celle du scan PII.
    Un `INDISPONIBLE` la ferait entrer dans l'identité sans rien y apporter.
    """
    try:
        import nexus_pdf_page_policy as politique
    except ImportError as exc:  # noqa: BLE001
        raise SystemExit(
            "CAMPAGNE_REFUSEE : la politique de page est introuvable "
            f"({exc}) — elle décide de ce qu'est une page vide, et sans elle "
            "l'extraction comme le scan PII ne sont pas qualifiés."
        ) from exc
    module = Path(politique.__file__)
    empreinte = hashlib.sha256(module.read_bytes()).hexdigest()
    identifiant = str(getattr(politique, "POLICY_ID", ""))
    canonique = str(getattr(politique, "CANONICAL_PYPDF_VERSION", ""))
    if not identifiant or not canonique:
        raise SystemExit(
            "CAMPAGNE_REFUSEE : la politique de page ne déclare pas son "
            "identité ou sa version canonique de pypdf."
        )
    return identifiant, empreinte, canonique


_POLICY_ID, _POLICY_SHA256, _PYPDF_CANONIQUE = _politique_de_page()
_PYPDF_MESURE = _version_pypdf()
if _PYPDF_MESURE != _PYPDF_CANONIQUE:
    raise SystemExit(
        f"CAMPAGNE_REFUSEE : pypdf {_PYPDF_MESURE} n'est pas le runtime "
        f"canonique déclaré par la politique de page ({_PYPDF_CANONIQUE}) — "
        "mesuré sur les 320 PDF de production, deux versions rendent un texte "
        "différent sur 319 d'entre eux."
    )


def _digest_postgres() -> str:
    """Digest OCI de l'image, EXIGÉ et vérifié dans sa forme."""
    declare = os.environ.get("NEXUS_STAGING_PG_DIGEST", "")
    motif = re.fullmatch(r"(?:[^@]+@)?sha256:([0-9a-f]{64})", declare)
    if motif is None:
        raise SystemExit(
            "CAMPAGNE_REFUSEE : NEXUS_STAGING_PG_DIGEST absent ou mal formé "
            f"({declare!r}) — une campagne finale ne peut pas taire l'image "
            "qui a stocké ses résultats."
        )
    return declare


def _postgres_observe(connection: object) -> dict:
    """Ce que le serveur et Docker DISENT réellement, pas ce qu'on annonce."""
    with connection.cursor() as curseur:  # type: ignore[attr-defined]
        curseur.execute("show server_version")
        version = str(curseur.fetchone()[0])
        curseur.execute(
            "select extversion from pg_extension where extname = 'vector'"
        )
        ligne = curseur.fetchone()
        pgvector = str(ligne[0]) if ligne else "ABSENTE"
    conteneur = os.environ.get("NEXUS_STAGING_PG_CONTAINER", "")
    # Le conteneur ne porte pas `RepoDigests` : c'est son IMAGE qui le porte.
    # On remonte donc du conteneur à l'image qu'il exécute réellement, puis on
    # lit le digest de cette image — jamais celui d'un tag, qui peut avoir
    # bougé depuis.
    image = (
        _sortie(["docker", "inspect", conteneur, "--format", "{{.Image}}"])
        if conteneur
        else ""
    )
    depot = (
        _sortie(["docker", "inspect", image, "--format", "{{index .RepoDigests 0}}"])
        if image
        else ""
    )
    attendu = os.environ.get("NEXUS_STAGING_PG_DIGEST", "")
    return {
        "POSTGRES_SERVER_VERSION": version,
        "PGVECTOR_EXTENSION_VERSION": pgvector,
        "POSTGRES_OBSERVED_REPO_DIGEST": depot or "NON_OBSERVABLE",
        "POSTGRES_OBSERVED_IMAGE_ID": image or "NON_OBSERVABLE",
        "POSTGRES_IMAGE_MATCH": bool(depot) and depot == attendu,
    }


# --- Identité de la campagne # --- Identité de la campagne ------------------------------------------
# Une preuve qui ne dit pas sous quoi elle a été produite n'est pas rejouable.
import re  # noqa: E402
import subprocess as _sp  # noqa: E402


def _sha_fichier(chemin: Path) -> str:
    """Empreinte d'une autorité, ou son absence NOMMÉE.

    Rendre une chaîne vide pour un fichier manquant ferait entrer deux runs
    différents sous la même identité."""
    if not chemin.is_file():
        return f"ABSENT:{chemin.name}"
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _sortie(commande: list[str]) -> str:
    return _sp.run(
        commande, capture_output=True, text=True, check=False
    ).stdout.strip()


#: Chaque input du run, classifié. `required` dit si son absence est fatale :
#: le sentinelle `ABSENT:` empêche deux configurations de partager un
#: RUN_ID, mais il n'a de sens que pour une dépendance VRAIMENT optionnelle.
#: Une autorité obligatoire manquante doit arrêter la campagne AVANT toute
#: écriture, pas la laisser produire une preuve incomplète.
_CAMPAGNE = {
    # -- ce qui décrit le périmètre --
    "INVENTORY_SHA256": _sha_fichier(Path(os.environ["NEXUS_DRIVE_INVENTORY"])),
    "MANIFEST_SHA256_ATTENDU": os.environ["NEXUS_DRIVE_MANIFEST_SHA256"],
    # -- ce qui décrit le code exécuté --
    "CODE_COMMIT": _sortie(["git", "-C", str(_PEDAGO), "rev-parse", "HEAD"]),
    "CODE_DIRTY": bool(_sortie(["git", "-C", str(_PEDAGO), "status", "--porcelain"])),
    "RUNNER_SHA256": _sha_fichier(Path(__file__).resolve()),
    # -- les autorités classifiées --
    **{nom: _sha_fichier(chemin) for nom, chemin, _, _ in _AUTORITES},
    # -- identités non fichiers --
    "EXTRACTOR_ID": "pypdf",
    "EXTRACTOR_VERSION": _PYPDF_MESURE,
    "PAGE_POLICY_ID": _POLICY_ID,
    "PAGE_POLICY_SHA256": _POLICY_SHA256,
    "CANONICAL_PYPDF_VERSION": _PYPDF_CANONIQUE,
    "TEXT_NORMALIZATION_VERSION": TEXT_NORMALISATION_ID,
    "OCR_RUNTIME_IDENTITY": _OCR_RUNTIME.identity_sha256(),
    "CHUNKER_ID": "nexus-drive-slice",
    "POSTGRES_IMAGE_DIGEST": _digest_postgres(),
}

if _CAMPAGNE["CODE_DIRTY"]:
    raise SystemExit(
        "CAMPAGNE_REFUSEE : l'arbre de travail porte des modifications non "
        "commitées. Une campagne finale ne peut pas être liée à un commit qui "
        "ne décrit pas le code réellement exécuté."
    )

_CAMPAGNE["FULL_DRIVE_RUN_ID"] = hashlib.sha256(
    "\n".join(f"{k}={_CAMPAGNE[k]}" for k in sorted(_CAMPAGNE)).encode()
).hexdigest()
for _cle in sorted(_CAMPAGNE):
    print(f"{_cle}={_CAMPAGNE[_cle]}", flush=True)
print(
    f"MANIFEST_REVERIFIED={manifest.manifest_sha256} "
    f"OBJETS={manifest.object_count} t={time.monotonic() - started:.0f}s",
    flush=True,
)

# --- L'inventaire de la campagne, tel quel : on ne réénumère pas ---
occurrences = [json.loads(line) for line in INVENTORY.read_text("utf-8").splitlines() if line.strip()]
eligible = sorted(
    (o for o in occurrences if o["servable"] and o["mime_type"] == "application/pdf"),
    key=lambda o: o["relative_path"],
)
by_path = {o["relative_path"]: o for o in eligible}
print(f"INVENTAIRE={len(occurrences)} ELIGIBLE={len(eligible)}", flush=True)

# --- Dédup par CONTENU, sur les octets prouvés du disque ---
by_digest: dict[str, list[dict]] = {}
for occurrence in eligible:
    payload = (DESTINATION / occurrence["relative_path"]).read_bytes()
    if len(payload) != occurrence["size"]:
        raise SystemExit(
            f"{occurrence['relative_path']!r} pèse {len(payload)} octets sur "
            f"disque contre {occurrence['size']} annoncés à l'inventaire"
        )
    by_digest.setdefault(hashlib.sha256(payload).hexdigest(), []).append(occurrence)

artifacts = [
    {
        "artifact_id": digest,
        "occurrences": sorted(o["relative_path"] for o in by_digest[digest]),
        "size": by_digest[digest][0]["size"],
        "mime_type": by_digest[digest][0]["mime_type"],
        "modified_time": min(o["modified_time"] for o in by_digest[digest]),
    }
    for digest in sorted(by_digest)
]
print(
    f"OCCURRENCES={len(eligible)} ARTEFACTS_DISTINCTS={len(artifacts)} "
    f"DUPLICATE_BY_CONTENT={len(eligible) - len(artifacts)}",
    flush=True,
)

totals: collections.Counter[str] = collections.Counter()
# Catégories SÉPARÉES : une panne d'extraction n'est pas une panne du
# scanner PII, et les confondre rendrait « PII_ERRORS » faux.
erreurs_extraction: list[dict[str, str]] = []
erreurs_pii: list[dict[str, str]] = []
erreurs_staging: list[dict[str, str]] = []
non_assessables: list[str] = []


def _incident(artifact: dict, premier: str, index: dict, exc: Exception) -> dict:
    return {
        "artifact_id": artifact["artifact_id"],
        "drive_file_id": index[premier]["drive_file_id"],
        "relative_path": premier,
        "error": f"{type(exc).__name__}: {exc}",
    }

unclassifiable: list[dict[str, str]] = []
pii_detectes: list[dict] = []
quarantaine: list[str] = []
staged: list[str] = []


def _write_report(done: int) -> None:
    distincts = len(artifacts)
    erreurs = (
        len(erreurs_extraction) + len(erreurs_pii) + len(erreurs_staging)
    )
    # Partition EXACTE des artefacts distincts. La quarantaine PII y figure :
    # l'omettre faisait du premier document détecté un objet « inexpliqué ».
    unaccounted = (
        distincts
        - len(staged)
        - len(quarantaine)
        - len(unclassifiable)
        - erreurs
    )
    pii_attempted = totals["pii_attempted"]
    REPORT.write_text(
        json.dumps(
            {
                "campagne": _CAMPAGNE,
                "autorites_du_run": [
                    {
                        "nom": nom,
                        "chemin": str(chemin.relative_to(_RACINE)),
                        "sha256": _CAMPAGNE[nom],
                        "required": requis,
                        "effect_scope": portee,
                    }
                    for nom, chemin, requis, portee in _AUTORITES
                ],
                # -- périmètre --
                "DRIVE_ELIGIBLE_PDF_OCCURRENCES": len(eligible),
                "DRIVE_PDF_DISTINCT_ARTIFACTS": distincts,
                "DRIVE_DUPLICATE_BY_CONTENT": len(eligible) - distincts,
                "MANIFEST_SHA256": manifest.manifest_sha256,
                # -- partition du traitement --
                "DRIVE_PDF_CLEARED_AND_STAGED": len(staged),
                "DRIVE_PDF_QUARANTINED_PII": len(quarantaine),
                "DRIVE_PDF_UNCLASSIFIABLE": len(unclassifiable),
                "DRIVE_PDF_PROCESSING_ERRORS": erreurs,
                "DRIVE_PDF_UNACCOUNTED": unaccounted,
                # -- erreurs, par cause --
                "EXTRACTION_ERRORS": len(erreurs_extraction),
                "PII_SCAN_ERRORS": len(erreurs_pii),
                "STAGING_ERRORS": len(erreurs_staging),
                # -- comptabilité PII --
                "PII_ATTEMPTED": pii_attempted,
                "PII_CLEARED": totals["pii_cleared"],
                "PII_DETECTED": totals["pii_detected"],
                "PII_NOT_ASSESSABLE": len(non_assessables),
                "PII_UNACCOUNTED": (
                    distincts - pii_attempted - len(non_assessables)
                ),
                "QUARANTINED_PII_ARTIFACTS": len(quarantaine),
                # -- ledgers --
                "totals": dict(totals),
                "erreurs_extraction": erreurs_extraction,
                "erreurs_pii": erreurs_pii,
                "erreurs_staging": erreurs_staging,
                "unclassifiable": unclassifiable,
                "pii_detectes": pii_detectes,
                "progress": f"{done}/{distincts}",
                "elapsed_s": round(time.monotonic() - started, 1),
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


with psycopg.connect(staging_dsn()) as connection:
    # Une variable d'environnement n'est pas une preuve du conteneur qui a
    # réellement tourné. On confronte le digest annoncé à l'image observée,
    # et on enregistre ce que le serveur DIT de lui-même.
    _observe = _postgres_observe(connection)
    if not _observe["POSTGRES_IMAGE_MATCH"]:
        raise SystemExit(
            "CAMPAGNE_REFUSEE : le digest annoncé "
            f"({_CAMPAGNE['POSTGRES_IMAGE_DIGEST']}) ne correspond à aucune "
            f"image observée ({_observe['POSTGRES_OBSERVED_REPO_DIGEST']})"
        )
    _CAMPAGNE.update(_observe)
    for _cle in sorted(_observe):
        print(f"{_cle}={_observe[_cle]}", flush=True)

    store = PostgresStagingStore(connection)
    store.create_schema()

    for index, artifact in enumerate(artifacts, start=1):
        first = artifact["occurrences"][0]
        hints = tuple(first.split("/")[:-1])

        # 1. UNE extraction, avant tout le reste. Son empreinte est l'identité
        #    commune du scan PII, du découpage et de l'indexation.
        try:
            proven = (DESTINATION / first).read_bytes()
            pages_canoniques = extract_pdf_pages(proven)
            texte_canonique = "\n".join(page.text for page in pages_canoniques)
            empreinte_texte = hashlib.sha256(
                texte_canonique.encode("utf-8")
            ).hexdigest()
        except Exception as exc:  # noqa: BLE001
            # Sans texte, la fraîcheur PII n'est pas ASSESSABLE — elle n'est
            # pas « claire ». Fabriquer un PII_CLEARED ici serait un mensonge.
            erreurs_extraction.append(_incident(artifact, first, by_path, exc))
            non_assessables.append(artifact["artifact_id"])
            continue

        # 2. PII AVANT classification : un document qu'on ne sait pas classer
        #    n'est pas un document sans données personnelles.
        try:
            constats = [
                motif
                for page in pages_canoniques
                for motif in scan_text_for_pii(
                    page.text, _PII_PATTERNS, page_number=page.number
                )
            ]
        except Exception as exc:  # noqa: BLE001
            erreurs_pii.append(_incident(artifact, first, by_path, exc))
            non_assessables.append(artifact["artifact_id"])
            continue

        totals["pii_attempted"] += 1
        if constats:
            totals["pii_detected"] += 1
            # Ledger SANITISÉ : jamais le texte trouvé ni son contexte.
            pii_detectes.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "content_sha256": artifact["artifact_id"],
                    "drive_file_id": by_path[first]["drive_file_id"],
                    "canonical_text_sha256": empreinte_texte,
                    "pattern_ids": sorted({m.pattern_id for m in constats}),
                    "match_count": len(constats),
                    "pages": sorted({m.page_number for m in constats}),
                }
            )
        else:
            totals["pii_cleared"] += 1

        # 3. Classification.
        try:
            placement = classify_from_hints(hints)
        except DriveClassificationError as refus:
            unclassifiable.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "drive_file_id": by_path[first]["drive_file_id"],
                    "relative_path": first,
                    "refus": str(refus),
                    "canonical_text_sha256": empreinte_texte,
                    "pii_detected": bool(constats),
                }
            )
            continue

        # 4. Persistance. Un artefact entre entier ou pas du tout.
        local: collections.Counter[str] = collections.Counter()
        try:
            with connection.transaction():
                created = store.upsert_artifact(
                    StagedArtifact(
                        artifact_id=artifact["artifact_id"],
                        content_sha256=artifact["artifact_id"],
                        source_kind=SOURCE_KIND,
                        mime_type=artifact["mime_type"],
                        size_bytes=artifact["size"],
                        modified_time=artifact["modified_time"],
                        placement=placement,
                        canonical_text_sha256=empreinte_texte,
                    )
                )
                local["new_artifacts"] += int(created)
                local["duplicate_artifacts"] += int(not created)

                for relative_path in artifact["occurrences"]:
                    occurrence = by_path[relative_path]
                    fresh = store.upsert_provenance(
                        StagedProvenance(
                            artifact_id=artifact["artifact_id"],
                            source_id=occurrence["source_id"],
                            drive_file_id=occurrence["drive_file_id"],
                            drive_path=occurrence["source_id"].split(":", 1)[1],
                            relative_path=occurrence["relative_path"],
                            shortcut_id=occurrence["shortcut_id"],
                        )
                    )
                    local["new_provenances"] += int(fresh)
                    local["duplicate_provenances"] += int(not fresh)

                # FAIL-CLOSED sur le SERVING : un document détecté est
                # persisté comme artefact, avec sa provenance et l'empreinte
                # de son texte, mais SANS aucun chunk. La campagne continue —
                # l'arrêter au premier imposerait une revue humaine par
                # document là où une seule rend l'inventaire complet.
                if constats:
                    quarantaine.append(artifact["artifact_id"])
                else:
                    for chunk in make_chunks(
                        artifact["artifact_id"], pages_canoniques
                    ):
                        fresh_chunk = store.upsert_chunk(chunk)
                        local["new_chunks"] += int(fresh_chunk)
                        local["duplicate_chunks"] += int(not fresh_chunk)
            totals.update(local)
            if not constats:
                staged.append(artifact["artifact_id"])
        except Exception as exc:  # noqa: BLE001
            erreurs_staging.append(_incident(artifact, first, by_path, exc))
            continue

        if index % 100 == 0 or index == len(artifacts):
            connection.commit()
            _write_report(index)
            print(
                f"{index}/{len(artifacts)} servables={len(staged)} "
                f"quarantaine={len(quarantaine)} "
                f"inclassables={len(unclassifiable)} "
                f"erreurs={len(erreurs_extraction) + len(erreurs_pii) + len(erreurs_staging)} "
                f"chunks={totals['new_chunks']} t={time.monotonic() - started:.0f}s",
                flush=True,
            )
    connection.commit()

_write_report(len(artifacts))
print("=== FINAL ===", flush=True)
_rendu = json.loads(REPORT.read_text("utf-8"))
for key in (
    "DRIVE_ELIGIBLE_PDF_OCCURRENCES",
    "DRIVE_PDF_DISTINCT_ARTIFACTS",
    "DRIVE_PDF_CLEARED_AND_STAGED",
    "DRIVE_PDF_QUARANTINED_PII",
    "DRIVE_PDF_UNCLASSIFIABLE",
    "DRIVE_PDF_PROCESSING_ERRORS",
    "DRIVE_PDF_UNACCOUNTED",
    "EXTRACTION_ERRORS",
    "PII_SCAN_ERRORS",
    "STAGING_ERRORS",
    "PII_ATTEMPTED",
    "PII_CLEARED",
    "PII_DETECTED",
    "PII_NOT_ASSESSABLE",
    "PII_UNACCOUNTED",
):
    print(f"{key}={_rendu[key]}", flush=True)
