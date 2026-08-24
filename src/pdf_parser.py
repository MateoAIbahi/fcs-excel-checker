"""
Lecture des nomenclatures exportees au format PDF.

Ces PDF sont l'impression du meme classeur que les nomenclatures Excel :
une page de garde en tableau cle/valeur, puis un onglet par page (parfois
plusieurs pages pour un meme onglet). Le nom de l'onglet figure en pied de
page, sous la forme "2-Basse Tension        6/11".

On se contente donc de reconstituer, pour chaque onglet, un DataFrame de
meme forme que celui produit par pandas sur le classeur Excel. Tout le
reste de la chaine (classification des onglets, extraction des fonctions,
comparaison) est partage avec le chemin Excel : voir
excel_parser.parse_sheet_frames.
"""

import re

import pandas as pd
import pdfplumber

from src.excel_parser import parse_sheet_frames
from src.utils import normalize

# "2-Basse Tension      6/11" : nom d'onglet suivi de la pagination.
FOOTER_RE = re.compile(r"^(?P<sheet>.+?)\s+(?P<page>\d+)\s*/\s*(?P<total>\d+)\s*$")

# Pages annexes : schemas HT, fiches suiveuses exportees depuis un autre
# classeur. Elles portent un pied de page mais aucune donnee exploitable.
ANNEX_SHEETS = ("XLSX", "SCHEMAHT")


def is_pdf(filename):
    return str(filename or "").lower().endswith(".pdf")


def sheet_name_of(page):
    """Nom de l'onglet lu dans le pied de page, ou None (page de garde, annexe)."""
    text = page.extract_text() or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    match = FOOTER_RE.match(lines[-1])
    if not match:
        return None
    name = match.group("sheet").strip()
    token = normalize(name)
    if not token or any(token.endswith(suffix) for suffix in ANNEX_SHEETS):
        return None
    return name


def _to_rows(table):
    """Nettoie une table pdfplumber : None -> '', retours ligne -> espace."""
    rows = []
    for row in table or []:
        rows.append([
            "" if cell is None else str(cell).replace("\n", " ").strip()
            for cell in row
        ])
    return rows


def _drop_repeated_header(rows, header):
    """
    Un onglet reparti sur plusieurs pages repete son en-tete. Sans ce
    filtrage, la ligne 'Désignation | Nom Litéral | Type option' serait lue
    comme une fonction nommee 'Désignation'.
    """
    if not header:
        return rows
    reference = [normalize(cell) for cell in header]
    return [
        row for row in rows
        if [normalize(cell) for cell in row] != reference
    ]


def load_pdf_context(file, max_pdg_rows=40):
    """
    Retourne (frames, sheet_names, pdg_rows), meme contrat que
    excel_parser.load_workbook_context.
    """
    frames = {}
    headers = {}
    pdg_rows = []

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            rows = _to_rows(table)
            name = sheet_name_of(page)

            if name is None:
                # Page de garde : premiere page sans pied de page exploitable.
                if not pdg_rows and rows:
                    pdg_rows = [tuple(row) for row in rows[:max_pdg_rows]]
                continue

            if not rows:
                continue

            if name in frames:
                rows = _drop_repeated_header(rows, headers.get(name))
                frames[name].extend(rows)
            else:
                headers[name] = _detect_header(rows)
                frames[name] = rows

    width = {name: max((len(row) for row in rows), default=0)
             for name, rows in frames.items()}
    return (
        {
            name: pd.DataFrame([row + [""] * (width[name] - len(row))
                                for row in rows])
            for name, rows in frames.items()
        },
        list(frames),
        pdg_rows,
    )


def _detect_header(rows):
    """Repere la ligne d'en-tete pour pouvoir la filtrer sur les pages suivantes."""
    for row in rows[:6]:
        tokens = {normalize(cell) for cell in row}
        if "DESIGNATION" in tokens or "MNEMONIQUE" in tokens:
            return row
    return None


def parse_pdf_file(file, filename=None):
    """Equivalent de parse_excel_file pour une nomenclature PDF."""
    frames, _sheet_names, _pdg_rows = load_pdf_context(file)
    result = parse_sheet_frames(frames)
    result["notes"].append("Nomenclature lue depuis un PDF.")
    return result