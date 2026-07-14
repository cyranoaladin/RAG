"""
Dashboard RAG v2 — Streamlit
Architecture scolaire Nexus Reussite alignee sur rag_collections.yml.
Toute la navigation derive du catalogue v2 : /catalogue/v2 et /collections/v2.
Aucune collection legacy. Aucun appel /stats.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="RAG Dashboard — Nexus Reussite",
    page_icon="\U0001f9e0",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = os.getenv("INGEST_API_BASE", os.getenv("RAG_API_URL", "http://ingestor:8001"))
API_TOKEN = os.getenv("INGEST_API_TOKEN", os.getenv("RAG_API_TOKEN", ""))

# Labels humains pour les niveaux, voies, statuts
NIVEAU_LABELS = {
    "troisieme": "3e",
    "seconde": "Seconde",
    "premiere": "Premiere",
    "terminale": "Terminale",
}
VOIE_LABELS = {
    "gen": "Generale",
    "stmg": "STMG",
    None: "Commun",
}
STATUT_LABELS = {
    "tronc_commun": "Tronc commun",
    "specialite": "Specialite",
    "option": "Option",
    "examen": "Examen",
    "remediation": "Remediation",
}
DOMAIN_LABELS = {
    "education": "Education",
    "exam": "Examens",
    "quarantine": "Quarantaine",
    "official": "Officiel",
    "nexus_owned": "Nexus",
}

TYPES_RESSOURCE = [
    "Cours",
    "Exercices",
    "Corrige",
    "Annale",
    "Fiche de revision",
    "Methodologie",
    "Sujet type bac",
    "Ressource pedagogique",
    "Lien web",
    "Video educative",
    "Document officiel",
    "Autre",
]


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
        st.error(f"Connexion API echouee: {exc}")
    return None


def api_post(endpoint: str, data: dict[str, Any], timeout: float = 60.0) -> dict[str, Any] | None:
    try:
        resp = httpx.post(f"{API_BASE}{endpoint}", json=data, headers=_headers_json(), timeout=timeout)
        if resp.status_code in (200, 202):
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Connexion API echouee: {exc}")
    return None


def api_upload(
    endpoint: str,
    files: list[tuple[str, bytes, str]],
    params: dict[str, str] | None = None,
    timeout: float = 900.0,
) -> dict[str, Any] | None:
    try:
        multipart = [("files", (n, c, m)) for n, c, m in files]
        resp = httpx.post(
            f"{API_BASE}{endpoint}", files=multipart,
            params=params or {}, headers=_headers_upload(), timeout=timeout,
        )
        if resp.status_code in (200, 202):
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Upload echoue: {exc}")
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
    return " — ".join(parts) if parts else str(c.get("name", "?"))


# ===============================================================
# COMPOSANTS REUTILISABLES
# ===============================================================

def _render_upload_tab(metadata: dict[str, str], key_prefix: str) -> None:
    st.markdown("**Formats** : PDF, DOCX, Markdown, TXT, HTML")
    uploaded = st.file_uploader(
        "Glissez-deposez vos fichiers",
        type=["pdf", "docx", "doc", "md", "txt", "csv", "html", "htm"],
        accept_multiple_files=True,
        key=f"{key_prefix}_files",
    )
    if uploaded:
        st.info(f"{len(uploaded)} fichier(s) selectionne(s)")
        rows = [{"Nom": f.name, "Taille": f"{f.size / 1024:.1f} Ko", "Type": f.type or "?"} for f in uploaded]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if st.button("Ingerer les fichiers", key=f"{key_prefix}_btn"):
            total_added = 0
            total_errors = 0
            progress_bar = st.progress(0, text="Preparation...")
            for idx, f in enumerate(uploaded):
                progress_bar.progress((idx + 1) / len(uploaded), text=f"Fichier {idx + 1}/{len(uploaded)}")
                payload = [(f.name, f.read(), f.type or "application/octet-stream")]
                result = api_upload("/ingest/upload-files", payload, params={"metadata": json.dumps(metadata)}, timeout=300.0)
                if result:
                    total_added += int(result.get("total_added", 0) or 0)
                else:
                    total_errors += 1
            progress_bar.progress(1.0, text="Termine !")
            if total_added > 0:
                st.success(f"{total_added} chunk(s) ajoute(s)")
            if total_errors > 0:
                st.error(f"{total_errors} erreur(s)")


def _render_urls_tab(metadata: dict[str, str], key_prefix: str) -> None:
    st.markdown("Une URL par ligne.")
    urls_text = st.text_area("URLs", height=180, placeholder="https://...", key=f"{key_prefix}_urls")
    if urls_text.strip():
        urls = [u.strip() for u in urls_text.strip().splitlines() if u.strip()]
        st.info(f"{len(urls)} URL(s)")
        if st.button("Ingerer les URLs", key=f"{key_prefix}_go"):
            total_added = 0
            total_errors = 0
            progress_bar = st.progress(0, text="Preparation...")
            for idx, url in enumerate(urls):
                progress_bar.progress((idx + 1) / len(urls), text=f"URL {idx + 1}/{len(urls)}")
                result = api_post("/ingest/urls", {"urls": [url], "metadata": metadata}, timeout=120.0)
                if result:
                    total_added += result.get("total_added", 0)
                else:
                    total_errors += 1
            progress_bar.progress(1.0, text="Termine !")
            if total_added > 0:
                st.success(f"{total_added} chunk(s) ajoute(s)")
            if total_errors > 0:
                st.error(f"{total_errors} erreur(s)")


def _render_drive_tab(metadata: dict[str, str], key_prefix: str) -> None:
    st.markdown("Entrez l'ID du dossier Google Drive.")
    folder_id = st.text_input("ID du dossier Drive", key=f"{key_prefix}_drive")
    if folder_id.strip() and st.button("Lancer l'ingestion Drive", key=f"{key_prefix}_drv_btn"):
        result = api_post("/ingest/drive", {"folder_id": folder_id.strip(), "metadata": metadata}, timeout=30.0)
        if not result or "task_id" not in result:
            st.error(f"Erreur lors du lancement : {result}")
            return
        task_id = result["task_id"]
        status_text = st.empty()
        progress_bar = st.progress(0)
        while True:
            time.sleep(2)
            status_resp = api_get(f"/ingest/drive/status/{task_id}", timeout=10.0)
            if not status_resp:
                status_text.warning("En attente de reponse...")
                continue
            task_status = status_resp.get("status", "pending")
            progress_bar.progress(min(status_resp.get("progress_pct", 0), 100))
            status_text.markdown(f"**{task_status}**")
            if task_status in ("done", "error"):
                if task_status == "done":
                    st.success(f"Ingestion terminee — {status_resp.get('added_chunks', 0)} chunks")
                else:
                    st.error(f"Erreur: {status_resp.get('error_message', '?')}")
                break


# ===============================================================
# SIDEBAR NAVIGATION
# ===============================================================

st.sidebar.markdown("# \U0001f9e0")
st.sidebar.title("RAG Nexus Reussite")

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
st.sidebar.caption(f"API : `{API_BASE}`")


# ===============================================================
# PAGE DASHBOARD
# ===============================================================
if page == "Dashboard":
    st.title("Dashboard RAG v2 — Catalogue scolaire")

    catalogue = _fetch_catalogue()
    if not catalogue:
        st.warning("Impossible de charger le catalogue. Verifiez la connexion API.")
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

        # Metriques globales
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Declarees", total)
        m2.metric("Instanciees", n_instanciees)
        m3.metric("Retrievable", n_retrievable)
        m4.metric("Non instanciees", n_non_instanciees)
        m5.metric("Quarantaine", n_quarantaine)

        st.markdown("---")

        # Repartition par niveau
        st.subheader("Par niveau")
        level_cols = st.columns(len(by_level))
        for i, (level, names) in enumerate(sorted(by_level.items())):
            label = NIVEAU_LABELS.get(level, level.title())
            level_cols[i % len(level_cols)].metric(label, len(names))

        # Repartition par voie
        st.subheader("Par voie")
        voie_counts: dict[str, int] = {}
        for c in collections:
            v = c.get("voie") or "commun"
            voie_counts[v] = voie_counts.get(v, 0) + 1
        voie_cols = st.columns(len(voie_counts))
        for i, (voie, count) in enumerate(sorted(voie_counts.items())):
            label = VOIE_LABELS.get(voie, voie.title()) if voie != "commun" else "Commun"
            voie_cols[i].metric(label, count)

        # Repartition par statut
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
            f_matiere = st.selectbox("Matiere", ["Toutes"] + all_matieres)
        with fc4:
            f_inst = st.selectbox("Instanciee", ["Toutes", "Oui", "Non"])

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

        # Table
        if filtered:
            rows = []
            for c in filtered:
                badge = ""
                if c.get("domain") == "quarantine":
                    badge = "Quarantaine"
                elif c.get("retrievable"):
                    badge = "Active recherche"
                elif c.get("instanciee"):
                    badge = "Instanciee"
                else:
                    badge = "Declaree non instanciee"

                rows.append({
                    "Collection": c["name"],
                    "Matiere": (c.get("matiere") or "").replace("_", " ").title(),
                    "Niveau": NIVEAU_LABELS.get(c.get("niveau"), c.get("niveau") or "-"),
                    "Voie": VOIE_LABELS.get(c.get("voie"), c.get("voie") or "-"),
                    "Statut": STATUT_LABELS.get(c.get("statut"), c.get("statut") or "-"),
                    "Badge": badge,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Aucune collection ne correspond aux filtres.")

    # Sante API
    st.markdown("---")
    health = api_get("/health")
    if health:
        st.success("API operationnelle")
    else:
        st.error("API non joignable")


# ===============================================================
# PAGE RECHERCHE
# ===============================================================
elif page == "Recherche":
    st.title("Recherche RAG v2")

    v2_collections = _fetch_v2_collections()
    if not v2_collections:
        st.warning("Aucune collection v2 retrievable. Verifiez la configuration.")
    else:
        col_labels = {_collection_label(c): c["name"] for c in v2_collections}
        options = list(col_labels.keys()) + (["Toutes"] if len(col_labels) > 1 else [])

        # Parcours scolaire
        st.subheader("Collection cible")
        selected = st.radio("Collection", options, horizontal=True)

        query = st.text_input("Question", placeholder="Qu'est-ce qu'un arbre binaire ?")
        k = st.slider("Nombre de resultats", 1, 20, 5)

        if query and st.button("Rechercher"):
            with st.spinner("Recherche v2 en cours..."):
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
                    f"{len(hits)} resultat(s) dans `{result.get('collection', '?')}` "
                    f"(seuil rerank: {seuil})"
                )
                gen_allowed = result.get("answer_generation_allowed", False)
                if gen_allowed is False:
                    st.caption("Retrieval seul — answer_generation_allowed = false")

                for i, h in enumerate(hits):
                    h_col = h.pop("_collection", None)
                    rerank_score = h.get("rerank_score", 0)
                    source_label = h.get("source_label", "Sans titre")
                    col_tag = f" | {h_col}" if h_col else ""
                    with st.expander(f"#{i+1} — {source_label} (rerank: {rerank_score:+.2f}{col_tag})"):
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
        "Ingerez des ressources dans les collections v2 instanciees. "
        "Les collections non instanciees sont declarees mais pas encore activees."
    )

    catalogue = _fetch_catalogue()
    if not catalogue:
        st.warning("Impossible de charger le catalogue.")
    else:
        collections = catalogue.get("collections", [])
        ingestion_targets = [c for c in collections if c.get("ingestion_enabled")]
        ingest_non_inst = [c for c in collections if not c.get("instanciee")]

        if not ingestion_targets:
            st.warning("Aucune collection instanciee disponible pour l'ingestion.")
        else:
            # Collection selector
            target_labels = {_collection_label(c): c["name"] for c in ingestion_targets}
            selected_label = st.selectbox("Collection cible", list(target_labels.keys()))
            selected_name = target_labels[selected_label]

            # Find selected collection info
            selected_col: dict[str, Any] = next((c for c in ingestion_targets if c["name"] == selected_name), {})

            sel_niveau = str(selected_col.get("niveau") or "-")
            st.info(
                f"**Collection** : `{selected_name}`  \n"
                f"**Domaine** : {selected_col.get('domain', '?')}  \n"
                f"**Niveau** : {NIVEAU_LABELS.get(sel_niveau, sel_niveau)}  \n"
                f"**Matiere** : {(selected_col.get('matiere') or '-').replace('_', ' ').title()}"
            )

            col_t = st.columns(2)
            with col_t[0]:
                type_ressource = st.selectbox("Type de ressource", TYPES_RESSOURCE)
            with col_t[1]:
                tag = st.text_input("Tag libre (optionnel)", placeholder="ex: suites, probabilites...")

            st.markdown("---")

            ingest_meta: dict[str, str] = {
                "collection": selected_name,
                "matiere": selected_col.get("matiere") or "",
                "niveau": selected_col.get("niveau") or "",
                "voie": selected_col.get("voie") or "",
                "domain": selected_col.get("domain") or "",
                "type_ressource": type_ressource,
            }
            if tag.strip():
                ingest_meta["tag"] = tag.strip()

            tab_up, tab_url, tab_drv = st.tabs(["Upload fichiers", "URLs", "Google Drive"])
            with tab_up:
                _render_upload_tab(ingest_meta, "ingest")
            with tab_url:
                _render_urls_tab(ingest_meta, "ingest")
            with tab_drv:
                _render_drive_tab(ingest_meta, "ingest")

        # Show non-instanciees
        if ingest_non_inst:
            st.markdown("---")
            with st.expander(f"Collections declarees non instanciees ({len(ingest_non_inst)})"):
                for c in ingest_non_inst:
                    st.caption(
                        f"`{c['name']}` — "
                        f"{(c.get('matiere') or '?').replace('_', ' ').title()} / "
                        f"{NIVEAU_LABELS.get(c.get('niveau'), c.get('niveau') or '?')} / "
                        f"{STATUT_LABELS.get(c.get('statut'), c.get('statut') or '?')}"
                    )


# ===============================================================
# PAGE ADMINISTRATION
# ===============================================================
elif page == "Administration":
    st.title("Administration RAG v2")

    # Sante API
    st.subheader("Sante du service")
    health = api_get("/health")
    if health:
        st.success(f"API operationnelle — statut : {health.get('status', '?')}")
    else:
        st.error("API non joignable")

    catalogue = _fetch_catalogue()
    if not catalogue:
        st.warning("Impossible de charger le catalogue.")
    else:
        collections = catalogue.get("collections", [])

        # Catalogue v2 complet
        st.subheader("Catalogue v2 complet")
        st.write(f"**{len(collections)}** collections declarees")

        admin_inst = [c for c in collections if c.get("instanciee")]
        admin_non_inst = [c for c in collections if not c.get("instanciee")]
        admin_retrievable = [c for c in collections if c.get("retrievable")]
        admin_quarantine = [c for c in collections if c.get("domain") == "quarantine"]

        # Collections instanciees
        st.subheader(f"Collections instanciees ({len(admin_inst)})")
        for c in admin_inst:
            badge = "Retrievable" if c.get("retrievable") else "Non retrievable"
            st.write(f"- `{c['name']}` — {badge}")

        # Collections non instanciees
        st.subheader(f"Collections declarees non instanciees ({len(admin_non_inst)})")
        with st.expander("Voir les collections non instanciees"):
            for c in admin_non_inst:
                st.write(
                    f"- `{c['name']}` — "
                    f"{(c.get('matiere') or '?').replace('_', ' ').title()} / "
                    f"{NIVEAU_LABELS.get(c.get('niveau'), c.get('niveau') or '?')}"
                )

        # Collections retrievable
        st.subheader(f"Collections retrievable ({len(admin_retrievable)})")
        for c in admin_retrievable:
            st.write(f"- `{c['name']}`")

        # Quarantaine
        st.subheader(f"Quarantaine ({len(admin_quarantine)})")
        for c in admin_quarantine:
            st.write(f"- `{c['name']}` — instanciee={c.get('instanciee')}, retrievable={c.get('retrievable')}")

        # Controles de coherence
        st.subheader("Controles de coherence")
        issues = []

        for c in collections:
            name = c["name"]
            if c.get("domain") == "quarantine":
                continue

            # Collection instanciee mais non retrievable
            if c.get("instanciee") and not c.get("retrievable"):
                issues.append(f"`{name}` : instanciee mais non retrievable")

            # Retrievable mais pas instanciee (should be impossible)
            if c.get("retrievable") and not c.get("instanciee"):
                issues.append(f"`{name}` : retrievable mais pas instanciee (incoherent)")

            # Taxonomy file absent
            tf = c.get("taxonomy_file")
            if not tf:
                issues.append(f"`{name}` : pas de taxonomy_file declare")

            # Domain unknown
            domain = c.get("domain")
            if domain and domain not in DOMAIN_LABELS:
                issues.append(f"`{name}` : domaine inconnu '{domain}'")

        if issues:
            for issue in issues:
                st.warning(issue)
        else:
            st.success("Aucun probleme de coherence detecte.")
