"""Points d'entrée en ligne de commande de la chaîne de preuves.

Un workflow ne doit pas contenir de logique de gouvernance. Chaque étape
appelle ici une sous-commande dont le comportement est testé en Python ;
le YAML se limite à enchaîner et à propager des digests. Un contrôle
écrit en shell dans un workflow n'est vérifiable que par relecture, et
personne ne relit un ``if`` de bash aussi attentivement qu'un test.

Toutes les sorties sont canoniques : clés triées, indentation fixe, LF
final. Les digests qui en découlent identifient donc un contenu, jamais
une exécution.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from rag_pedago.governance.corpus_campaign import parse_corpus_campaign
from rag_pedago.governance.corpus_review_view import (
    build_review_view,
    render_markdown,
)
from rag_pedago.governance.corpus_source_resolver import (
    CorpusSourceUnavailable,
    resolve_corpus_source,
)
from rag_pedago.governance.h2_evidence import H2EvidenceBundle
from rag_pedago.imports.artifact_placement_model import compute_file_sha256


def _write_canonical(path: Path, payload: dict) -> str:
    """Écrit un JSON canonique et rend son digest."""
    import hashlib

    raw = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _oras_pull(reference: str) -> tuple[bytes, str]:
    """Tire l'artefact par sa référence **dérivée du descripteur**.

    Le digest rendu est celui que le registre annonce ; le résolveur le
    recoupe ensuite avec celui qu'a approuvé la campagne. Aucune sortie
    d'erreur du registre n'est relayée : elle peut contenir un jeton."""
    try:
        completed = subprocess.run(
            ["oras", "pull", reference, "--output", "-"],
            capture_output=True,
            check=False,
            timeout=3600,
        )
    except FileNotFoundError as exc:  # pragma: no cover - dépend du runner
        raise CorpusSourceUnavailable("'oras' is not installed") from exc
    if completed.returncode != 0:
        raise CorpusSourceUnavailable(
            f"oras pull failed with exit code {completed.returncode}"
        )
    resolved = subprocess.run(
        ["oras", "resolve", reference],
        capture_output=True,
        check=False,
        timeout=300,
    )
    if resolved.returncode != 0:
        raise CorpusSourceUnavailable("oras resolve failed")
    return completed.stdout, resolved.stdout.decode().strip()


def cmd_resolve_corpus(args: argparse.Namespace) -> int:
    """Résout, rematérialise et rehache le corpus décrit par la campagne."""
    campaign = parse_corpus_campaign(args.campaign.read_bytes())
    resolved = resolve_corpus_source(
        campaign, destination=args.destination, pull=_oras_pull
    )
    _write_canonical(
        args.output,
        {
            "campaign_id": campaign.campaign_id,
            "oci_digest": resolved.oci_digest,
            "archive_sha256": resolved.archive_sha256,
            "tree_digest": resolved.tree_digest,
            "manifest_sha256": resolved.manifest.manifest_sha256,
            "object_count": resolved.manifest.object_count,
            "root": str(resolved.root),
        },
    )
    print(f"corpus resolved: {resolved.manifest.object_count} objects")
    return 0


def cmd_review_view(args: argparse.Namespace) -> int:
    """Rend la vue de revue — aide à la relecture, jamais une autorité.

    Le catalogue est **recompilé** depuis le manifeste scellé plutôt que
    relu depuis un JSON. La vue décrit ainsi exactement l'objet que le
    gate examine ; un aller-retour par une sérialisation dont la fidélité
    n'est testée nulle part introduirait un écart possible entre ce qu'un
    humain relit et ce qui est évalué.
    """
    from rag_pedago.imports.corpus_catalog_compiler import (
        compile_sealed_catalog,
        load_routing_config,
    )

    config = load_routing_config(args.config)
    config["manifest_sha256"] = compute_file_sha256(args.sealed_manifest)
    catalog = compile_sealed_catalog(
        args.sealed_manifest, args.placement_catalog, config
    )

    baseline = None
    if args.baseline_manifest:
        baseline_config = load_routing_config(args.config)
        baseline_config["manifest_sha256"] = compute_file_sha256(
            args.baseline_manifest
        )
        baseline = compile_sealed_catalog(
            args.baseline_manifest,
            args.baseline_placement_catalog or args.placement_catalog,
            baseline_config,
        )

    view = build_review_view(
        campaign_id=args.campaign_id,
        source_oci_digest=args.source_oci_digest,
        source_tree_digest=args.source_tree_digest,
        manifest_sha256=catalog.manifest_sha256,
        catalog_sha256=args.catalog_sha256,
        current=catalog,
        baseline=baseline,
        authorized_scopes=args.authorized_scope or None,
    )
    args.json.write_bytes(view.to_canonical_json())
    if args.markdown:
        args.markdown.write_text(render_markdown(view), encoding="utf-8")

    print(f"review view: {view.view_sha256}")
    if view.anomalies:
        print(f"  {len(view.anomalies)} anomalies", file=sys.stderr)
        for anomaly in view.anomalies[:20]:
            print(f"  - {anomaly.code}: {anomaly.subject}", file=sys.stderr)
    if view.escalations:
        print(
            f"  {len(view.escalations)} escalations widen publication",
            file=sys.stderr,
        )
    # La vue n'échoue pas sur une anomalie : elle la rend visible. C'est le
    # gate qui refuse, et la revue humaine qui décide.
    return 0


def cmd_h2_evidence(args: argparse.Namespace) -> int:
    """Assemble et écrit ``NEXUS-H2-EVIDENCE-V1``."""
    report = json.loads(args.h2_report.read_text(encoding="utf-8"))

    bundle = H2EvidenceBundle(
        repository=args.repository,
        pull_request_number=args.pull_request,
        pr_head_sha=args.pr_head_sha,
        pr_head_tree_sha=args.pr_head_tree_sha,
        merge_sha=args.merge_sha,
        merge_tree_sha=args.merge_tree_sha,
        campaign_id=args.campaign_id,
        campaign_sha256=args.campaign_sha256,
        source_oci_digest=args.source_oci_digest,
        source_archive_sha256=args.source_archive_sha256,
        source_tree_digest=args.source_tree_digest,
        manifest_sha256=args.manifest_sha256,
        catalog_sha256=args.catalog_sha256,
        review_view_sha256=args.review_view_sha256,
        authorization_sha256=args.authorization_sha256,
        revocation_registry_sha256=args.revocation_registry_sha256,
        trust_anchor_sha256=args.trust_anchor_sha256,
        exact_head_receipt_sha256=args.exact_head_receipt_sha256,
        exact_head_receipt_issued_at=args.exact_head_receipt_issued_at,
        routing_config_sha256=args.routing_config_sha256,
        rights_config_sha256=args.rights_config_sha256,
        pii_config_sha256=args.pii_config_sha256,
        golden_config_sha256=args.golden_config_sha256,
        h2_report_sha256=args.h2_report_sha256,
        h2_coverage_gate_pass=bool(report.get("h2_coverage_gate_pass")),
        authority_revocations_checked=bool(
            report.get("authority_revocations_checked")
        ),
        coverage_complete=bool(report.get("coverage_complete")),
        environment=args.environment,
        workflow_path=args.workflow_path,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )

    # L'horodatage est passé à l'enveloppe, jamais lu depuis le contenu :
    # le digest doit rester reproductible à partir du contenu seul.
    produced_at = datetime.now(UTC).isoformat()
    envelope = bundle.to_envelope(produced_at=produced_at)
    args.output.write_bytes(
        (
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
    )
    print(f"h2 evidence: {bundle.content_sha256}")
    print(f"artifact name: {bundle.artifact_name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-pedago-governance",
        description="Chaîne de preuves du corpus gouverné.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser(
        "resolve-corpus",
        help="Résout un corpus OCI par digest et le rehache intégralement.",
    )
    resolve.add_argument("--campaign", type=Path, required=True)
    resolve.add_argument("--destination", type=Path, required=True)
    resolve.add_argument("--output", type=Path, required=True)
    resolve.set_defaults(func=cmd_resolve_corpus)

    review = sub.add_parser("review-view", help="Rend la vue de revue humaine.")
    review.add_argument("--sealed-manifest", type=Path, required=True)
    review.add_argument("--placement-catalog", type=Path, required=True)
    review.add_argument("--config", type=Path, required=True)
    review.add_argument("--baseline-manifest", type=Path)
    review.add_argument("--baseline-placement-catalog", type=Path)
    review.add_argument("--campaign-id", required=True)
    review.add_argument("--source-oci-digest", required=True)
    review.add_argument("--source-tree-digest", required=True)
    review.add_argument("--catalog-sha256", required=True)
    review.add_argument("--authorized-scope", action="append")
    review.add_argument("--json", type=Path, required=True)
    review.add_argument("--markdown", type=Path)
    review.set_defaults(func=cmd_review_view)

    evidence = sub.add_parser(
        "h2-evidence", help="Assemble le bundle NEXUS-H2-EVIDENCE-V1."
    )
    for flag in (
        "--repository",
        "--pr-head-sha",
        "--pr-head-tree-sha",
        "--merge-sha",
        "--merge-tree-sha",
        "--campaign-id",
        "--campaign-sha256",
        "--source-oci-digest",
        "--source-archive-sha256",
        "--source-tree-digest",
        "--manifest-sha256",
        "--catalog-sha256",
        "--review-view-sha256",
        "--authorization-sha256",
        "--revocation-registry-sha256",
        "--trust-anchor-sha256",
        "--exact-head-receipt-sha256",
        "--exact-head-receipt-issued-at",
        "--routing-config-sha256",
        "--rights-config-sha256",
        "--pii-config-sha256",
        "--golden-config-sha256",
        "--h2-report-sha256",
        "--environment",
        "--workflow-path",
        "--run-id",
    ):
        evidence.add_argument(flag, required=True)
    evidence.add_argument("--pull-request", type=int, required=True)
    evidence.add_argument("--run-attempt", type=int, required=True)
    evidence.add_argument("--h2-report", type=Path, required=True)
    evidence.add_argument("--output", type=Path, required=True)
    evidence.set_defaults(func=cmd_h2_evidence)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
