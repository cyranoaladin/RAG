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
    try:
        import pypdf

        return str(pypdf.__version__)
    except Exception:  # noqa: BLE001
        return "INDISPONIBLE"


def _sha_page_policy() -> str:
    try:
        import nexus_pdf_page_policy as politique

        return str(getattr(politique, "POLICY_SHA256", getattr(politique, "POLICY_ID", "")))
    except Exception:  # noqa: BLE001
        return "INDISPONIBLE"


try:
    from nexus_pdf_page_policy import POLICY_ID as _POLICY_ID
except Exception:  # noqa: BLE001
    _POLICY_ID = "INDISPONIBLE"


# --- Identité de la campagne ------------------------------------------
# Une preuve qui ne dit pas sous quoi elle a été produite n'est pas rejouable.
import subprocess as _sp  # noqa: E402

_PEDAGO = Path(os.environ["NEXUS_PEDAGO_ROOT"])
_RACINE = _PEDAGO.parents[1]


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
    "EXTRACTOR_VERSION": _version_pypdf(),
    "PAGE_POLICY_ID": _POLICY_ID,
    "TEXT_NORMALIZATION_VERSION": TEXT_NORMALISATION_ID,
    "OCR_RUNTIME_IDENTITY": _OCR_RUNTIME.identity_sha256(),
    "CHUNKER_ID": "nexus-drive-slice",
    "POSTGRES_IMAGE_DIGEST": os.environ.get("NEXUS_STAGING_PG_DIGEST", "NON_DECLARE"),
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
errors: list[dict[str, str]] = []
unclassifiable: list[dict[str, str]] = []
pii_detectes: list[dict] = []
quarantaine: list[str] = []
staged: list[str] = []


def _write_report(done: int) -> None:
    REPORT.write_text(
        json.dumps(
            {
                "DRIVE_ELIGIBLE_PDF": len(eligible),
                "DRIVE_DISTINCT_ARTIFACTS": len(artifacts),
                "DRIVE_DUPLICATE_BY_CONTENT": len(eligible) - len(artifacts),
                "DRIVE_INGESTED": len(staged),
                "DRIVE_UNCLASSIFIABLE_BY_SOURCE": len(unclassifiable),
                "DRIVE_ERRORS": len(errors),
                "DRIVE_UNACCOUNTED": (
                    len(artifacts) - len(staged) - len(errors) - len(unclassifiable)
                ),
                "MANIFEST_SHA256": manifest.manifest_sha256,
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
                "totals": dict(totals),
                "errors": errors,
                "unclassifiable": unclassifiable,
                "PII_SCANNED_PDF": totals["pii_scanned"],
                "PII_CLEARED": totals["pii_cleared"],
                "PII_DETECTED": totals["pii_detected"],
                "PII_ERRORS": len(errors),
                "PII_UNACCOUNTED": (
                    len(artifacts)
                    - totals["pii_scanned"]
                    - len(errors)
                    - len(unclassifiable)
                ),
                "QUARANTINED_PII_ARTIFACTS": len(quarantaine),
                "pii_detectes": pii_detectes,
                "progress": f"{done}/{len(artifacts)}",
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
    store = PostgresStagingStore(connection)
    store.create_schema()

    for index, artifact in enumerate(artifacts, start=1):
        first = artifact["occurrences"][0]
        hints = tuple(first.split("/")[:-1])
        try:
            try:
                placement = classify_from_hints(hints)
            except DriveClassificationError as refus:
                # Le garde a raison : la source empile un statut sur une
                # nature et dit ainsi qu'elle ne tranche pas. On ne tranche
                # pas non plus — on nomme l'objet et on l'envoie en
                # disposition.
                unclassifiable.append(
                    {
                        "artifact_id": artifact["artifact_id"],
                        "drive_file_id": by_path[first]["drive_file_id"],
                        "relative_path": first,
                        "refus": str(refus),
                    }
                )
                continue

            # Un artefact entre ENTIER ou pas du tout. Sans point de reprise,
            # un échec au découpage laisserait derrière lui sa ligne
            # d'artefact et ses provenances : en aval, un document sans
            # chunks — ou pire, avec un jeu partiel — se lit comme ingéré.
            # Les compteurs suivent la TRANSACTION, pas la tentative : un
            # artefact annulé par le point de reprise n'a rien écrit, et un
            # rapport qui l'annoncerait « nouveau » contredirait la base
            # qu'il prétend décrire.
            # UNE extraction, AVANT toute écriture. Son empreinte est
            # l'identité commune du scan PII, du découpage et de l'indexation :
            # extraire deux fois laisserait un document déclaré propre sur un
            # texte et indexé sur un autre, sans que rien ne puisse le montrer.
            proven = (DESTINATION / first).read_bytes()
            pages_canoniques = extract_pdf_pages(proven)
            texte_canonique = "\n".join(page.text for page in pages_canoniques)
            empreinte_texte = hashlib.sha256(
                texte_canonique.encode("utf-8")
            ).hexdigest()

            local: collections.Counter[str] = collections.Counter()
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

              constats = [
                  motif
                  for page in pages_canoniques
                  for motif in scan_text_for_pii(
                      page.text, _PII_PATTERNS, page_number=page.number
                  )
              ]
              if constats:
                  pii_detectes.append(
                      {
                          "artifact_id": artifact["artifact_id"],
                          "drive_file_id": by_path[first]["drive_file_id"],
                          "relative_path": first,
                          "content_sha256": artifact["artifact_id"],
                          "canonical_text_sha256": empreinte_texte,
                          "pattern_ids": sorted({m.pattern_id for m in constats}),
                          "match_count": len(constats),
                          "pages": sorted({m.page_number for m in constats}),
                      }
                  )
              local["pii_scanned"] += 1
              local["pii_detected"] += int(bool(constats))
              local["pii_cleared"] += int(not constats)

              # FAIL-CLOSED sur le SERVING, pas sur la campagne. Un document
              # détecté n'est ni découpé ni indexé — mais l'arrêter tout de
              # suite imposerait une revue humaine par document, là où une
              # seule campagne rend l'inventaire complet des détections.
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
            staged.append(artifact["artifact_id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "drive_file_id": by_path[first]["drive_file_id"],
                    "relative_path": first,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        if index % 100 == 0 or index == len(artifacts):
            connection.commit()
            _write_report(index)
            print(
                f"{index}/{len(artifacts)} stagés={len(staged)} "
                f"inclassables={len(unclassifiable)} erreurs={len(errors)} "
                f"chunks={totals['new_chunks']} t={time.monotonic() - started:.0f}s",
                flush=True,
            )
    connection.commit()

_write_report(len(artifacts))
print("=== FINAL ===", flush=True)
for key in (
    "DRIVE_ELIGIBLE_PDF",
    "DRIVE_DISTINCT_ARTIFACTS",
    "DRIVE_DUPLICATE_BY_CONTENT",
    "DRIVE_INGESTED",
    "DRIVE_UNCLASSIFIABLE_BY_SOURCE",
    "DRIVE_ERRORS",
    "DRIVE_UNACCOUNTED",
    "PII_SCANNED_PDF",
    "PII_CLEARED",
    "PII_DETECTED",
    "PII_ERRORS",
    "PII_UNACCOUNTED",
    "QUARANTINED_PII_ARTIFACTS",
):
    print(f"{key}={json.loads(REPORT.read_text('utf-8'))[key]}", flush=True)
