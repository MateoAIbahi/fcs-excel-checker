import re
import pandas as pd

from src.utils import normalize, clean_code, is_section_title, is_tg_file


def read_excel_sheets(file):
    return pd.ExcelFile(file)


def extract_ccn_sheet(df):
    functions = set()

    header_row = None
    designation_col = None

    for index, row in df.iterrows():
        values = [normalize(v) for v in row.values]

        if "DESIGNATION" in values:
            header_row = index
            designation_col = values.index("DESIGNATION")
            break

    if header_row is None:
        return functions

    for _, row in df.iloc[header_row + 1:].iterrows():
        code = clean_code(row.iloc[designation_col])

        if code and not is_section_title(code):
            functions.add(code)

    return functions


def extract_cal_sheet(df):
    functions = set()

    start = False

    for _, row in df.iterrows():
        first_col = clean_code(row.iloc[0]) if len(row) > 0 else None
        second_col = clean_code(row.iloc[1]) if len(row) > 1 else None
        retained = clean_code(row.iloc[4]) if len(row) > 4 else None

        if second_col and "Fonctions ou équipements interfacés" in second_col:
            break

        if second_col and "Fonctions numérisées dans" in second_col:
            start = True
            continue

        if start and first_col and normalize(retained) == "X":
            functions.add(first_col)

    return functions


def extract_basse_tension_sheet(df):
    functions = set()

    header_row = None
    mnemonic_col = None
    designation_col = None

    for index, row in df.iterrows():
        values = [normalize(v) for v in row.values]

        if "MNEMONIQUE" in values:
            header_row = index
            mnemonic_col = values.index("MNEMONIQUE")
            designation_col = values.index("DESIGNATION") if "DESIGNATION" in values else 1
            break

    if header_row is None:
        return functions

    for _, row in df.iloc[header_row + 1:].iterrows():
        mnemonic = clean_code(row.iloc[mnemonic_col])
        designation = clean_code(row.iloc[designation_col])

        if mnemonic and designation and not is_section_title(mnemonic):
            if "-Fonction" in designation or "Fonction" in designation:
                functions.add(mnemonic)

        elif designation and "-Fonction" in designation:
            match = re.search(r"([A-Za-z0-9_.-]+)-Fonction", designation)
            if match:
                functions.add(match.group(1))

    return functions


def extract_tac_sheet(df):
    functions = set()

    header_row = None
    fct_tac_col = None

    for index, row in df.iterrows():
        values = [normalize(v) for v in row.values]

        if "FCTTAC" in values:
            header_row = index
            fct_tac_col = values.index("FCTTAC")
            break

    if header_row is None:
        return functions

    for _, row in df.iloc[header_row + 1:].iterrows():
        value = clean_code(row.iloc[fct_tac_col])

        if value:
            matches = re.findall(r":\s*([A-Za-z0-9_.-]+)", value)
            for match in matches:
                functions.add(match)

    return functions


def parse_excel_file(file, filename):
    xls = read_excel_sheets(file)

    result = {
        "FonctionsNumériséesCCN": set(),
        "EquipementsTiers": set()
    }

    if is_tg_file(filename):
        for sheet_name in xls.sheet_names:
            if normalize(sheet_name) == "CAL":
                df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
                result["FonctionsNumériséesCCN"].update(extract_cal_sheet(df))

    else:
        for sheet_name in xls.sheet_names:
            normalized_sheet = normalize(sheet_name)

            df = pd.read_excel(xls, sheet_name=sheet_name, header=None)

            if "CCN" in normalized_sheet:
                result["FonctionsNumériséesCCN"].update(extract_ccn_sheet(df))

            elif "BASSETENSION" in normalized_sheet:
                result["EquipementsTiers"].update(extract_basse_tension_sheet(df))

            elif "TAC" in normalized_sheet:
                result["EquipementsTiers"].update(extract_tac_sheet(df))

    return result