"""
Dashboard RAG v2 — Streamlit
Architecture scolaire Nexus Réussite alignée sur rag_collections.yml.
Toute la navigation dérive du catalogue v2 : /catalogue/v2 et /collections/v2.
Le tableau de bord ne dépend d'aucune métrique legacy.

Ingestion : utilise exclusivement /ingest/v2/* (FE-03).
Métadonnées serveur-side : source_kind, review_status, source_label,
source_uri, doc_id, chunk_id, chunk_sha256 sont générés par le pipeline v2.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="RAG Dashboard \u2014 Nexus R\u00e9ussite",
    page_icon="\U0001f9e0",
    layout="wide",
    initial_sidebar_state="expanded",
)

_DEFAULT_API_HOST = "ingestor"
_DEFAULT_API_PORT = 8001
API_BASE = os.getenv(
    "INGEST_API_BASE",
    os.getenv("RAG_API_URL", f"http://{_DEFAULT_API_HOST}:{_DEFAULT_API_PORT}"),
)
API_TOKEN = os.getenv("INGEST_API_TOKEN", os.getenv("RAG_API_TOKEN", ""))

# Labels humains pour les niveaux, voies, statuts
NIVEAU_LABELS: dict[str, str] = {
    "troisieme": "3\u00e8me",
    "seconde": "Seconde",
    "premiere": "Premi\u00e8re",
    "terminale": "Terminale",
}
VOIE_LABELS: dict[str | None, str] = {
    "gen": "G\u00e9n\u00e9rale",
    "stmg": "STMG",
    None: "Commun",
}
STATUT_LABELS: dict[str, str] = {
    "tronc_commun": "Tronc commun",
    "specialite": "Sp\u00e9cialit\u00e9",
    "option": "Option",
    "examen": "Examen",
    "remediation": "Rem\u00e9diation",
}
DOMAIN_LABELS: dict[str, str] = {
    "education": "\u00c9ducation",
    "exam": "Examens",
    "quarantine": "Quarantaine",
    "official": "Officiel",
    "nexus_owned": "Nexus",
}

RIGHTS_OPTIONS = [
    "nexus_owned",
    "official",
    "licensed",
    "unknown",
]

TYPES_RESSOURCE = [
    "cours",
    "exercices",
    "corrig\u00e9",
    "annale",
    "fiche_revision",
    "m\u00e9thodologie",
    "sujet_bac",
    "ressource_pedagogique",
    "lien_web",
    "vid\u00e9o",
    "document_officiel",
    "autre",
]

TYPES_RESSOURCE_LABELS: dict[str, str] = {
    "cours": "Cours",
    "exercices": "Exercices",
    "corrig\u00e9": "Corrig\u00e9",
    "annale": "Annale",
    "fiche_revision": "Fiche de r\u00e9vision",
    "m\u00e9thodologie": "M\u00e9thodologie",
    "sujet_bac": "Sujet type bac",
    "ressource_pedagogique": "Ressource p\u00e9dagogique",
    "lien_web": "Lien web",
    "vid\u00e9o": "Vid\u00e9o \u00e9ducative",
    "document_officiel": "Document officiel",
    "autre": "Autre",
}


# ===============================================================
# HELPERS API
# ===============================================================

def _headers_json() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}


def _headers_upload() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def api_get(endpoint: str, timeout: float = 60.0) -> dict[str, Any] | None:
    try:
        resp = httpx.get(f"{API_BASE}{endpoint}", headers=_headers_json(), timeout=timeout)
        if resp.status_code == 200:
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Connexion API \u00e9chou\u00e9e : {exc}")
    return None


def api_post(endpoint: str, data: dict[str, Any], timeout: float = 60.0) -> dict[str, Any] | None:
    try:
        resp = httpx.post(f"{API_BASE}{endpoint}", json=data, headers=_headers_json(), timeout=timeout)
        if resp.status_code in (200, 202):
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Connexion API \u00e9chou\u00e9e : {exc}")
    return None


def api_upload_v2(
    files: list[tuple[str, bytes, str]],
    params: dict[str, str],
    timeout: float = 900.0,
) -> dict[str, Any] | None:
    """Upload fichiers vers /ingest/v2/upload-files avec query params v2."""
    try:
        multipart = [("files", (n, c, m)) for n, c, m in files]
        resp = httpx.post(
            f"{API_BASE}/ingest/v2/upload-files",
            files=multipart,
            params=params,
            headers=_headers_upload(),
            timeout=timeout,
        )
        if resp.status_code in (200, 202):
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Upload \u00e9chou\u00e9 : {exc}")
    return None


# ===============================================================
# CATALOGUE CACHE
# ===============================================================

@st.cache_data(ttl=300)
def _fetch_catalogue() -> dict[str, Any] | None:
    return api_get("/catalogue/v2")


@st.cache_data(ttl=300)
def _fetch_v2_collections() -> list[dict[str, Any]]:
    r = api_get("/collections/v2")
    if r and isinstance(r.get("collections"), list):
        cols: list[dict[str, Any]] = r["collections"]
        return cols
    return []


def _collection_label(c: dict[str, Any]) -> str:
    matiere = (c.get("matiere") or "").replace("_", " ").title()
    niveau_key = str(c.get("niveau") or "")
    voie_key = str(c.get("voie") or "")
    statut_key = str(c.get("statut") or "")
    niveau = NIVEAU_LABELS.get(niveau_key, niveau_key)
    voie = VOIE_LABELS.get(voie_key, voie_key)
    statut = STATUT_LABELS.get(statut_key, statut_key)
    parts = [p for p in (matiere, niveau, voie, statut) if p and p != "Commun"]
    return " \u2014 ".join(parts) if parts else str(c.get("name", "?"))


# ===============================================================
# COMPOSANTS INGESTION v2
# ===============================================================

def _v2_params(meta: dict[str, str]) -> dict[str, str]:
    """Construit les query params v2 depuis les m\u00e9tadonn\u00e9es UI."""
    return {
        "collection": meta["collection"],
        "rights": meta["rights"],
        "matiere": meta["matiere"],
        "niveau": meta["niveau"],
        "voie": meta.get("voie") or "gen",
        "type_doc": meta.get("type_doc") or "cours",
    }


def _render_upload_tab(metadata: dict[str, str], key_prefix: str) -> None:
    st.markdown("**Formats** : PDF, DOCX, Markdown, TXT, HTML, Jupyter Notebook")
    uploaded = st.file_uploader(
        "Glissez-d\u00e9posez vos fichiers",
        type=["pdf", "docx", "doc", "md", "txt", "csv", "html", "htm", "ipynb", "tex"],
        accept_multiple_files=True,
        key=f"{key_prefix}_files",
    )
    if uploaded:
        st.info(f"{len(uploaded)} fichier(s) s\u00e9lectionn\u00e9(s)")
        rows = [{"Nom": f.name, "Taille": f"{f.size / 1024:.1f} Ko", "Type": f.type or "?"} for f in uploaded]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if st.button("Ing\u00e9rer les fichiers", key=f"{key_prefix}_btn"):
            total_written = 0
            total_errors = 0
            progress_bar = st.progress(0, text="Pr\u00e9paration\u2026")
            params = _v2_params(metadata)
            for idx, f in enumerate(uploaded):
                progress_bar.progress((idx + 1) / len(uploaded), text=f"Fichier {idx + 1}/{len(uploaded)}")
                payload = [(f.name, f.read(), f.type or "application/octet-stream")]
                result = api_upload_v2(payload, params=params, timeout=300.0)
                if result:
                    for r in result.get("results", []):
                        total_written += r.get("chunks_written", 0)
                else:
                    total_errors += 1
            progress_bar.progress(1.0, text="Termin\u00e9 !")
            if total_written > 0:
                st.success(f"{total_written} chunk(s) ajout\u00e9(s) (review_status=needs_review)")
            if total_errors > 0:
                st.error(f"{total_errors} erreur(s)")
            if total_written == 0 and total_errors == 0:
                st.info("Aucun chunk \u00e9ligible.")


def _render_urls_tab(metadata: dict[str, str], key_prefix: str) -> None:
    st.markdown("Une URL par ligne.")
    urls_text = st.text_area("URLs", height=180, placeholder="https://\u2026", key=f"{key_prefix}_urls")
    if urls_text.strip():
        urls = [u.strip() for u in urls_text.strip().splitlines() if u.strip()]
        st.info(f"{len(urls)} URL(s)")
        if st.button("Ing\u00e9rer les URLs", key=f"{key_prefix}_go"):
            total_written = 0
            total_errors = 0
            progress_bar = st.progress(0, text="Pr\u00e9paration\u2026")
            v2_payload = {
                "urls": urls,
                "collection": metadata["collection"],
                "rights": metadata["rights"],
                "matiere": metadata["matiere"],
                "niveau": metadata["niveau"],
                "voie": metadata.get("voie") or "gen",
                "type_doc": metadata.get("type_doc") or "cours",
            }
            result = api_post("/ingest/v2/urls", v2_payload, timeout=300.0)
            progress_bar.progress(1.0, text="Termin\u00e9 !")
            if result:
                for r in result.get("results", []):
                    total_written += r.get("chunks_written", 0)
                    if r.get("error"):
                        total_errors += 1
            else:
                total_errors = len(urls)
            if total_written > 0:
                st.success(f"{total_written} chunk(s) ajout\u00e9(s) (review_status=needs_review)")
            if total_errors > 0:
                st.error(f"{total_errors} erreur(s)")
            if total_written == 0 and total_errors == 0:
                st.info("Aucun chunk \u00e9ligible.")


def _render_drive_tab(metadata: dict[str, str], key_prefix: str) -> None:
    st.markdown(
        "**Drive v2 non activ\u00e9** : l\u2019ingestion Google Drive n\u00e9cessite un service "
        "account configur\u00e9 sur le serveur. Utilisez Upload fichiers ou URLs en attendant."
    )
    folder_id = st.text_input("ID du dossier Drive (informatif)", key=f"{key_prefix}_drive", disabled=True)
    if folder_id:
        pass


# ===============================================================
# SIDEBAR NAVIGATION
# ===============================================================

st.sidebar.markdown("# \U0001f9e0")
st.sidebar.title("RAG Nexus R\u00e9ussite")

page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Recherche",
        "Ingestion",
        "Administration",
    ],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.success("API connect\u00e9e")
st.sidebar.caption("Backend RAG v2")


# ===============================================================
# PAGE DASHBOARD
# ===============================================================
if page == "Dashboard":
    st.title("Dashboard RAG v2")
    st.caption("Catalogue scolaire Nexus R\u00e9ussite")

    catalogue = _fetch_catalogue()
    if not catalogue:
        st.warning("Impossible de charger le catalogue. V\u00e9rifiez la connexion API.")
    else:
        collections = catalogue.get("collections", [])
        by_level = catalogue.get("by_level", {})
        by_domain = catalogue.get("by_domain", {})
        by_status = catalogue.get("by_status", {})

        total = len(collections)
        n_instanciees = sum(1 for c in collections if c.get("instanciee"))
        n_retrievable = sum(1 for c in collections if c.get("retrievable"))
        n_non_instanciees = total - n_instanciees
        n_quarantaine = sum(1 for c in collections if c.get("domain") == "quarantine")

        st.subheader("Indicateurs du catalogue")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("D\u00e9clar\u00e9es", total)
        m2.metric("Instanci\u00e9es", n_instanciees)
        m3.metric("Retrievable", n_retrievable)
        m4.metric("Non instanci\u00e9es", n_non_instanciees)
        m5.metric("Quarantaine", n_quarantaine)

        st.markdown("---")

        # R\u00e9partition par niveau
        st.subheader("Par niveau")
        level_cols = st.columns(len(by_level))
        for i, (level, names) in enumerate(sorted(by_level.items())):
            label = NIVEAU_LABELS.get(level, level.title())
            level_cols[i % len(level_cols)].metric(label, len(names))

        # R\u00e9partition par voie
        st.subheader("Par voie")
        voie_counts: dict[str, int] = {}
        for c in collections:
            v = c.get("voie") or "commun"
            voie_counts[v] = voie_counts.get(v, 0) + 1
        voie_cols = st.columns(len(voie_counts))
        for i, (voie, count) in enumerate(sorted(voie_counts.items())):
            label = VOIE_LABELS.get(voie, voie.title()) if voie != "commun" else "Commun"
            voie_cols[i].metric(label, count)

        # R\u00e9partition par statut
        st.subheader("Par statut")
        statut_cols = st.columns(len(by_status))
        for i, (statut, names) in enumerate(sorted(by_status.items())):
            label = STATUT_LABELS.get(statut, statut.title())
            statut_cols[i % len(statut_cols)].metric(label, len(names))

        st.markdown("---")

        # Filtres
        st.subheader("Catalogue complet")
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            f_niveau = st.selectbox("Niveau", ["Tous"] + list(by_level.keys()))
        with fc2:
            all_voies = sorted({c.get("voie") or "commun" for c in collections})
            f_voie = st.selectbox("Voie", ["Tous"] + all_voies)
        with fc3:
            all_matieres = sorted({c.get("matiere") or "" for c in collections if c.get("matiere")})
            f_matiere = st.selectbox("Mati\u00e8re", ["Toutes"] + all_matieres)
        with fc4:
            f_inst = st.selectbox("Instanci\u00e9e", ["Toutes", "Oui", "Non"])

        # Apply filters
        filtered = collections
        if f_niveau != "Tous":
            filtered = [c for c in filtered if c.get("niveau") == f_niveau]
        if f_voie != "Tous":
            filtered = [c for c in filtered if (c.get("voie") or "commun") == f_voie]
        if f_matiere != "Toutes":
            filtered = [c for c in filtered if c.get("matiere") == f_matiere]
        if f_inst == "Oui":
            filtered = [c for c in filtered if c.get("instanciee")]
        elif f_inst == "Non":
            filtered = [c for c in filtered if not c.get("instanciee")]

        st.subheader("Tableau du catalogue")
        if filtered:
            rows = []
            for c in filtered:
                badge = ""
                if c.get("domain") == "quarantine":
                    badge = "Quarantaine"
                elif c.get("retrievable"):
                    badge = "Active recherche"
                elif c.get("instanciee"):
                    badge = "Instanci\u00e9e"
                else:
                    badge = "D\u00e9clar\u00e9e non instanci\u00e9e"

                c_niveau = str(c.get("niveau") or "-")
                c_voie = c.get("voie")
                c_statut = str(c.get("statut") or "-")
                rows.append({
                    "Collection": c["name"],
                    "Mati\u00e8re": (c.get("matiere") or "").replace("_", " ").title(),
                    "Niveau": NIVEAU_LABELS.get(c_niveau, c_niveau),
                    "Voie": VOIE_LABELS.get(c_voie, c_voie or "-"),
                    "Statut": STATUT_LABELS.get(c_statut, c_statut),
                    "Badge": badge,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Aucune collection ne correspond aux filtres.")

    # Sant\u00e9 API
    st.markdown("---")
    health = api_get("/health")
    if health:
        st.success("API op\u00e9rationnelle")
    else:
        st.error("API non joignable")


# ===============================================================
# PAGE RECHERCHE
# ===============================================================
elif page == "Recherche":
    st.title("Recherche RAG v2")
    st.info("Seules les collections instanci\u00e9es et interrogeables (retrievable) sont propos\u00e9es.")

    v2_collections = _fetch_v2_collections()
    if not v2_collections:
        st.warning("Aucune collection v2 retrievable. V\u00e9rifiez la configuration.")
    else:
        col_labels = {_collection_label(c): c["name"] for c in v2_collections}
        options = list(col_labels.keys()) + (["Toutes"] if len(col_labels) > 1 else [])

        st.subheader("Collection cible")
        selected = st.radio("Collection", options, horizontal=True)

        query = st.text_input("Question", placeholder="Qu\u2019est-ce qu\u2019un arbre binaire ?")
        k = st.slider("Nombre de r\u00e9sultats", 1, 20, 5)

        if query and st.button("Rechercher"):
            with st.spinner("Recherche v2 en cours\u2026"):
                if selected == "Toutes":
                    all_hits: list[dict[str, Any]] = []
                    for col_name in col_labels.values():
                        r = api_post("/search/v2", {"q": query, "collection": col_name, "k": k}, timeout=120.0)
                        if r and r.get("hits"):
                            for h in r["hits"]:
                                h["_collection"] = col_name
                            all_hits.extend(r["hits"])
                    deduped: dict[str, dict[str, Any]] = {}
                    for hit in all_hits:
                        cid = hit.get("chunk_id", "")
                        if cid not in deduped or hit.get("rerank_score", 0) > deduped[cid].get("rerank_score", 0):
                            deduped[cid] = hit
                    merged = sorted(deduped.values(), key=lambda h: h.get("rerank_score", 0), reverse=True)[:k]
                    result: dict[str, Any] | None = {
                        "hits": merged,
                        "collection": "toutes",
                        "returned": len(merged),
                    }
                else:
                    target_col = col_labels[selected]
                    result = api_post("/search/v2", {"q": query, "collection": target_col, "k": k}, timeout=120.0)

            if result:
                hits = result.get("hits", [])
                seuil = result.get("seuil", "")
                st.info(
                    f"{len(hits)} r\u00e9sultat(s) dans `{result.get('collection', '?')}` "
                    f"(seuil rerank : {seuil})"
                )
                gen_allowed = result.get("answer_generation_allowed", False)
                if gen_allowed is False:
                    st.caption("Retrieval seul \u2014 answer_generation_allowed = false")

                for i, h in enumerate(hits):
                    h_col = h.pop("_collection", None)
                    rerank_score = h.get("rerank_score", 0)
                    source_label = h.get("source_label", "Sans titre")
                    col_tag = f" | {h_col}" if h_col else ""
                    with st.expander(f"#{i+1} \u2014 {source_label} (rerank: {rerank_score:+.2f}{col_tag})"):
                        preview = h.get("preview", "")
                        if preview:
                            st.markdown(preview)
                        st.markdown(
                            f"**Source** : `{source_label}`  \n"
                            f"**Droits** : `{h.get('rights', '')}`  \n"
                            f"**Type** : `{h.get('type_doc', '')}`  \n"
                            f"**doc_id** : `{h.get('doc_id', '')}`  \n"
                            f"**chunk_id** : `{h.get('chunk_id', '')}`"
                        )


# ===============================================================
# PAGE INGESTION
# ===============================================================
elif page == "Ingestion":
    st.title("Ingestion RAG v2")
    st.markdown(
        "Ing\u00e9rez des ressources dans les collections v2 instanci\u00e9es. "
        "Les collections non instanci\u00e9es sont d\u00e9clar\u00e9es mais pas encore activ\u00e9es."
    )
    st.caption(
        "M\u00e9tadonn\u00e9es g\u00e9n\u00e9r\u00e9es c\u00f4t\u00e9 serveur : "
        "source_kind, review_status (needs_review), source_label, source_uri, "
        "doc_id, chunk_id, chunk_sha256."
    )
    st.info("Les documents ing\u00e9r\u00e9s sont plac\u00e9s en needs_review avant leur validation.")

    catalogue = _fetch_catalogue()
    if not catalogue:
        st.warning("Impossible de charger le catalogue.")
    else:
        collections = catalogue.get("collections", [])
        ingestion_targets = [c for c in collections if c.get("ingestion_enabled")]
        ingest_non_inst = [c for c in collections if not c.get("instanciee")]

        if not ingestion_targets:
            st.warning("Aucune collection instanci\u00e9e disponible pour l\u2019ingestion.")
        else:
            st.subheader("Param\u00e8tres de la ressource")
            target_labels = {_collection_label(c): c["name"] for c in ingestion_targets}
            selected_label = st.selectbox("Collection cible", list(target_labels.keys()))
            selected_name = target_labels[selected_label]

            # Find selected collection info
            selected_col: dict[str, Any] = next(
                (c for c in ingestion_targets if c["name"] == selected_name), {}
            )

            sel_niveau = str(selected_col.get("niveau") or "-")
            st.info(
                f"**Collection** : `{selected_name}`  \n"
                f"**Domaine** : {DOMAIN_LABELS.get(selected_col.get('domain', ''), selected_col.get('domain', '?'))}  \n"
                f"**Niveau** : {NIVEAU_LABELS.get(sel_niveau, sel_niveau)}  \n"
                f"**Mati\u00e8re** : {(selected_col.get('matiere') or '-').replace('_', ' ').title()}"
            )

            col_t = st.columns(3)
            with col_t[0]:
                type_doc = st.selectbox(
                    "Type de document",
                    TYPES_RESSOURCE,
                    format_func=lambda x: TYPES_RESSOURCE_LABELS.get(x, x),
                )
            with col_t[1]:
                rights = st.selectbox("Droits", RIGHTS_OPTIONS)
            with col_t[2]:
                tag = st.text_input("Tag libre (optionnel)", placeholder="ex : suites, probabilit\u00e9s\u2026")

            st.markdown("---")

            ingest_meta: dict[str, str] = {
                "collection": selected_name,
                "rights": rights,
                "matiere": selected_col.get("matiere") or "",
                "niveau": selected_col.get("niveau") or "",
                "voie": selected_col.get("voie") or "gen",
                "domain": selected_col.get("domain") or "",
                "type_doc": type_doc,
            }
            if tag.strip():
                ingest_meta["tag"] = tag.strip()

            tab_up, tab_url, tab_drv = st.tabs([
                "Upload fichiers",
                "URLs",
                "Google Drive",
            ])
            with tab_up:
                _render_upload_tab(ingest_meta, "ingest")
            with tab_url:
                _render_urls_tab(ingest_meta, "ingest")
            with tab_drv:
                _render_drive_tab(ingest_meta, "ingest")

        # Show non-instanci\u00e9es
        if ingest_non_inst:
            st.markdown("---")
            with st.expander(
                f"Collections d\u00e9clar\u00e9es non instanci\u00e9es ({len(ingest_non_inst)})"
            ):
                for c in ingest_non_inst:
                    c_niv = str(c.get("niveau") or "?")
                    c_stat = str(c.get("statut") or "?")
                    st.caption(
                        f"`{c['name']}` \u2014 "
                        f"{(c.get('matiere') or '?').replace('_', ' ').title()} / "
                        f"{NIVEAU_LABELS.get(c_niv, c_niv)} / "
                        f"{STATUT_LABELS.get(c_stat, c_stat)}"
                    )


# ===============================================================
# PAGE ADMINISTRATION
# ===============================================================
elif page == "Administration":
    st.title("Administration RAG v2")
    st.caption("Vue de gouvernance des collections et de leur coh\u00e9rence.")

    # Sant\u00e9 API
    st.subheader("Sant\u00e9 du service")
    health = api_get("/health")
    if health:
        st.success(f"API op\u00e9rationnelle \u2014 statut : {health.get('status', '?')}")
    else:
        st.error("API non joignable")

    catalogue = _fetch_catalogue()
    if not catalogue:
        st.warning("Impossible de charger le catalogue.")
    else:
        collections = catalogue.get("collections", [])

        # Catalogue v2 complet
        st.subheader("Catalogue v2 complet")
        st.write(f"**{len(collections)}** collections d\u00e9clar\u00e9es")

        admin_inst = [c for c in collections if c.get("instanciee")]
        admin_non_inst = [c for c in collections if not c.get("instanciee")]
        admin_retrievable = [c for c in collections if c.get("retrievable")]
        admin_quarantine = [c for c in collections if c.get("domain") == "quarantine"]

        # Collections instanci\u00e9es
        st.subheader(f"Collections instanci\u00e9es ({len(admin_inst)})")
        for c in admin_inst:
            badge = "Retrievable" if c.get("retrievable") else "Non retrievable"
            st.write(f"- `{c['name']}` \u2014 {badge}")

        # Collections non instanci\u00e9es
        st.subheader(f"Collections d\u00e9clar\u00e9es non instanci\u00e9es ({len(admin_non_inst)})")
        with st.expander("Voir les collections non instanci\u00e9es"):
            for c in admin_non_inst:
                c_niv = str(c.get("niveau") or "?")
                st.write(
                    f"- `{c['name']}` \u2014 "
                    f"{(c.get('matiere') or '?').replace('_', ' ').title()} / "
                    f"{NIVEAU_LABELS.get(c_niv, c_niv)}"
                )

        # Collections retrievable
        st.subheader(f"Collections retrievable ({len(admin_retrievable)})")
        for c in admin_retrievable:
            st.write(f"- `{c['name']}`")

        # Quarantaine
        st.subheader(f"Quarantaine ({len(admin_quarantine)})")
        for c in admin_quarantine:
            st.write(
                f"- `{c['name']}` \u2014 "
                f"instanci\u00e9e={c.get('instanciee')}, retrievable={c.get('retrievable')}"
            )

        # Contr\u00f4les de coh\u00e9rence
        st.subheader("Contr\u00f4les de coh\u00e9rence")
        issues: list[str] = []

        for c in collections:
            name = c["name"]
            if c.get("domain") == "quarantine":
                continue

            if c.get("instanciee") and not c.get("retrievable"):
                issues.append(f"`{name}` : instanci\u00e9e mais non retrievable")

            if c.get("retrievable") and not c.get("instanciee"):
                issues.append(f"`{name}` : retrievable mais pas instanci\u00e9e (incoh\u00e9rent)")

            tf = c.get("taxonomy_file")
            if not tf:
                issues.append(f"`{name}` : pas de taxonomy_file d\u00e9clar\u00e9")

            if not c.get("taxonomy_exists", True):
                issues.append(f"`{name}` : taxonomy_file d\u00e9clar\u00e9 mais fichier absent")

            domain = c.get("domain")
            if domain and domain not in DOMAIN_LABELS:
                issues.append(f"`{name}` : domaine inconnu \u00ab {domain} \u00bb")

            ci = c.get("coherence_issues")
            if ci and isinstance(ci, list):
                for issue in ci:
                    issues.append(f"`{name}` : {issue}")

        if issues:
            for issue in issues:
                st.warning(issue)
        else:
            st.success("Aucun probl\u00e8me de coh\u00e9rence d\u00e9tect\u00e9.")
