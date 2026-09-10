#!/usr/bin/env python3
"""Prépare les paquets de revue PII, hors dépôt, figés par empreinte (ADR-0047 § 2).

Un reviewer humain statue sur ce que le scanner a trouvé, pas sur un résumé. Le
paquet d'un contenu est donc généré depuis les octets exacts du PDF (rehachés),
sous la politique, le scanner, le foyer de pages et le runtime nommés dans son
manifeste. Il porte chaque correspondance avec sa page, sa longueur, son
contexte et le texte brut, le texte complet des pages concernées, et le PDF
entier — matière brute, donc HORS Git. Son empreinte est celle de son
`manifest.json`, qui épingle chaque fichier : toute modification après décision
l'invalide (`--verifier`).

Le dépôt ne garde que l'INDEX (`NEXUS-PII-REVIEW-INDEX-V1`) : empreintes,
classes, comptes, pages, titres, placements — jamais la matière.

    python scripts/preparer_paquets_revue_pii.py \\
        --pdf-root ~/nexus-pdf-mirror-20260902 \\
        --content-set docs/reports/evidence-index/production_content_set_320_20260902.txt \\
        --placements docs/reports/evidence-index/pii_review_placements_20260902.json \\
        --output-root ~/nexus-pii-review-20260902 \\
        --index docs/reports/evidence-index/pii_review_index_20260902.json \\
        --campaign-id pii-review-2026-09-02-lot-1-2

    python scripts/preparer_paquets_revue_pii.py --verifier \\
        --output-root ~/nexus-pii-review-20260902 \\
        --index docs/reports/evidence-index/pii_review_index_20260902.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

import nexus_pdf_page_policy as page_policy  # noqa: E402
import pypdf  # noqa: E402

from rag_pedago.imports import pii_scanner  # noqa: E402
from rag_pedago.imports.pii_review_projection import (  # noqa: E402
    finding_context,
    finding_identity,
)

BUNDLE_PROTOCOL = "NEXUS-PII-REVIEW-BUNDLE-V1"
INDEX_PROTOCOL = "NEXUS-PII-REVIEW-INDEX-V1"
REPOSITORY_ROOT = SERVICE_ROOT.parents[1]


def nir_checksum_valid(candidate: str) -> bool:
    """Contrôle de clé d'un NIR : clé = 97 − (13 premiers chiffres mod 97).

    Un NIR de Corse (2A/2B) se code 19/18 avant le calcul ; la grille PII ne
    capture que des chiffres, on ne le rencontre pas ici. Ce verdict est une
    PREUVE TECHNIQUE mise à disposition du reviewer (§ 9) ; il ne décide rien.
    """
    digits = "".join(ch for ch in candidate if ch.isdigit())
    if len(digits) != 15:
        return False
    number, key = int(digits[:13]), int(digits[13:])
    return key == 97 - (number % 97)


def _git(*args: str) -> str:
    import subprocess

    return subprocess.check_output(["git", *args], cwd=REPOSITORY_ROOT, text=True).strip()


def producer_identity(*, require_frozen: bool = True) -> dict[str, object]:
    """Ce que le reviewer doit savoir : « CE code, CES autorités » (§ 2).

    Commit et arbre source du dépôt qui produit les paquets, arbre sale refusé
    sur les fichiers qui décident (générateur, scanner, politique, foyer)."""
    import importlib.metadata
    import subprocess

    # `pii_review_projection.py` fournit `finding_identity` et
    # `finding_context` : il DÉCIDE de l'identité et du contexte que les paquets
    # scellent. L'omettre de la surface gelée laissait une modification locale
    # produire des paquets différents sous la même provenance.
    porcelain = subprocess.check_output(
        ["git", "status", "--porcelain", "--",
         "services/rag-pedago/scripts/preparer_paquets_revue_pii.py",
         "services/rag-pedago/rag_pedago/imports/pii_review_projection.py",
         "services/rag-pedago/rag_pedago/imports/pii_scanner.py",
         "services/rag-pedago/configs/pii_gate_policy.yml",
         "packages/pdf-page-policy", "packages/contracts"],
        cwd=REPOSITORY_ROOT, text=True,
    )
    dirty = sorted(line[3:] for line in porcelain.splitlines() if line.strip())
    if dirty and require_frozen:
        raise RuntimeError(f"review bundle producer is not frozen: uncommitted changes in {dirty}")
    return {
        "producer_commit_sha": _git("rev-parse", "HEAD"),
        "producer_tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "generator_path": "services/rag-pedago/scripts/preparer_paquets_revue_pii.py",
        "generator_sha256": _sha256_file(Path(__file__)),
        # Nouveau champ, PROSPECTIF : les 23 paquets déjà revus gardent leur
        # provenance d'origine, qui ne couvrait pas ce module. Le prétendre
        # réécrirait leur histoire au lieu de versionner la règle.
        "projection_path": "services/rag-pedago/rag_pedago/imports/pii_review_projection.py",
        "projection_sha256": _sha256_file(
            REPOSITORY_ROOT
            / "services/rag-pedago/rag_pedago/imports/pii_review_projection.py"
        ),
        "contracts_version": importlib.metadata.version("nexus-contracts"),
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def canonical_json_bytes(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(SERVICE_ROOT.parents[1]).as_posix()
    except ValueError:
        return path.name


def _instruments(policy_path: Path) -> dict[str, object]:
    return {
        "policy_path": _repo_relative(policy_path),
        "policy_sha256": _sha256_file(policy_path),
        "scanner_path": _repo_relative(Path(pii_scanner.__file__)),
        "scanner_sha256": _sha256_file(Path(pii_scanner.__file__)),
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
        "runtime": {"python": sys.version.split()[0], "pypdf": pypdf.__version__},
    }


def _bundle_for(
    *,
    sha: str,
    content: bytes,
    result: pii_scanner.PIIScanResult,
    pages_text: list[str],
    facts: dict[str, object],
    instruments: dict[str, object],
    producer: dict[str, object],
    bundle_dir: Path,
    campaign_id: str,
) -> dict[str, object]:
    bundle_dir.mkdir(parents=True, exist_ok=False)
    (bundle_dir / "pages").mkdir()
    files: dict[str, str] = {}
    (bundle_dir / "document.pdf").write_bytes(content)
    files["document.pdf"] = sha
    concerned = sorted({m.page_number for m in result.matches if m.page_number is not None})
    for page in concerned:
        name = f"pages/page-{page:04d}.txt"
        text = pages_text[page - 1]
        (bundle_dir / name).write_text(text, encoding="utf-8")
        files[name] = _sha256_bytes(text.encode("utf-8"))
    signals = []
    for match in sorted(result.matches, key=lambda m: (m.page_number or 0, m.char_offset, m.pattern_id)):
        page_text = pages_text[(match.page_number or 1) - 1]
        context = finding_context(
            page_text,
            char_offset=match.char_offset,
            match_length=len(match.match_text),
        )
        match_sha = _sha256_bytes(match.match_text.encode("utf-8"))
        context_sha = _sha256_bytes(context.encode("utf-8"))
        # Identité du finding : dérivée par l'autorité unique du scanner, pour
        # que le producteur de release retrouve EXACTEMENT ces findings dans
        # son propre scan (ADR-0047). Une dérivation locale, même identique
        # aujourd'hui, pourrait diverger demain sans que rien ne le dise.
        finding_id = finding_identity(
            content_sha256=sha,
            pattern_id=match.pattern_id,
            page_number=match.page_number,
            char_offset=match.char_offset,
            match_sha256=match_sha,
        )
        signal: dict[str, object] = {
            "finding_id": finding_id,
            "pattern_id": match.pattern_id,
            "description": match.description,
            "page_number": match.page_number,
            "char_offset": match.char_offset,
            "match_length": len(match.match_text),
            "match_sha256": match_sha,
            "context_sha256": context_sha,
            "match_text": match.match_text,
            "context": context,
        }
        if match.pattern_id == "french_ssn":
            signal["checksum_valid"] = nir_checksum_valid(match.match_text)
        signals.append(signal)
    manifest: dict[str, object] = {
        "protocol_version": BUNDLE_PROTOCOL,
        "campaign_id": campaign_id,
        "bundle_id": f"{campaign_id}:{sha}",
        "content_sha256": sha,
        "pdf_sha256": sha,
        "title": facts.get("title"),
        "source_path": facts.get("source_path"),
        "placements": sorted(facts.get("placements", [])),  # type: ignore[arg-type]
        **instruments,
        **producer,
        "page_count": len(pages_text),
        "pages_scanned": result.pages_scanned,
        "ignored_empty_pages": list(result.ignored_empty_pages),
        "characters_scanned": result.characters_scanned,
        "signal_count": len(result.matches),
        "signal_classes": sorted({m.pattern_id for m in result.matches}),
        "pages": concerned,
        "signals": signals,
        "files": dict(sorted(files.items())),
        "raw_pii_in_bundle": True,
        "instructions": (
            "Ce paquet porte de la matière brute : il ne doit jamais entrer dans le dépôt. "
            "Statuez sur chaque correspondance en lisant la page entière, et le PDF si le "
            "contexte ne suffit pas. Toute modification de ce paquet après décision "
            "invalide la décision (empreinte du manifeste)."
        ),
    }
    (bundle_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def preparer_par_extraction_locale(
    *,
    pdf_root: Path,
    content_sha256: Sequence[str],
    placements_path: Path,
    policy_path: Path,
    output_root: Path,
    index_path: Path,
    campaign_id: str,
    require_frozen: bool = True,
) -> dict[str, object]:
    """SUPERSÉDÉE. Génère les paquets en RE-EXTRAYANT le PDF elle-même.

    Conservée pour que les 23 paquets déjà revus restent reproductibles, et
    pour elles seules. Toute nouvelle campagne passe par
    `preparer_depuis_entree_canonique` : re-extraire ici, c'est re-décider du
    sens d'une page, et donc pouvoir présenter au reviewer un texte que ni le
    scanner PII ni le découpage n'ont jamais vu. C'est exactement ce qui a
    laissé l'extraction partielle V1 traverser toute la chaîne.

    `require_frozen` (défaut) refuse un producteur non commité : une campagne
    réelle est liée à UN commit. Les épreuves synthétiques le désactivent."""
    facts_by_sha: dict[str, dict[str, object]] = json.loads(placements_path.read_text(encoding="utf-8"))
    instruments = _instruments(policy_path)
    producer = producer_identity(require_frozen=require_frozen)
    producer["producer_frozen"] = require_frozen
    patterns = pii_scanner.load_patterns_from_config(policy_path)
    output_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    scanned = 0
    for sha in sorted(set(content_sha256)):
        path = pdf_root / f"{sha}.pdf"
        if not path.is_file():
            raise FileNotFoundError(f"mirror file missing for {sha}")
        content = path.read_bytes()
        if _sha256_bytes(content) != sha:
            raise ValueError(f"mirror file {path.name} does not match its content SHA-256")
        result = pii_scanner.scan_pdf_bytes(content, source_path=path.name, patterns=patterns)
        scanned += 1
        if result.extraction_error:
            raise ValueError(f"content {sha} could not be scanned: {result.extraction_error}")
        if not result.pii_detected:
            continue
        pages_text, _ignored, error = pii_scanner.extract_pdf_pages_with_structural_empty_pages(content)
        if error:
            raise ValueError(f"content {sha} could not be paginated: {error}")
        facts = facts_by_sha.get(sha)
        if facts is None:
            raise ValueError(f"no placement facts declared for detected content {sha}")
        bundle_dir = output_root / sha
        if bundle_dir.exists():
            raise FileExistsError(f"bundle already exists: {bundle_dir}")
        manifest = _bundle_for(
            sha=sha, content=content, result=result, pages_text=pages_text, facts=facts,
            instruments=instruments, producer=producer, bundle_dir=bundle_dir,
            campaign_id=campaign_id,
        )
        findings = [
            {
                key: signal[key]
                for key in ("finding_id", "pattern_id", "page", "match_sha256", "context_sha256",
                            "match_length", "checksum_valid")
                if key in signal or key == "page"
            }
            for signal in (
                {**item, "page": item["page_number"]} for item in manifest["signals"]  # type: ignore[union-attr]
            )
        ]
        findings.sort(key=lambda f: str(f["finding_id"]))
        entries.append(
            {
                "content_sha256": sha,
                "bundle_id": manifest["bundle_id"],
                "bundle_dir": sha,
                "bundle_sha256": _sha256_file(bundle_dir / "manifest.json"),
                "pdf_sha256": sha,
                "finding_count": len(findings),
                "pages_with_findings": manifest["pages"],
                "findings": findings,
                "title": manifest["title"],
                "source_path": manifest["source_path"],
                "placements": manifest["placements"],
                "signal_count": manifest["signal_count"],
                "signal_classes": manifest["signal_classes"],
                "pages": manifest["pages"],
                "page_count": manifest["page_count"],
                "files": manifest["files"],
            }
        )
    index: dict[str, object] = {
        "protocol_version": INDEX_PROTOCOL,
        "campaign_id": campaign_id,
        "generated_at": datetime.now(UTC).isoformat(),
        **instruments,
        **producer,
        "content_set_sha256": _sha256_bytes(("\n".join(sorted(set(content_sha256))) + "\n").encode()),
        "counts": {"scanned": scanned, "bundles": len(entries)},
        "raw_pii_in_output": False,
        # L'index ne peut pas porter sa propre empreinte ; c'est l'ensemble de
        # décisions qui l'épingle (`review_index_sha256`).
        "index_sha256_excluded": True,
        "bundles": entries,
    }
    index_path.write_bytes(canonical_json_bytes(index))
    return index


def verifier(*, output_root: Path, index_path: Path) -> list[str]:
    """Rehache chaque paquet contre l'index ; rend la liste des écarts (vide = intact)."""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    problemes: list[str] = []
    for entry in index["bundles"]:
        bundle_dir = output_root / entry["bundle_dir"]
        manifest_path = bundle_dir / "manifest.json"
        if not manifest_path.is_file():
            problemes.append(f"{entry['content_sha256']}: manifest.json missing")
            continue
        if _sha256_file(manifest_path) != entry["bundle_sha256"]:
            problemes.append(f"{entry['content_sha256']}: manifest.json digest differs from the index")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, digest in manifest["files"].items():
            file_path = bundle_dir / name
            if not file_path.is_file():
                problemes.append(f"{entry['content_sha256']}: {name} missing")
            elif _sha256_file(file_path) != digest:
                problemes.append(f"{entry['content_sha256']}: {name} digest differs from the manifest")
    return problemes


