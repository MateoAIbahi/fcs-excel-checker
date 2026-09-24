"""
Point d'entree unique pour lire une nomenclature, quel que soit son format.

Les nomenclatures arrivent tantot en .xlsx, tantot en .xls, tantot en .pdf.
Le reste de la chaine n'a pas a s'en soucier : ce module renvoie toujours le
meme triplet (noms d'onglets, lignes de page de garde, resultat d'analyse).
"""

import os

from src.excel_parser import (
    classify_sheets,
    load_workbook_context,
    parse_excel_file,
    read_struck_rows,
)
from src.pdf_parser import is_pdf, load_pdf_context
from src.excel_parser import parse_sheet_frames


def load_nomenclature(file, filename=None):
    """
    Retourne (sheet_names, pdg_rows, parsed).

    `file` : chemin ou objet fichier. `filename` sert uniquement a
    determiner le format ; il est deduit du chemin s'il n'est pas fourni.
    """
    if filename is None and isinstance(file, str):
        filename = os.path.basename(file)

    if is_pdf(filename):
        frames, sheet_names, pdg_rows = load_pdf_context(file)
        parsed = parse_sheet_frames(frames)
        parsed["notes"].append("Nomenclature lue depuis un PDF.")
        return sheet_names, pdg_rows, parsed

    xls, sheet_names, pdg_rows = load_workbook_context(file)
    # Les options barrees ne sont pas lisibles via pandas : le classeur est
    # relu une fois pour sa mise en forme.
    struck_rows = read_struck_rows(file, filename)
    parsed = parse_excel_file(xls, filename, struck_rows)

    # Note limitee aux onglets exploites : le barre d'un onglet annexe
    # (GARDIENNAGE, STRUCTURE...) n'a aucun effet sur la comparaison.
    buckets = classify_sheets(sheet_names)
    used = {name for names in buckets.values() for name in names}
    signaled = {sheet: rows for sheet, rows in struck_rows.items()
                if sheet in used}
    if signaled:
        parsed["notes"].append(
            "Lignes barrées ignorées : %s."
            % ", ".join("%s (%d)" % (sheet, len(rows))
                        for sheet, rows in sorted(signaled.items())))
    return sheet_names, pdg_rows, parsed


SUPPORTED_EXTENSIONS = ["xls", "xlsx", "pdf"]