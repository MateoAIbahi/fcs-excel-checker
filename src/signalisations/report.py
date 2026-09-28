"""
Rapport Excel de la phase 2.

Trois onglets, dans l'esprit du rapport de la phase 1 :

* Resume  : une ligne par tranche (fonctions, comptes par statut) ;
* Details : une ligne par signalisation, avec ses colonnes de provenance ;
* Sources : fichiers de lot lus et avertissements.
"""

from io import BytesIO

import pandas as pd

from src.signalisations.comparator import (
    STATUS_FCS_ONLY,
    STATUS_FCS_OUT_OF_SCOPE,
    STATUS_LOT_ONLY,
    STATUS_OK,
)

COLORS = {
    STATUS_OK: "#D9EAD3",
    STATUS_LOT_ONLY: "#FCE5CD",
    STATUS_FCS_ONLY: "#F4CCCC",
    STATUS_FCS_OUT_OF_SCOPE: "#FFF2CC",
}

COLUMN_WIDTHS = {
    "Tranche": 14,
    "Type de tranche": 32,
    "Fichier de lot": 40,
    "Fonction FCS": 18,
    "Bloc du lot": 24,
    "Méthode": 24,
    "Type": 24,
    "Référence lot": 26,
    "Instance": 22,
    "IDRC": 12,
    "Mnémonique FCS": 18,
    "Libellé FCS": 34,
    "Présente au lot": 16,
    "Présente au FCS": 16,
    "Connue du dicodata": 20,
    "Mnémonique dicodata": 20,
    "Libellé dicodata": 46,
    "Statut": 46,
    "Fonctions du FCS": 16,
    "Fonctions rattachées à un bloc": 28,
    "Fonctions sans bloc": 52,
    "Signalisations du FCS": 20,
    "Avertissements": 70,
}

COLUMN_OK = "Présentes des deux côtés"
COLUMN_LOT_ONLY = "Prévues au lot, absentes du FCS"
COLUMN_FCS_ONLY = "Présentes au FCS, absentes du lot"


def _summary_frame(comparison):
    rows = []
    for tranche, entry in sorted(comparison["tranches"].items()):
        counts = entry.get("compte") or {}
        rows.append({
            "Tranche": tranche,
            "Type de tranche": entry.get("type", ""),
            "Fichier de lot": entry.get("fichier", ""),
            "Fonctions du FCS": entry.get("fonctions", ""),
            "Fonctions rattachées à un bloc": entry.get("fonctions_avec_bloc", ""),
            "Signalisations du FCS": entry.get("signalisations_fcs", ""),
            COLUMN_OK: counts.get(STATUS_OK, 0) if counts else "",
            COLUMN_LOT_ONLY: counts.get(STATUS_LOT_ONLY, 0) if counts else "",
            COLUMN_FCS_ONLY: counts.get(STATUS_FCS_ONLY, 0) if counts else "",
            "Statut": entry.get("statut", ""),
            "Fonctions sans bloc": ", ".join(entry.get("fonctions_sans_bloc", [])),
        })
    return pd.DataFrame(rows)


def _sources_frame(comparison, files=None):
    rows = [{"Fichier de lot": name, "Type de tranche": libelle,
             "Tranches visées": ", ".join(tranches), "Avertissement": ""}
            for name, libelle, tranches in (files or [])]
    rows.extend({"Fichier de lot": "", "Type de tranche": "",
                 "Tranches visées": "", "Avertissement": warning}
                for warning in comparison["avertissements"])
    return pd.DataFrame(rows)


def _format_sheet(worksheet, frame, status_formats):
    if frame.empty:
        return
    for index, column in enumerate(frame.columns):
        worksheet.set_column(index, index, COLUMN_WIDTHS.get(column, 22))
    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(frame), len(frame.columns) - 1)

    if "Statut" not in frame.columns:
        return
    for offset, status in enumerate(frame["Statut"], start=1):
        cell_format = status_formats.get(status)
        if cell_format:
            worksheet.set_row(offset, None, cell_format)


def generate_excel_report(comparison, files=None):
    """Retourne un BytesIO contenant le classeur."""
    summary = _summary_frame(comparison)
    details = pd.DataFrame(comparison["lignes"])
    sources = _sources_frame(comparison, files)

    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="xlsxwriter") as writer:
        book = writer.book
        header = book.add_format({
            "bold": True, "bg_color": "#12355B", "font_color": "white",
            "border": 1, "text_wrap": True, "valign": "vcenter",
        })
        status_formats = {status: book.add_format({"bg_color": color})
                          for status, color in COLORS.items()}

        for name, frame in (("Résumé", summary), ("Détails", details),
                            ("Sources", sources)):
            frame.to_excel(writer, sheet_name=name, index=False)
            worksheet = writer.sheets[name]
            if not frame.empty:
                for index, column in enumerate(frame.columns):
                    worksheet.write(0, index, column, header)
            _format_sheet(worksheet, frame, status_formats)

    stream.seek(0)
    return stream
