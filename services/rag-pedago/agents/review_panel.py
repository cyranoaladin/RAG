"""ReviewPanel — orchestrateur du panel de revue par agents experts (LOT 29, ADR-0018).

Remplace l'acteur humain de l'etape « review » (quality -> gate -> review) par
un panel de reviewers experts deterministes (rights / subject / quality).
Decision par consensus unanime ; tout desaccord, doute ou reviewer en echec
envoie en quarantaine. La regle « droits inconnus -> quarantaine » est dure et
non delegable.

Perimetre strict : revue des artefacts STAGING uniquement. Le panel n'ecrit
jamais dans pgvector ; l'indexation reste soumise a la chaine gouvernee.

Usage (depuis services/rag-pedago) :
    python -m agents.review_panel --plan     # liste les artefacts en attente
    python -m agents.review_panel --run      # relit tous les 'pending'
    python -m agents.review_panel --report   # synthese du dernier run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agents.base import ROOT
from agents.reviewers import REVIEWER_CLASSES, Artefact, Verdict

POLICY_PATH = ROOT / "configs" / "review_policy.yml"
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _lock(name: str) -> bool:
    if not CONTRACT_PATH.is_file():
        return False
    cfg = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return isinstance(cfg, dict) and cfg.get(name) is True


class ReviewPanel:
    """Panel de reviewers experts — consensus unanime, quarantaine par defaut."""

    def __init__(self, policy_path: Path = POLICY_PATH) -> None:
        self.policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        self.staging_root = ROOT / self.policy.get("staging_root", "data/staging/agents/continuous")
        self.reviewers = []
        for spec in self.policy.get("reviewers", []):
            cls = REVIEWER_CLASSES[spec["id"]]
            self.reviewers.append(cls(self.policy))

    # ---------------------------------------------------------------
    # Collecte des artefacts en attente
    # ---------------------------------------------------------------
    def pending_artefacts(self) -> list[Artefact]:
        artefacts: list[Artefact] = []
        if not self.staging_root.is_dir():
            return artefacts
        for manifest_path in sorted(self.staging_root.rglob("manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if manifest.get("review_status") != "pending":
                continue
            page = manifest_path.parent / "page.txt"
            text = page.read_text(encoding="utf-8") if page.is_file() else ""
            artefacts.append(Artefact(staging_dir=manifest_path.parent,
                                      manifest=manifest, text=text))
        return artefacts

    # ---------------------------------------------------------------
    # Decision du panel
    # ---------------------------------------------------------------
    def decide(self, artefact: Artefact) -> dict[str, Any]:
        verdicts: list[Verdict] = []
        for reviewer in self.reviewers:
            try:
                verdicts.append(reviewer.review(artefact))
            except Exception as exc:
                # Un reviewer en echec ne peut pas approuver (fail-closed).
                v = Verdict(reviewer=reviewer.reviewer_id, status="quarantine",
                            reasons=[f"reviewer en echec: {exc}"],
                            rules_fired=["on_reviewer_error:quarantine"])
                v.sign()
                verdicts.append(v)

        statuses = {v.status for v in verdicts}
        if statuses == {"approved"} and len(verdicts) == len(self.reviewers):
            decision = "approved"
        elif statuses == {"rejected"} and len(verdicts) == len(self.reviewers):
            # Rejet unanime : tous les reviewers rejettent -> rejected.
            decision = "rejected"
        else:
            # Toute autre combinaison (desaccord approved/rejected, quarantaine,
            # reviewer en echec) -> quarantaine (on_disagreement: quarantine).
            decision = "quarantine"

        # Digest calcule sur les octets REELLEMENT relus (page.txt), pas sur le
        # digest declare dans le manifeste : meme en cas d'integrite rompue, la
        # trace auditable etablit quels octets ont produit le verdict.
        page = artefact.staging_dir / "page.txt"
        content_sha256 = hashlib.sha256(
            page.read_bytes() if page.is_file() else b""
        ).hexdigest()

        payload = {
            "source_id": artefact.manifest.get("source_id"),
            "artefact_sha256": content_sha256,
            "manifest_sha256": artefact.manifest.get("sha256"),
            "decision": decision,
            "verdicts": [asdict(v) for v in verdicts],
            "decided_at": _utcnow(),
            "panel_version": self.policy.get("policy_id"),
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        payload["panel_signature"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return payload

    # ---------------------------------------------------------------
    # Deduplication idempotente du flux append-only
    # ---------------------------------------------------------------
    @staticmethod
    def _dedup_key(record: dict[str, Any]) -> tuple[Any, ...]:
        """Cle stable d'une decision : hors timestamp et signature."""
        return (
            record.get("source_id"),
            record.get("artefact_sha256"),
            record.get("decision"),
            record.get("panel_version"),
        )

    def _already_recorded(self, manifest_jsonl: Path, payload: dict[str, Any]) -> bool:
        """Vrai si une decision identique (meme source, memes octets relus,
        meme decision, meme version de panel) est deja consignee."""
        if not manifest_jsonl.is_file():
            return False
        key = self._dedup_key(payload)
        with manifest_jsonl.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and self._dedup_key(record) == key:
                    return True
        return False

    # ---------------------------------------------------------------
    # Run : revue de tous les artefacts 'pending'
    # ---------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        if not _lock("data_staging_allowed"):
            return {"error": "verrou data_staging_allowed absent ou false (fail-closed)",
                    "exit_code": 1}

        artefacts = self.pending_artefacts()
        counts = {"approved": 0, "rejected": 0, "quarantine": 0}
        decisions: list[dict[str, Any]] = []

        outputs = self.policy.get("outputs", {})
        manifest_jsonl = ROOT / outputs.get("review_manifest_jsonl", "data/review/review_panel_manifest.jsonl")
        ledger = ROOT / outputs.get("ledger_append", "data/ledger/review_panel.jsonl")
        manifest_jsonl.parent.mkdir(parents=True, exist_ok=True)
        ledger.parent.mkdir(parents=True, exist_ok=True)

        for artefact in artefacts:
            payload = self.decide(artefact)
            decision = payload["decision"]
            counts[decision] += 1

            # Trace append-only AVANT la mise a jour du manifeste : le ledger
            # est la source de verite. Si l'append echoue, l'artefact reste
            # 'pending' et sera relu au prochain run (recouvrable, rejouable).
            # Append idempotent : une decision identique (meme source, memes
            # octets, meme decision, meme panel) deja consignee n'est pas
            # dupliquee — le re-run apres echec ne cree pas de double trace.
            if not self._already_recorded(manifest_jsonl, payload):
                with manifest_jsonl.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

            # Mise a jour du manifeste staging (verdict du panel signe)
            artefact.manifest["review_status"] = decision
            artefact.manifest["review_verdict"] = payload
            (artefact.staging_dir / "manifest.json").write_text(
                json.dumps(artefact.manifest, indent=2, ensure_ascii=False), encoding="utf-8")

            decisions.append(payload)

        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "run_at": _utcnow(), "panel_version": self.policy.get("policy_id"),
                "reviewed": len(decisions), "counts": counts,
            }, ensure_ascii=False) + "\n")

        self._write_report(counts, decisions)
        return {"status": "ok", "reviewed": len(decisions), "counts": counts,
                "decisions": decisions, "exit_code": 0}

    def _write_report(self, counts: dict[str, int], decisions: list[dict[str, Any]]) -> None:
        outputs = self.policy.get("outputs", {})
        report_path = ROOT / outputs.get("report_file", "data/reports/review_panel_latest.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Rapport du panel de revue agents (LOT 29 / ADR-0018)",
            "",
            f"- Panel : `{self.policy.get('policy_id')}` — consensus {self.policy.get('consensus')}",
            f"- Artefacts relus : {sum(counts.values())}",
            f"- Approuves : {counts['approved']} | Rejetes : {counts['rejected']} | Quarantaine : {counts['quarantine']}",
            "",
            "## Invariants",
            "- Revue staging uniquement ; aucune ecriture pgvector.",
            "- Regle dure : droits inconnus -> quarantaine (non delegable).",
            "- Tout desaccord entre reviewers -> quarantaine.",
            "- Chaque verdict est signe et consigne au ledger (reversible, rejouable).",
            "",
            "## Decisions",
        ]
        for d in decisions:
            reasons = "; ".join(
                r for v in d["verdicts"] for r in v["reasons"][:1]
            )
            lines.append(f"- `{d['source_id']}` → **{d['decision']}** ({d['panel_signature']}) — {reasons}")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Panel de revue par agents experts (LOT 29)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true", help="Liste les artefacts en attente")
    group.add_argument("--run", action="store_true", help="Relit tous les artefacts 'pending'")
    args = parser.parse_args()

    panel = ReviewPanel()
    if args.plan:
        pending = panel.pending_artefacts()
        out = {
            "panel_version": panel.policy.get("policy_id"),
            "reviewers": [r.reviewer_id for r in panel.reviewers],
            "consensus": panel.policy.get("consensus"),
            "pending": len(pending),
            "artefacts": [a.manifest.get("source_id") for a in pending],
            "exit_code": 0,
        }
    else:
        out = panel.run()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    exit_code = out.get("exit_code", 0)
    sys.exit(exit_code if isinstance(exit_code, int) else 1)


if __name__ == "__main__":
    main()
