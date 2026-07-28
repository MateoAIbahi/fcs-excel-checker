import streamlit as st

# set_page_config doit precede TOUT autre appel Streamlit, y compris
# st.markdown : sinon Streamlit leve StreamlitSetPageConfigMustBeFirstCommand.
st.set_page_config(
    page_title="Comparateur FCS / Excel",
    page_icon="📊",
    layout="wide",
)

from src.fcs_parser import parse_fcs
from src.excel_parser import parse_excel_file, load_workbook_context
from src.comparator import compare_all
from src.report_generator import generate_excel_report
from src.tranche_matcher import match_workbook_to_tranche, resolve_collisions

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
    "2. Déposer les nomenclatures Excel (Tranche Générale comprise)",
    type=["xls", "xlsx"],
    accept_multiple_files=True,
)

st.caption(
    "La Tranche Générale est reconnue automatiquement à son onglet CAL : "
    "inutile de la déposer à part. Si elle est absente, la comparaison est "
    "menée quand même et l'absence est signalée dans le rapport."
)

st.divider()


def analyse(fcs_file, excel_files):
    fcs = parse_fcs(fcs_file)
    tranche_names = list(fcs["tranches"])
    site = (fcs["site"]["code"], fcs["site"]["nom"])
    volts = fcs.get("niveaux_tension", {})

    associations = {}
    parsed_by_file = {}
    failures = {}

    for uploaded in excel_files:
        name = uploaded.name
        try:
            xls, sheet_names, pdg_rows = load_workbook_context(uploaded)
            associations[name] = match_workbook_to_tranche(
                name, sheet_names, pdg_rows, tranche_names, site, volts
            )
            parsed_by_file[name] = parse_excel_file(xls, name)
        except Exception as error:              # noqa: BLE001
            failures[name] = "%s : %s" % (type(error).__name__, error)

    associations = resolve_collisions(associations)
    comparison = compare_all(fcs, associations, parsed_by_file)
    report = generate_excel_report(comparison, associations)
    return fcs, associations, comparison, report, failures


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
            "collision": "⚠️",
            "page_de_garde_sans_correspondance": "❌",
            "echec": "❌",
        }
        st.table([
            {
                "": icons.get(match["method"], "❔"),
                "Fichier": filename,
                "Tranche": match["tranche"] or "—",
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
        st.markdown("### Tranches du FCS sans comparaison")

        pending = {
            name: entry["statut_tranche"]
            for name, entry in comparison["tranches"].items()
            if entry["statut_tranche"]
        }
        if pending:
            for name, statut in sorted(pending.items()):
                st.write("- `%s` → %s" % (name, statut))
        else:
            st.write("Toutes les tranches du FCS ont été comparées.")

        # ------------------------------------------------------------------
        st.markdown("### Synthèse")

        rows = []
        for name, entry in sorted(comparison["tranches"].items()):
            for section, lines in entry["sections"].items():
                rows.append({
                    "Tranche": name,
                    "Section": section,
                    "OK": sum(1 for r in lines if r["Statut"].startswith("OK")),
                    "Excel seul": sum(1 for r in lines
                                      if r["Statut"].startswith("Présent Excel")),
                    "FCS seul": sum(1 for r in lines
                                    if r["Statut"].startswith("Présent FCS")),
                })
        if rows:
            st.dataframe(rows, use_container_width=True)