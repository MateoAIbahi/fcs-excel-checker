"""
Point d'entree unique pour lire une nomenclature, quel que soit son format.

Les nomenclatures arrivent tantot en .xlsx, tantot en .xls, tantot en .pdf.
Le reste de la chaine n'a pas a s'en soucier : ce module renvoie toujours le
meme triplet (noms d'onglets, lignes de page de garde, resultat d'analyse).
"""

import os

from src.excel_parser import load_workbook_context, parse_excel_file
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
    return sheet_names, pdg_rows, parse_excel_file(xls, filename)


SUPPORTED_EXTENSIONS = ["xls", "xlsx", "pdf"]