CANONICAL_INPUT_SCHEMA = "NEXUS-CANONICAL-REVIEW-INPUT-V1"


def _signaux_depuis_texte_canonique(
    *,
    sha: str,
    pages_text: list[str],
    patterns: list[object],
) -> list[dict[str, object]]:
    """Localise les correspondances DANS le texte canonique du run.

    Ce n'est pas une nouvelle mesure : le texte est prouvé identique à celui
    que le scanner du run a lu (empreinte de page ET empreinte de document),
    et le scanner est le même module épinglé. Ce qu'on ajoute ici est la
    POSITION de chaque correspondance, que le registre du run n'agrège pas —
    et l'agrégat obtenu est confronté au sien juste après.
    """
    signaux: list[dict[str, object]] = []
    for numero, texte in enumerate(pages_text, start=1):
        for correspondance in pii_scanner.scan_text_for_pii(
            texte, patterns, page_number=numero  # type: ignore[arg-type]
        ):
            signaux.append({"page": numero, "match": correspondance})
    signaux.sort(
        key=lambda s: (
            s["page"],
            s["match"].char_offset,  # type: ignore[union-attr]
            s["match"].pattern_id,  # type: ignore[union-attr]
        )
    )
    return signaux


def preparer_depuis_entree_canonique(
    *,
    canonical_input_root: Path,
    pdf_root: Path,
    placements_path: Path,
    policy_path: Path,
    output_root: Path,
    index_path: Path,
    campaign_id: str,
    run_pii_ledger: dict[str, dict[str, object]],
    require_frozen: bool = True,
) -> dict[str, object]:
    """Génère les paquets depuis la SORTIE CANONIQUE du traitement (§ 6, § 7).

    Le préparateur ne lit plus le PDF pour en tirer du texte : il consomme le
    texte qui a réellement alimenté le scanner PII, le découpage et
    `canonical_text_sha256`. Le PDF entier reste dans le paquet — le reviewer
    doit pouvoir confronter le finding au document — mais aucun finding n'est
    recalculé depuis une nouvelle extraction.
    """
    manifeste = json.loads(
        (canonical_input_root / "manifest.json").read_text(encoding="utf-8")
    )
    if manifeste.get("schema") != CANONICAL_INPUT_SCHEMA:
        raise ValueError(
            f"entrée de revue de schéma inattendu : {manifeste.get('schema')!r}"
        )
    facts_by_sha: dict[str, dict[str, object]] = json.loads(
        placements_path.read_text(encoding="utf-8")
    )
    instruments = _instruments(policy_path)
    producer = producer_identity(require_frozen=require_frozen)
    producer["producer_frozen"] = require_frozen
    # La lignée du TRAITEMENT, distincte de celle du producteur de paquets :
    # sans elle, un paquet ne dit pas de quel run son texte provient.
    lineage = {
        cle: manifeste[cle]
        for cle in (
            "FULL_DRIVE_PROCESSING_RUN_ID",
            "EXTRACTION_POLICY_ID",
            "PAGE_POLICY_ID",
            "PAGE_POLICY_SHA256",
            "OCR_RUNTIME_IDENTITY",
            "PII_LEDGER_SHA256",
        )
        if cle in manifeste
    }
    patterns = pii_scanner.load_patterns_from_config(policy_path)
    output_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []

    for entree in manifeste["entries"]:
        sha = str(entree["content_sha256"])
        dossier = canonical_input_root / sha
        document = json.loads((dossier / "document.json").read_text(encoding="utf-8"))

        pages_text: list[str] = []
        for numero in range(1, int(document["page_count"]) + 1):
            nom = f"pages/page-{numero:04d}.txt"
            # Lu en OCTETS puis décodé : `read_text` traduit les fins de ligne
            # (`\r\n` et `\r` deviennent `\n`). Le texte canonique du corpus
            # gouverné contient de vrais `\r` — les traduire présenterait au
            # reviewer un texte différent de celui qui a été scanné, ce que ce
            # lot existe précisément pour empêcher.
            texte = (dossier / nom).read_bytes().decode("utf-8")
            if _sha256_bytes(texte.encode("utf-8")) != document["files"][nom]:
                raise ValueError(
                    f"{sha[:16]}… page {numero} : le texte de l'entrée canonique "
                    "ne correspond pas à son empreinte déclarée"
                )
            pages_text.append(texte)

        texte_canonique = "\n".join(pages_text)
        empreinte_texte = _sha256_bytes(texte_canonique.encode("utf-8"))
        if empreinte_texte != document["canonical_text_sha256"]:
            raise ValueError(
                f"{sha[:16]}… : le texte recomposé hache vers {empreinte_texte[:16]}… "
                f"là où l'entrée canonique annonce {document['canonical_text_sha256'][:16]}…"
            )
        registre = run_pii_ledger.get(sha)
        if registre is None:
            raise ValueError(
                f"{sha[:16]}… : absent du registre PII du run — un paquet sans "
                "détection du run n'a rien à faire revoir"
            )
        if registre["canonical_text_sha256"] != empreinte_texte:
            raise ValueError(
                f"{sha[:16]}… : le texte de revue n'est pas celui que le run a scanné"
            )

        provenance = {int(p["page_number"]): p for p in document["page_provenance"]}
        signaux = _signaux_depuis_texte_canonique(
            sha=sha, pages_text=pages_text, patterns=patterns
        )
        classes = sorted({s["match"].pattern_id for s in signaux})  # type: ignore[union-attr]
        concerned = sorted({int(s["page"]) for s in signaux})
        # L'agrégat DOIT retomber sur celui du run. S'il diverge, ce n'est pas
        # le paquet qui est faux : c'est que le scanner ou la politique ont
        # bougé sous une lignée qui prétend ne pas avoir bougé.
        if (
            classes != sorted(registre["pattern_ids"])  # type: ignore[arg-type]
            or concerned != sorted(registre["pages"])  # type: ignore[arg-type]
            or len(signaux) != int(registre["match_count"])  # type: ignore[arg-type]
        ):
            raise ValueError(
                f"{sha[:16]}… : le scan du texte canonique rend "
                f"{len(signaux)} correspondance(s) sur {concerned} là où le run "
                f"en a enregistré {registre['match_count']} sur {registre['pages']}"
            )

        bundle_dir = output_root / sha
        if bundle_dir.exists():
            raise FileExistsError(f"bundle already exists: {bundle_dir}")
        pdf_path = pdf_root / f"{sha}.pdf"
        if not pdf_path.is_file():
            raise FileNotFoundError(f"mirror file missing for {sha}")
        content = pdf_path.read_bytes()
        if _sha256_bytes(content) != sha:
            raise ValueError(
                f"mirror file {pdf_path.name} does not match its content SHA-256"
            )

        bundle_dir.mkdir(parents=True, exist_ok=False)
        (bundle_dir / "pages").mkdir()
        files: dict[str, str] = {"document.pdf": sha}
        (bundle_dir / "document.pdf").write_bytes(content)
        os.chmod(bundle_dir / "document.pdf", 0o600)
        for page in concerned:
            nom = f"pages/page-{page:04d}.txt"
            texte = pages_text[page - 1]
            # Écrit en OCTETS pour la même raison : `write_text` traduirait
            # `\n` en fin de ligne de la plateforme et l'empreinte scellée ne
            # désignerait plus le texte scanné.
            (bundle_dir / nom).write_bytes(texte.encode("utf-8"))
            os.chmod(bundle_dir / nom, 0o600)
            files[nom] = _sha256_bytes(texte.encode("utf-8"))

        signals: list[dict[str, object]] = []
        for signal in signaux:
            match = signal["match"]
            page_number = int(signal["page"])
            page_text = pages_text[page_number - 1]
            context = finding_context(
                page_text,
                char_offset=match.char_offset,  # type: ignore[union-attr]
                match_length=len(match.match_text),  # type: ignore[union-attr]
            )
            match_sha = _sha256_bytes(match.match_text.encode("utf-8"))  # type: ignore[union-attr]
            trace = provenance[page_number]
            rendu: dict[str, object] = {
                "finding_id": finding_identity(
                    content_sha256=sha,
                    pattern_id=match.pattern_id,  # type: ignore[union-attr]
                    page_number=page_number,
                    char_offset=match.char_offset,  # type: ignore[union-attr]
                    match_sha256=match_sha,
                ),
                "pattern_id": match.pattern_id,  # type: ignore[union-attr]
                "description": match.description,  # type: ignore[union-attr]
                "page_number": page_number,
                "char_offset": match.char_offset,  # type: ignore[union-attr]
                "match_length": len(match.match_text),  # type: ignore[union-attr]
                "match_sha256": match_sha,
                "context_sha256": _sha256_bytes(context.encode("utf-8")),
                "match_text": match.match_text,  # type: ignore[union-attr]
                "context": context,
                # § 10 : le reviewer doit savoir que la page montrée vient du
                # repli OCR canonique, sans qu'on lui ajoute de matière.
                "extraction_path": trace["extraction_path"],
                "page_policy_verdict": trace["page_policy_verdict"],
                "canonical_page_text_sha256": trace["canonical_page_text_sha256"],
                "ocr_runtime_identity_sha256": trace["ocr_runtime_identity_sha256"],
            }
            if match.pattern_id == "french_ssn":  # type: ignore[union-attr]
                rendu["checksum_valid"] = nir_checksum_valid(match.match_text)  # type: ignore[union-attr]
            signals.append(rendu)

        facts = facts_by_sha.get(sha)
        if facts is None:
            raise ValueError(f"no placement facts declared for detected content {sha}")
        manifest: dict[str, object] = {
            "protocol_version": BUNDLE_PROTOCOL,
            "campaign_id": campaign_id,
            "bundle_id": f"{campaign_id}:{sha}",
            "content_sha256": sha,
            "pdf_sha256": sha,
            "title": facts.get("title"),
            "source_path": facts.get("source_path"),
            "placements": sorted(facts.get("placements", [])),  # type: ignore[arg-type]
            **instruments,
            **producer,
            **lineage,
            # Ce que le reviewer lit vient du run, pas d'une extraction locale.
            "review_input_schema": CANONICAL_INPUT_SCHEMA,
            "canonical_text_sha256": empreinte_texte,
            "page_provenance_digest": document["page_provenance_digest"],
            "extraction_identity_sha256": document["extraction_identity_sha256"],
            "page_count": len(pages_text),
            "signal_count": len(signals),
            "signal_classes": classes,
            "pages": concerned,
            "page_provenance": [provenance[p] for p in concerned],
            "signals": signals,
            "files": dict(sorted(files.items())),
            "raw_pii_in_bundle": True,
            "instructions": (
                "Ce paquet porte de la matière brute : il ne doit jamais entrer dans "
                "le dépôt. Le texte des pages est CELUI qui a alimenté le scanner PII "
                "et le découpage — il n'a pas été ré-extrait du PDF. Une page dont "
                "extraction_path vaut OCR_FALLBACK provient du repli OCR canonique. "
                "Statuez sur chaque correspondance en lisant la page entière, et le "
                "PDF si le contexte ne suffit pas. Toute modification de ce paquet "
                "après décision invalide la décision (empreinte du manifeste)."
            ),
        }
        (bundle_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        os.chmod(bundle_dir / "manifest.json", 0o600)

        findings = [
            {
                cle: signal[cle]
                for cle in (
                    "finding_id", "pattern_id", "page_number", "match_sha256",
                    "context_sha256", "match_length", "checksum_valid",
                    "extraction_path", "canonical_page_text_sha256",
                )
                if cle in signal
            }
            for signal in signals
        ]
        findings.sort(key=lambda f: str(f["finding_id"]))
        entries.append(
            {
                "content_sha256": sha,
                "bundle_id": manifest["bundle_id"],
                "bundle_dir": sha,
                "bundle_sha256": _sha256_file(bundle_dir / "manifest.json"),
                "pdf_sha256": sha,
                "canonical_text_sha256": empreinte_texte,
                "page_provenance_digest": document["page_provenance_digest"],
                "finding_count": len(findings),
                "findings": findings,
                "title": manifest["title"],
                "source_path": manifest["source_path"],
                "placements": manifest["placements"],
                "signal_count": len(signals),
                "signal_classes": classes,
                "pages": concerned,
                "page_count": len(pages_text),
                "files": manifest["files"],
            }
        )

    index: dict[str, object] = {
        "protocol_version": INDEX_PROTOCOL,
        "campaign_id": campaign_id,
        "generated_at": datetime.now(UTC).isoformat(),
        **instruments,
        **producer,
        **lineage,
        "review_input_schema": CANONICAL_INPUT_SCHEMA,
        "review_input_content_set_sha256": manifeste["content_set_sha256"],
        "content_set_sha256": _sha256_bytes(
            ("\n".join(sorted(e["content_sha256"] for e in entries)) + "\n").encode()  # type: ignore[misc]
        ),
        # Les MÊMES noms que `NEXUS-PII-REVIEW-INDEX-V1` porte déjà : un index
        # qui renommerait ses clés serait un protocole neuf, et le
        # vérificateur comme la projection de release cesseraient de le lire.
        "counts": {
            "scanned": len(entries),
            "bundles": len(entries),
            "findings": sum(int(e["finding_count"]) for e in entries),  # type: ignore[arg-type]
        },
        "raw_pii_in_output": True,
        "index_sha256_excluded": True,
        "bundles": sorted(entries, key=lambda e: str(e["content_sha256"])),
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(canonical_json_bytes(index))
    return index


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verifier", action="store_true")
    parser.add_argument("--pdf-root", type=Path)
    parser.add_argument("--content-set", type=Path)
    parser.add_argument("--placements", type=Path)
    parser.add_argument("--policy", type=Path, default=SERVICE_ROOT / "configs/pii_gate_policy.yml")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--campaign-id")
    parser.add_argument(
        "--canonical-input",
        type=Path,
        required=False,
        help=(
            "racine d'un NEXUS-CANONICAL-REVIEW-INPUT-V1 : le texte de revue "
            "vient du run, il n'est pas ré-extrait du PDF"
        ),
    )
    parser.add_argument(
        "--run-report",
        type=Path,
        help="rapport du run dont le registre PII fait autorité sur les agrégats",
    )
    args = parser.parse_args(argv)
    if args.verifier:
        problemes = verifier(output_root=args.output_root, index_path=args.index)
        print(json.dumps({"intact": not problemes, "ecarts": problemes}, ensure_ascii=False, indent=2))
        return 0 if not problemes else 1
    # Le CLI n'expose plus la voie qui ré-extrait : une campagne réelle passe
    # par la sortie canonique du traitement. La fonction supersédée reste
    # appelable depuis les épreuves qui prouvent la reproductibilité des 23
    # paquets historiques, et de là seulement.
    if not (args.canonical_input and args.run_report and args.pdf_root
            and args.placements and args.campaign_id):
        parser.error(
            "--canonical-input, --run-report, --pdf-root, --placements et "
            "--campaign-id sont requis"
        )
    rapport = json.loads(args.run_report.read_text(encoding="utf-8"))
    registre = {
        entree["artifact_id"]: {
            "canonical_text_sha256": entree["canonical_text_sha256"],
            "pattern_ids": entree["pattern_ids"],
            "pages": entree["pages"],
            "match_count": entree["match_count"],
        }
        for entree in rapport["pii_detectes"]
    }
    index = preparer_depuis_entree_canonique(
        canonical_input_root=args.canonical_input, pdf_root=args.pdf_root,
        placements_path=args.placements, policy_path=args.policy,
        output_root=args.output_root, index_path=args.index,
        campaign_id=args.campaign_id, run_pii_ledger=registre,
    )
    print(json.dumps({"index": str(args.index), "index_sha256": _sha256_file(args.index), "counts": index["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
