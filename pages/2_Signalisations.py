"""
Page 2 : verification des signalisations (phase 2).

Prototype soumis a ICE pour valider le fonctionnement et quelques regles
avant d'aller plus loin. Les points a valider sont rappeles en bas de page.
"""

import streamlit as st

st.set_page_config(
    page_title="Vérification des signalisations",
    page_icon="🔔",
    layout="wide",
)

import pandas as pd                                            # noqa: E402

from src.signalisations.comparator import (                    # noqa: E402
    STATUS_FCS_ONLY,
    STATUS_LOT_ONLY,
    STATUS_OK,
)
from src.signalisations.pipeline import run_analysis           # noqa: E402

st.markdown(
    """
    <style>
    .main-title { font-size: 42px; font-weight: 800; color: #12355B; margin-bottom: 0px; }
    .subtitle { font-size: 18px; color: #555; margin-bottom: 30px; }
    .proto { background-color: #FFF8E1; padding: 14px 18px; border-radius: 12px;
             border-left: 6px solid #F9A825; margin-bottom: 18px; }
    </style>
    """,
    unsafe_allow_html=True,
)

col1, col2 = st.columns([6, 1])
with col1:
    st.markdown(
        """
        <div class="main-title">Vérification des signalisations</div>
        <div class="subtitle">
            Croisement du fichier FCS, des fichiers de lot et du référentiel
            dicodata, signalisation par signalisation.
        </div>
        """,
        unsafe_allow_html=True,
    )
with col2:
    st.image("assets/logo_ice.png", width=140)

st.markdown(
    '<div class="proto"><b>Version de travail.</b> Cette page est soumise '
    "pour validation du fonctionnement et des règles de comparaison. Les "
    "points en attente de décision sont rappelés en bas de page.</div>",
    unsafe_allow_html=True,
)

fcs_file = st.file_uploader("1. Déposer le fichier FCS (.xml)", type=["xml"])

lot_files = st.file_uploader(
    "2. Déposer les fichiers de lot (.xml), un par type de tranche",
    type=["xml"],
    accept_multiple_files=True,
)

dicodata_file = st.file_uploader(
    "3. Déposer le référentiel dicodata (facultatif)", type=["xls", "xlsx"])

overrides_file = st.file_uploader(
    "4. Déposer la table des fonctions atypiques (facultatif)",
    type=["xls", "xlsx", "csv"])

st.caption(
    "Chaque lot décrit un type de tranche et vaut pour toutes les tranches "
    "du FCS de ce type. Sans dicodata, la comparaison reste possible : "
    "seules les colonnes de référence sont vides."
)

st.divider()

if st.button("Lancer la vérification", type="primary"):
    if not fcs_file or not lot_files:
        st.warning("Un fichier FCS et au moins un fichier de lot sont nécessaires.")
        st.stop()

    with st.spinner("Lecture des fichiers et croisement des sources..."):
        fcs, comparison, report, sources, failures = run_analysis(
            fcs_file,
            [(file.name, file) for file in lot_files],
            dicodata_file,
            overrides_file,
        )
    st.session_state["phase2"] = (fcs, comparison, report, sources, failures)

if "phase2" in st.session_state:
    fcs, comparison, report, sources, failures = st.session_state["phase2"]
    rows = comparison["lignes"]

    st.success("Vérification terminée.")
    st.download_button(
        "Télécharger le rapport Excel",
        data=report.getvalue(),
        file_name="rapport_signalisations.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    counts = {}
    for row in rows:
        counts[row["Statut"]] = counts.get(row["Statut"], 0) + 1
    columns = st.columns(4)
    columns[0].metric("Signalisations comparées", len(rows))
    columns[1].metric("Présentes des deux côtés", counts.get(STATUS_OK, 0))
    columns[2].metric("Prévues au lot, absentes du FCS",
                      counts.get(STATUS_LOT_ONLY, 0))
    columns[3].metric("Présentes au FCS, absentes du lot",
                      counts.get(STATUS_FCS_ONLY, 0))

    st.markdown("### Fichiers de lot")
    st.dataframe(
        pd.DataFrame([
            {"Fichier": name, "Type de tranche": libelle,
             "Tranches visées": ", ".join(tranches) or "aucune"}
            for name, libelle, tranches in sources
        ]),
        use_container_width=True, hide_index=True,
    )
    for name, message in failures.items():
        st.error("%s : %s" % (name, message))
    if comparison["avertissements"]:
        with st.expander("Avertissements (%d)" % len(comparison["avertissements"])):
            for warning in comparison["avertissements"]:
                st.markdown("- %s" % warning)

    st.markdown("### Synthèse par tranche")
    summary = [
        {"Tranche": tranche,
         "Type de tranche": entry.get("type", ""),
         "Fonctions": entry.get("fonctions", ""),
         "dont rattachées à un bloc": entry.get("fonctions_avec_bloc", ""),
         "Conformes": (entry.get("compte") or {}).get(STATUS_OK, ""),
         "Absentes du FCS": (entry.get("compte") or {}).get(STATUS_LOT_ONLY, ""),
         "Absentes du lot": (entry.get("compte") or {}).get(STATUS_FCS_ONLY, ""),
         "Statut": entry.get("statut", "")}
        for tranche, entry in sorted(comparison["tranches"].items())
    ]
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

    st.markdown("### Détail des signalisations")
    frame = pd.DataFrame(rows)
    if not frame.empty:
        choices = sorted(frame["Statut"].unique())
        selected = st.multiselect("Filtrer par statut", choices, default=choices)
        tranches = sorted(frame["Tranche"].unique())
        chosen = st.multiselect("Filtrer par tranche", tranches, default=tranches)
        view = frame[frame["Statut"].isin(selected) & frame["Tranche"].isin(chosen)]
        st.caption("%d lignes affichées sur %d." % (len(view), len(frame)))
        st.dataframe(view, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Points à valider")
    st.markdown(
        "- **Périmètre du premier contrôle.** Le fichier de lot est un "
        "catalogue du type de tranche : comparé tel quel, il fait ressortir "
        "des centaines de signalisations « manquantes » dont les fonctions "
        "ne sont pas installées. La comparaison est donc limitée aux "
        "fonctions déclarées au FCS pour la tranche.\n"
        "- **Blocs communs.** `COMMUN TRANCHE`, `DISJONCTEUR`, `SA` ou "
        "`POSITION DES ORGANES` ne sont pas des fonctions. Un tel bloc est "
        "retenu dès qu'une de ses signalisations figure au FCS.\n"
        "- **Variantes numérotées.** `DT.PX1`, `DT.PX2`, `DT.PX2.PHASE 4` "
        "ressortent comme absentes du FCS. S'agit-il de vrais écarts, ou "
        "faut-il une règle d'applicabilité (deuxième protection non "
        "installée) ?\n"
        "- **Fonctions atypiques.** En l'absence de la table, les "
        "correspondances partielles suivent des règles provisoires "
        "(`PDL1`→`PDL`, `ARS-BASE`→`ARS`, `PXmulti-PX`→`PX`), reportées "
        "dans la colonne Méthode."
    )
else:
    st.info("Déposez les fichiers puis lancez la vérification.")
