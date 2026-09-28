"""
Chaine de traitement de la phase 2, independante de Streamlit.

Utilisee par la page 'Signalisations' et par check_signalisations.py, sur le
modele de src/pipeline.py pour la phase 1.
"""

import pandas as pd

from src.signalisations.comparator import compare_site
from src.signalisations.dicodata import load_dicodata
from src.signalisations.fcs_signals import read_fcs_signals, tranches_of_type
from src.signalisations.fonctions import load_overrides
from src.signalisations.lot_parser import parse_lot
from src.signalisations.report import generate_excel_report

# Colonnes acceptees pour la table des fonctions atypiques fournie par ICE.
FUNCTION_COLUMNS = ("fonction", "fonction fcs", "code", "mnemonique")
BLOCK_COLUMNS = ("bloc", "bloc du lot", "commentaire", "bloc lot")


def read_overrides(file):
    """
    Table des fonctions atypiques : deux colonnes, fonction et bloc.
    Accepte .xlsx, .xls et .csv. Renvoie ({}, message) en cas d'echec.
    """
    if file is None:
        return {}, ""
    try:
        name = getattr(file, "name", str(file)).lower()
        frame = (pd.read_csv(file) if name.endswith(".csv")
                 else pd.read_excel(file))
    except Exception as error:                      # noqa: BLE001
        return {}, "Table des fonctions atypiques illisible : %s." % error

    columns = {str(column).strip().lower(): column for column in frame.columns}
    function_column = next((columns[key] for key in FUNCTION_COLUMNS
                            if key in columns), None)
    block_column = next((columns[key] for key in BLOCK_COLUMNS
                         if key in columns), None)
    if function_column is None or block_column is None:
        return {}, ("Table des fonctions atypiques ignorée : colonnes "
                    "attendues 'fonction' et 'bloc'.")

    pairs = [(str(row[function_column]), str(row[block_column]))
             for _, row in frame.iterrows()
             if str(row.get(function_column) or "").strip()
             and str(row.get(block_column) or "").strip()]
    return load_overrides(pairs), ""


def run_analysis(fcs_file, lot_files, dicodata_file=None, overrides_file=None):
    """
    fcs_file      : chemin ou objet fichier du FCS
    lot_files     : iterable de (nom, chemin ou objet fichier)
    dicodata_file : classeur dicodata, facultatif
    overrides_file: table des fonctions atypiques, facultative

    Retourne (fcs, comparison, report, sources, failures).
    'sources' : [(nom, LibelléTT, tranches visées)] pour l'onglet Sources.
    """
    fcs = read_fcs_signals(fcs_file)
    overrides, message = read_overrides(overrides_file)

    dicodata, failures = None, {}
    if dicodata_file is not None:
        try:
            dicodata = load_dicodata(dicodata_file)
        except Exception as error:                  # noqa: BLE001
            failures["dicodata"] = "%s : %s" % (type(error).__name__, error)

    lots, sources = [], []
    for name, file in lot_files:
        try:
            lot = parse_lot(file)
        except Exception as error:                  # noqa: BLE001
            failures[name] = "%s : %s" % (type(error).__name__, error)
            continue
        lots.append((name, lot))
        libelle = lot["type_tranche"].get("LibelléTT", "")
        sources.append((name, libelle,
                        tranches_of_type(fcs, libelle,
                                         lot["type_tranche"].get("IndiceTT"))))

    comparison = compare_site(fcs, lots, dicodata, overrides)
    if message:
        comparison["avertissements"].append(message)
    for name, lot in lots:
        comparison["avertissements"].extend(
            "%s : %s" % (name, warning) for warning in lot["avertissements"])

    report = generate_excel_report(comparison, sources)
    return fcs, comparison, report, sources, failures
