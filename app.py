import streamlit as st

from src.fcs_parser import parse_fcs
from src.excel_parser import parse_excel_file
from src.comparator import compare_excel_to_fcs
from src.report_generator import generate_excel_report
from src.tranche_matcher import match_files_to_tranches_with_llm

st.markdown(
    """
    <style>
    .main-title {
        font-size: 42px;
        font-weight: 800;
        color: #12355B;
        margin-bottom: 0px;
    }

    .subtitle {
        font-size: 18px;
        color: #555;
        margin-bottom: 30px;
    }

    .section-card {
        background-color: #F7F9FC;
        padding: 24px;
        border-radius: 14px;
        border: 1px solid #E3E8EF;
        margin-bottom: 20px;
    }

    .success-card {
        background-color: #EAF7EA;
        padding: 18px;
        border-radius: 12px;
        border-left: 6px solid #2E7D32;
        margin-top: 20px;
    }

    .warning-card {
        background-color: #FFF8E1;
        padding: 18px;
        border-radius: 12px;
        border-left: 6px solid #F9A825;
        margin-top: 20px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.set_page_config(
    page_title="Comparateur FCS / Excel",
    page_icon="📊",
    layout="wide"
)

col1, col2 = st.columns([6, 1])

with col1:
    st.markdown(
        """
        <div class="main-title">
            Comparateur FCS / Excel
        </div>
        <div class="subtitle">
            Vérification automatique des fonctions entre un fichier FCS XML et plusieurs fichiers Excel.
        </div>
        """,
        unsafe_allow_html=True
    )

with col2:
    st.image("assets/logo_ice.png", width=420)

st.divider()

fcs_file = st.file_uploader(
    "1. Déposer le fichier FCS (.xml)",
    type=["xml"]
)

tg_excel_file = st.file_uploader(
    "2. Déposer le fichier Excel de la Tranche Générale",
    type=["xls", "xlsx"]
)

other_excel_files = st.file_uploader(
    "3. Déposer les autres fichiers Excel",
    type=["xls", "xlsx"],
    accept_multiple_files=True
)

st.divider()

if st.button("Lancer la comparaison"):
    if fcs_file is None:
        st.error("Merci de déposer un fichier FCS.")
    elif tg_excel_file is None:
        st.error("Merci de déposer le fichier Excel de la Tranche Générale.")
    elif not other_excel_files:
        st.error("Merci de déposer au moins un fichier Excel hors Tranche Générale.")
    else:
        with st.spinner("Analyse en cours..."):
            fcs_data = parse_fcs(fcs_file)

            excel_data = {}

            excel_data["T.GENE"] = parse_excel_file(
                tg_excel_file,
                tg_excel_file.name
            )

            filenames = [file.name for file in other_excel_files]

            available_tranches = [
                tranche for tranche in fcs_data.keys()
                if tranche != "T.GENE"
            ]

            matches, unresolved = match_files_to_tranches_with_llm(
                filenames,
                available_tranches
            )

            ignored_files = list(unresolved.keys())

            for file in other_excel_files:
                if file.name not in matches:
                    continue

                tranche_name = matches[file.name]["tranche"]

                excel_data[tranche_name] = parse_excel_file(
                    file,
                    file.name
                )

            comparison = compare_excel_to_fcs(excel_data, fcs_data)
            report = generate_excel_report(comparison)

        st.markdown(
            '<div class="success-card">✅ Comparaison terminée avec succès.</div>',
            unsafe_allow_html=True
        )

        st.markdown("### Associations détectées")

        for filename, match in matches.items():
            if match["method"] == "llm":
                st.write(f"🤖 **{filename}** → `{match['tranche']}`")
            else:
                st.write(f"✅ **{filename}** → `{match['tranche']}`")
                        
                if ignored_files:
                    st.warning("Certains fichiers n'ont pas pu être associés automatiquement à une tranche :")
                    for filename in ignored_files:
                        st.write(f"- {filename}")

        st.download_button(
            label="Télécharger le rapport Excel",
            data=report,
            file_name="rapport_comparaison_fcs_excel.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )