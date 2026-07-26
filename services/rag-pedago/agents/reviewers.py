"""Agents relecteurs experts du panel de revue (LOT 29, ADR-0018).

Trois reviewers deterministes et auditables :
- RightsExpertAgent  : droits resolus par provenance (regle dure : inconnu -> quarantaine) ;
- SubjectExpertAgent : conformite au programme officiel (couverture des notions
  de la taxonomie de la collection cible dans le texte depose) ;
- QualityExpertAgent : substance, integrite sha256, completude du manifeste.

Chaque verdict est signe (agent_id + regles declenchees + sha256 du payload)
et consigne au ledger — decisions reversibles, traçables, rejouables.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from agents.base import ROOT

POLICY_PATH = ROOT / "configs" / "review_policy.yml"
_WS_RE = re.compile(r"\s+")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _norm(text: str) -> str:
    """Normalisation pour le matching : minuscules + accents replies
    (un libelle 'mathematiques' matche une page 'Mathématiques')."""
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(c)
    )
    return _WS_RE.sub(" ", folded).strip()


@dataclass
class Verdict:
    reviewer: str
    status: str                      # approved | rejected | quarantine
    reasons: list[str] = field(default_factory=list)
    rules_fired: list[str] = field(default_factory=list)
    signature: str = ""

    def sign(self) -> None:
        payload = json.dumps(
            {"reviewer": self.reviewer, "status": self.status,
             "reasons": sorted(self.reasons), "rules": sorted(self.rules_fired)},
            sort_keys=True, ensure_ascii=False,
        )
        self.signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Artefact:
    """Artefact staging a relire (manifest.json + page.txt)."""
    staging_dir: Path
    manifest: dict[str, Any]
    text: str


class BaseReviewer:
    reviewer_id = "base"

    def __init__(self, policy: dict[str, Any]) -> None:
        self.policy = policy

    def review(self, artefact: Artefact) -> Verdict:  # pragma: no cover - abstract
        raise NotImplementedError


class RightsExpertAgent(BaseReviewer):
    """Droits et licences resolus par provenance — jamais par classification."""

    reviewer_id = "rights_expert"

    def review(self, artefact: Artefact) -> Verdict:
        v = Verdict(reviewer=self.reviewer_id, status="approved")
        url = artefact.manifest.get("url", "")
        domain = urlparse(url).netloc
        rights_map = self.policy.get("rights_map", {})
        resolved = rights_map.get(domain)

        if resolved is None:
            # REGLE DURE (ADR-0018 §regles) : droits inconnus -> quarantaine,
            # non delegable, aucune exception possible.
            v.status = "quarantine"
            v.reasons.append(f"droits inconnus pour la provenance '{domain}'")
            v.rules_fired.append("unknown_rights_action:quarantine")
        else:
            declared = artefact.manifest.get("rights_default")
            if declared and declared != resolved:
                v.status = "rejected"
                v.reasons.append(
                    f"rights_default declare '{declared}' != resolu '{resolved}' par provenance"
                )
                v.rules_fired.append("rights_mismatch")
            else:
                v.reasons.append(f"provenance '{domain}' -> droits '{resolved}'")
                v.rules_fired.append("rights_resolved_by_provenance")
        v.sign()
        return v


class SubjectExpertAgent(BaseReviewer):
    """Conformite au programme officiel : couverture des notions de la taxonomie."""

    reviewer_id = "subject_expert"

    def __init__(self, policy: dict[str, Any]) -> None:
        super().__init__(policy)
        cfg = policy.get("subject_expert", {})
        self.catalogue_path = (ROOT / cfg.get("catalogue", "")).resolve()
        self.taxonomy_root = ROOT / cfg.get("taxonomy_root", "taxonomy")
        self.min_coverage = float(cfg.get("min_notion_coverage", 0.05))
        self.missing_taxonomy_action = cfg.get("missing_taxonomy_action", "quarantine")
        # Regle differenciee pour les collections `domain: exam` (LOT 31) :
        # un sujet d'examen se juge a des marqueurs d'examen, pas a la
        # couverture notionnelle d'un programme.
        exam_cfg = cfg.get("exam_domain", {})
        # Marqueurs normalises avec _norm (accents plies) pour correspondre
        # au texte normalise : sans cela 'epreuve' (texte plie) ne matchait
        # jamais le marqueur accentue 'épreuve' (revue PR #74, round 5).
        self.exam_markers = [_norm(str(m)) for m in exam_cfg.get("markers", [
            "session", "sujet", "épreuve", "annales",
            "corrigé", "baccalauréat", "durée",
        ])]
        self.exam_min_markers = int(exam_cfg.get("min_markers", 2))

    def _catalogue_entry(self, collection: str) -> dict[str, Any] | None:
        if not self.catalogue_path.is_file():
            return None
        catalogue = yaml.safe_load(self.catalogue_path.read_text(encoding="utf-8")) or {}
        entry = (catalogue.get("collections") or {}).get(collection)
        return entry if isinstance(entry, dict) else None

    def _taxonomy_for(self, collection: str) -> Path | None:
        entry = self._catalogue_entry(collection)
        if not entry:
            return None
        tax_rel = entry.get("taxonomy_file")
        if not tax_rel:
            return None
        tax_path = self.taxonomy_root / tax_rel
        return tax_path if tax_path.is_file() else None

    @staticmethod
    def _notions(tax_path: Path) -> list[str]:
        taxo = yaml.safe_load(tax_path.read_text(encoding="utf-8")) or {}
        labels: list[str] = []
        for theme in taxo.get("themes", []):
            for notion in theme.get("notions", []):
                label = notion.get("label", "")
                if label:
                    labels.append(_norm(label))  # accents plies, cf. _norm(text)
        return labels

    @staticmethod
    def _exam_tokens(tax_path: Path | None) -> list[str]:
        """Marqueurs SPECIFIQUES a l'examen, derives UNIQUEMENT de ses
        champs d'identite (id, label, epreuve(s), matiere). Empeche qu'une
        page sur un AUTRE examen — ou un texte quelconque avec 'session' et
        'sujet' — valide la collection (revue PR #74). Les ids de THEMES
        sont exclus : niveau notionnel, pas identite d'examen — 'preparation',
        'presentation' ou 'echange' (grand_oral) valideraient n'importe
        quelle page ordinaire (revue PR #74, round 6)."""
        if tax_path is None or not tax_path.is_file():
            return []
        spec = yaml.safe_load(tax_path.read_text(encoding="utf-8")) or {}
        raw: list[str] = []
        for key in ("id", "label", "epreuve", "matiere"):
            val = spec.get(key)
            if isinstance(val, str):
                raw.append(val)
        for val in spec.get("epreuves", []) or []:
            if isinstance(val, str):
                raw.append(val)
        # Mots GENERIQUES exclus des tokens simples : presents dans tout
        # texte sur les examens ou la scolarite, ils valideraient n'importe
        # quelle page (revue PR #74, rounds 5-6). Ex: 'troisieme' (niveau)
        # issu de l'id dnb_troisieme. Les PHRASES completes sont conservees.
        stop = {"de", "du", "la", "le", "et", "en", "des", "les", "au", "aux",
                "epreuve", "epreuves", "examen", "examens", "session", "sujet",
                "baccalaureat", "general", "generale", "technologique",
                "national", "nationale", "diplome", "ecrit", "oral", "oraux",
                "troisieme", "seconde", "premiere", "terminale", "college",
                "lycee", "preparation", "presentation", "echange"}
        tokens: set[str] = set()
        for item in raw:
            norm = _norm(item.replace("_", " "))
            if len(norm) >= 3:
                tokens.add(norm)
            for word in norm.split():
                if len(word) >= 6 and word not in stop:
                    tokens.add(word)
        return sorted(tokens)

    def review(self, artefact: Artefact) -> Verdict:
        v = Verdict(reviewer=self.reviewer_id, status="approved")
        collections = artefact.manifest.get("collections_cibles") or []
        if not collections:
            v.status = "quarantine"
            v.reasons.append("aucune collection cible declaree dans le manifeste")
            v.rules_fired.append("no_target_collection")
            v.sign()
            return v

        # Perimetre complet : TOUTES les collections cibles sont evaluees,
        # pas un echantillon (exigence de couverture du perimetre qualite).
        text_norm = _norm(artefact.text)
        coverages: dict[str, float] = {}
        exam_failing: dict[str, int] = {}
        exam_checked = 0
        for collection in collections:
            entry = self._catalogue_entry(collection)
            if entry is None:
                v.status = self.missing_taxonomy_action
                v.reasons.append(f"entree catalogue introuvable pour '{collection}'")
                v.rules_fired.append("missing_taxonomy_action")
                v.sign()
                return v

            # Domaine exam : marqueurs d'examen generiques ET au moins un
            # marqueur specifique a CET examen (pas une page d'un autre examen)
            if entry.get("domain") == "exam":
                exam_checked += 1
                hits = sum(1 for m in self.exam_markers if m in text_norm)
                v.rules_fired.append(f"exam_markers[{collection}]:{hits}")
                specific = self._exam_tokens(self._taxonomy_for(collection))
                specific_hits = sum(1 for t in specific if t in text_norm)
                v.rules_fired.append(f"exam_specific[{collection}]:{specific_hits}")
                if hits < self.exam_min_markers or specific_hits == 0:
                    exam_failing[collection] = hits
                continue

            tax_path = self._taxonomy_for(collection)
            if tax_path is None:
                v.status = self.missing_taxonomy_action
                v.reasons.append(f"taxonomie introuvable pour '{collection}'")
                v.rules_fired.append("missing_taxonomy_action")
                v.sign()
                return v

            notions = self._notions(tax_path)
            if not notions:
                v.status = self.missing_taxonomy_action
                v.reasons.append(f"taxonomie vide pour '{collection}'")
                v.rules_fired.append("empty_taxonomy")
                v.sign()
                return v

            hits = sum(1 for n in notions if n in text_norm)
            coverages[collection] = hits / len(notions)
            v.rules_fired.append(f"notion_coverage[{collection}]:{coverages[collection]:.3f}")

        failing = {c: cov for c, cov in coverages.items() if cov < self.min_coverage}
        if not failing and not exam_failing:
            parts = []
            if coverages:
                worst = min(coverages.values())
                parts.append(
                    f"couverture notions conforme sur {len(coverages)}/{len(coverages)} "
                    f"collections cibles (pire cas {worst:.1%}) >= {self.min_coverage:.0%}"
                )
            if exam_checked:
                parts.append(
                    f"marqueurs d'examen presents sur {exam_checked}/{exam_checked} "
                    f"collections exam (>= {self.exam_min_markers})"
                )
            v.reasons.append(" ; ".join(parts))
        else:
            v.status = "rejected"
            if failing:
                detail = ", ".join(f"{c} {cov:.1%}" for c, cov in sorted(failing.items()))
                v.reasons.append(
                    f"couverture notions insuffisante sur {len(failing)}/{len(coverages)} "
                    f"collections cibles ({detail}) < {self.min_coverage:.0%} — "
                    "contenu hors programme presume"
                )
                v.rules_fired.append("insufficient_notion_coverage")
            if exam_failing:
                detail = ", ".join(
                    f"{c} {n} marqueur(s)" for c, n in sorted(exam_failing.items()))
                v.reasons.append(
                    f"marqueurs d'examen insuffisants sur {len(exam_failing)} collection(s) "
                    f"({detail}) < {self.exam_min_markers} — pas un contenu d'examen presume"
                )
                v.rules_fired.append("insufficient_exam_markers")
        v.sign()
        return v


class QualityExpertAgent(BaseReviewer):
    """Substance, integrite sha256, completude du manifeste."""

    reviewer_id = "quality_expert"

    def review(self, artefact: Artefact) -> Verdict:
        v = Verdict(reviewer=self.reviewer_id, status="approved")
        cfg = self.policy.get("quality_expert", {})

        words = len(artefact.text.split())
        min_w = int(cfg.get("min_words", 200))
        max_w = int(cfg.get("max_words", 200000))
        if words < min_w:
            v.status = "rejected"
            v.reasons.append(f"substance insuffisante : {words} mots < {min_w}")
            v.rules_fired.append("too_thin")
        elif words > max_w:
            v.status = "rejected"
            v.reasons.append(f"contenu anormalement volumineux : {words} mots > {max_w}")
            v.rules_fired.append("too_large")

        text_norm = _norm(artefact.text)
        for pattern in cfg.get("forbid_patterns", []):
            if pattern.lower() in text_norm:
                v.status = "quarantine"
                v.reasons.append(f"motif interdit detecte : '{pattern}'")
                v.rules_fired.append(f"forbid_pattern:{pattern}")

        missing = [f for f in cfg.get("require_manifest_fields", [])
                   if f not in artefact.manifest]
        if missing:
            v.status = "rejected" if v.status == "approved" else v.status
            v.reasons.append(f"champs manifeste manquants : {missing}")
            v.rules_fired.append("incomplete_manifest")

        if cfg.get("verify_sha256_integrity", True):
            page = artefact.staging_dir / "page.txt"
            digest = hashlib.sha256(page.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
            if digest != artefact.manifest.get("sha256"):
                v.status = "quarantine"
                v.reasons.append("integrite sha256 rompue (page.txt != manifest.sha256)")
                v.rules_fired.append("integrity_violation")
            else:
                v.rules_fired.append("integrity_ok")

        if v.status == "approved":
            v.reasons.append(f"substance {words} mots, integrite et metadonnees conformes")
        v.sign()
        return v


REVIEWER_CLASSES: dict[str, type[BaseReviewer]] = {
    "rights_expert": RightsExpertAgent,
    "subject_expert": SubjectExpertAgent,
    "quality_expert": QualityExpertAgent,
}
