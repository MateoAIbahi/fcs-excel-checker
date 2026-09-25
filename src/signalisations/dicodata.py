"""
Lecture du referentiel dicodata, troisieme source de la phase 2.

Classeur de 34 onglets et 9 Mo, dont deux seulement servent ici :

* 'information_type' : 2 838 IDRC, c'est lui qui fait le travail ;
* 'dd_idrc_it'       : 222 IDRC seulement (11 % du besoin), en complement.

Mesure sur MAUGE : les deux onglets combines couvrent 100 % des IDRC du lot
et 98 % de ceux du FCS.

La premiere ligne de donnees de chaque onglet decrit les TYPES de colonnes
('varchar(50)', 'int(2)') et non des valeurs : seules les lignes dont l'IDRC
a la forme 'ID' suivi de chiffres sont retenues.

Le classeur est volumineux : ne lire que les deux onglets utiles evite d'en
parcourir 34. L'appelant (page Streamlit) met le resultat en cache.
"""

import re

import pandas as pd

SHEET_MAIN = "information_type"
SHEET_EXTRA = "dd_idrc_it"
SHEET_FUNCTIONS = "dd_fonction_tranche"

IDRC_RE = re.compile(r"^ID\d+$")

# Colonnes reprises, par onglet : {nom dans le classeur: nom en sortie}
COLUMNS_MAIN = {
    "mnemo_info_court": "mnemonique",
    "mnemo_info_interne": "mnemonique_interne",
    "nom_info_type": "libellé",
    "nature": "nature",
    "finalite = designation": "désignation",
}
COLUMNS_EXTRA = {
    "mnemo_info_cours": "mnemonique",
    "mnemo_info_interne_commun": "mnemonique_interne",
    "nature": "nature",
}


def load_dicodata(file):
    """
    Retourne :
      {
        "idrc": {"ID000607": {"mnemonique", "libellé", "nature", "source"}},
        "fonctions": {"PXmulti-PX": "Fonction PX dans Protection..."},
        "compte": {"information_type": 2838, "dd_idrc_it": 222},
      }
    """
    book = file if isinstance(file, pd.ExcelFile) else pd.ExcelFile(file)
    entries, counts = {}, {}

    for sheet, columns in ((SHEET_MAIN, COLUMNS_MAIN), (SHEET_EXTRA, COLUMNS_EXTRA)):
        rows = _read(book, sheet, columns)
        counts[sheet] = len(rows)
        for idrc, entry in rows.items():
            # 'information_type' est lu en premier et fait foi.
            entries.setdefault(idrc, dict(entry, source=sheet))

    return {"idrc": entries, "fonctions": _functions(book), "compte": counts}


def _read(book, sheet, columns):
    if sheet not in book.sheet_names:
        return {}
    frame = pd.read_excel(book, sheet_name=sheet)
    if "IDRC" not in frame.columns:
        return {}

    available = {source: target for source, target in columns.items()
                 if source in frame.columns}
    frame = frame[["IDRC"] + list(available)]

    entries = {}
    for record in frame.to_dict("records"):
        idrc = _text(record["IDRC"])
        if not IDRC_RE.match(idrc) or idrc in entries:
            continue
        entries[idrc] = {target: _text(record[source])
                         for source, target in available.items()}
    return entries


def _text(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _functions(book):
    """Catalogue des fonctions (dd_fonction_tranche) : {mnemonique: libelle}."""
    if SHEET_FUNCTIONS not in book.sheet_names:
        return {}
    frame = pd.read_excel(book, sheet_name=SHEET_FUNCTIONS)
    code_column = next((column for column in frame.columns
                        if "mnemo_fonction" in str(column)), None)
    name_column = next((column for column in frame.columns
                        if "nom_fonction" in str(column)), None)
    if code_column is None:
        return {}

    functions = {}
    for _, row in frame.iterrows():
        code = _text(row.get(code_column))
        if not code or code.startswith("varchar"):
            continue
        functions.setdefault(code, _text(row.get(name_column)) if name_column else "")
    return functions


def describe(dicodata, idrc):
    """Entree du dicodata pour un IDRC, ou None."""
    return (dicodata or {}).get("idrc", {}).get(idrc)
