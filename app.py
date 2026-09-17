import streamlit as st

# set_page_config doit precede TOUT autre appel Streamlit, y compris
# st.markdown : sinon Streamlit leve StreamlitSetPageConfigMustBeFirstCommand.
st.set_page_config(
    page_title="Comparateur FCS / Excel",
    page_icon="📊",
    layout="wide",
)

from src.pipeline import run_analysis
from src.comparator import (
    is_ok_status,
    STATUS_EXCEL_ONLY,
    STATUS_FCS_ONLY,
)

st.markdown(
    """
    <style>
    .main-title { font-size: 42px; font-weight: 800; color: #12355B; margin-bottom: 0px; }
    .subtitle { font-size: 18px; color: #555; margin-bottom: 30px; }
    .success-card { background-color: #EAF7EA; padding: 18px; border-radius: 12px;
                    border-left: 6px solid #2E7D32; margin-top: 20px; }
    .warning-card { background-color: #FFF8E1; padding: 18px; border-radius: 12px;
                    border-left: 6px solid #F9A825; margin-top: 20px; }
    </style>
    """,
    unsafe_allow_html=True,
)

col1, col2 = st.columns([6, 1])
with col1:
    st.markdown(
        """
        <div class="main-title">Comparateur FCS / Excel</div>
        <div class="subtitle">
            Vérification automatique des fonctions entre un fichier FCS XML
            et les nomenclatures Excel du site.
        </div>
        """,
        unsafe_allow_html=True,
    )
with col2:
    st.image("assets/logo_ice.png", width=140)

st.divider()

fcs_file = st.file_uploader("1. Déposer le fichier FCS (.xml)", type=["xml"])

excel_files = st.file_uploader(
    "2. Déposer les nomenclatures (Excel ou PDF, Tranche Générale comprise)",
    type=["xls", "xlsx", "pdf"],
    accept_multiple_files=True,
)

st.caption(
    "La Tranche Générale est reconnue automatiquement à son onglet CAL : "
    "inutile de la déposer à part. Si elle est absente, la comparaison est "
    "menée quand même et l'absence est signalée dans le rapport."
)

st.divider()


def analyse(fcs_file, excel_files):
    return run_analysis(
        fcs_file, [(uploaded.name, uploaded) for uploaded in excel_files]
    )


if st.button("Lancer la comparaison"):
    if fcs_file is None:
        st.error("Merci de déposer un fichier FCS.")
    elif not excel_files:
        st.error("Merci de déposer au moins une nomenclature Excel.")
    else:
        with st.spinner("Analyse en cours..."):
            fcs, associations, comparison, report, failures = analyse(
                fcs_file, excel_files
            )

        st.markdown(
            '<div class="success-card">✅ Comparaison terminée.</div>',
            unsafe_allow_html=True,
        )

        st.download_button(
            label="Télécharger le rapport Excel",
            data=report,
            file_name="rapport_comparaison_fcs_excel.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # ------------------------------------------------------------------
        st.markdown("### Associations")

        icons = {
            "page_de_garde": "✅",
            "page_de_garde_sans_indice": "✅",
            "tranche_generale": "🏛️",
            "nom_cellule_infoposte": "✅",
            "desambiguisation_transformateur": "✅",
            "multi_tension": "🔀",
            "collision": "⚠️",
            "page_de_garde_sans_correspondance": "❌",
            "echec": "❌",
        }
        st.table([
            {
                "": icons.get(match["method"], "❔"),
                "Fichier": filename,
                "Tranche": match["tranche"] or match.get("tranche_absente") or "—",
                "Méthode": match["method"],
                "Page de garde": match.get("raw") or "",
            }
            for filename, match in sorted(associations.items())
        ])

        warnings = [
            "**%s** — %s" % (filename, match["warning"])
            for filename, match in sorted(associations.items())
            if match.get("warning")
        ]
        if warnings:
            with st.expander("Avertissements sur les associations (%d)" % len(warnings)):
                for line in warnings:
                    st.write("- " + line)

        if failures:
            st.error("Fichiers illisibles :")
            for filename, message in failures.items():
                st.write("- **%s** : %s" % (filename, message))

        # ------------------------------------------------------------------
        st.markdown("### Tranches à signaler")

        pending = {
            name: entry["statut_tranche"]
            for name, entry in comparison["tranches"].items()
            if entry["statut_tranche"]
        }
        if pending:
            for name, statut in sorted(pending.items()):
                st.write("- `%s` → %s" % (name, statut))
        else:
            st.write("Aucune tranche à signaler.")

        # ------------------------------------------------------------------
        st.markdown("### Synthèse")

        rows = []
        for name, entry in sorted(comparison["tranches"].items()):
            for section, lines in entry["sections"].items():
                rows.append({
                    "Tranche": name,
                    "Section": section,
                    # En-tetes courts a l'ecran : les intitules complets du
                    # rapport Excel tronquaient la derniere colonne.
                    "Conformes": sum(1 for r in lines if is_ok_status(r["Statut"])),
                    "Uniquement nomenclature": sum(
                        1 for r in lines if r["Statut"] == STATUS_EXCEL_ONLY),
                    "Uniquement FCS": sum(
                        1 for r in lines if r["Statut"] == STATUS_FCS_ONLY),
                })
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)