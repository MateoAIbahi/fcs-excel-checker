from io import BytesIO

import pandas as pd

from src.comparator import (
    STATUS_OK,
    STATUS_OK_INSTANCE,
    STATUS_OK_LABEL,
    STATUS_OK_EQUIVALENCE,
    STATUS_OK_CAL,
    STATUS_EXCEL_ONLY,
    STATUS_FCS_ONLY,
    COLUMN_OK,
    COLUMN_EXCEL_ONLY,
    COLUMN_FCS_ONLY,
    is_ok_status,
)

COLORS = {
    STATUS_OK: "#D9EAD3",
    STATUS_OK_INSTANCE: "#E8F0DA",
    STATUS_OK_LABEL: "#E8F0DA",
    STATUS_OK_EQUIVALENCE: "#E8F0DA",
    STATUS_OK_CAL: "#E8F0DA",
    STATUS_EXCEL_ONLY: "#FCE5CD",
    STATUS_FCS_ONLY: "#F4CCCC",
}

COLUMN_WIDTHS = {
    "Tranche": 14,
    "Section": 24,
    "Fichier(s)": 38,
    "Statut": 44,
    COLUMN_OK: 16,
    COLUMN_EXCEL_ONLY: 26,
    COLUMN_FCS_ONLY: 26,
    "Statut tranche": 46,
    "Fonction Excel": 30,
    "Fonction FCS": 20,
    "Libellé FCS": 46,
    "Détail": 46,
    "Avertissements": 70,
    "Méthode": 26,
    "Codification page de garde": 30,
}


def _build_frames(comparison):
    summary, details, associations = [], [], []

    for tranche, entry in sorted(comparison["tranches"].items()):
        files = ", ".join(entry["fichiers"])
        warnings = " | ".join(entry["avertissements"])

        if entry["statut_tranche"]:
            summary.append({
                "Tranche": tranche,
                "Section": "",
                "Fichier(s)": files,
                COLUMN_OK: 0,
                COLUMN_EXCEL_ONLY: 0,
                COLUMN_FCS_ONLY: 0,
                "Statut tranche": entry["statut_tranche"],
                "Avertissements": warnings,
            })
            continue

        for section, rows in entry["sections"].items():
            counts = {}
            for row in rows:
                counts[row["Statut"]] = counts.get(row["Statut"], 0) + 1
                details.append({
                    "Tranche": tranche,
                    "Section": section,
                    "Fonction Excel": row["Fonction Excel"],
                    "Fonction FCS": row["Fonction FCS"],
                    "Libellé FCS": row["Libellé FCS"],
                    "Statut": row["Statut"],
                    "Détail": row["Détail"],
                })

            ok = sum(n for status, n in counts.items() if is_ok_status(status))
            summary.append({
                "Tranche": tranche,
                "Section": section,
                "Fichier(s)": files,
                COLUMN_OK: ok,
                COLUMN_EXCEL_ONLY: counts.get(STATUS_EXCEL_ONLY, 0),
                COLUMN_FCS_ONLY: counts.get(STATUS_FCS_ONLY, 0),
                "Statut tranche": "",
                "Avertissements": warnings,
            })

    for tranche, entry in sorted(comparison["tranches"].items()):
        for filename in entry["fichiers"]:
            associations.append({
                "Fichier": filename,
                "Tranche": tranche,
                "Méthode": "",
                "Codification page de garde": "",
                "Avertissements": " | ".join(entry["avertissements"]),
            })

    for filename, match in sorted(comparison["fichiers_non_associes"].items()):
        associations.append({
            "Fichier": filename,
            "Tranche": "NON ASSOCIÉ",
            "Méthode": match.get("method", ""),
            "Codification page de garde": match.get("raw") or "",
            "Avertissements": match.get("warning") or "",
        })

    return (pd.DataFrame(summary),
            pd.DataFrame(details),
            pd.DataFrame(associations))


def _format_sheet(worksheet, df, workbook, header_format, status_formats):
    if df.empty:
        return
    for index, column in enumerate(df.columns):
        worksheet.write(0, index, column, header_format)
        worksheet.set_column(index, index, COLUMN_WIDTHS.get(column, 22))
    worksheet.freeze_panes(1, 0)
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    if "Statut" not in df.columns:
        return
    for offset, status in enumerate(df["Statut"], start=1):
        cell_format = status_formats.get(status)
        if cell_format:
            worksheet.set_row(offset, None, cell_format)


def generate_excel_report(comparison, association_details=None):
    """
    comparison          : sortie de compare_all
    association_details : {nom_fichier: dict de match_workbook_to_tranche},
                          optionnel, enrichit l'onglet Associations.
    """
    output = BytesIO()
    summary_df, details_df, associations_df = _build_frames(comparison)

    if association_details and not associations_df.empty:
        for index, row in associations_df.iterrows():
            match = association_details.get(row["Fichier"])
            if not match:
                continue
            associations_df.at[index, "Méthode"] = match.get("method", "")
            associations_df.at[index, "Codification page de garde"] = match.get("raw") or ""

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="Résumé", index=False)
        associations_df.to_excel(writer, sheet_name="Associations", index=False)
        details_df.to_excel(writer, sheet_name="Détails", index=False)

        workbook = writer.book
        header_format = workbook.add_format({
            "bold": True, "bg_color": "#D9EAF7", "border": 1,
            "text_wrap": True, "valign": "vcenter",
        })
        status_formats = {
            status: workbook.add_format({"bg_color": color})
            for status, color in COLORS.items()
        }

        for sheet_name, df in (("Résumé", summary_df),
                               ("Associations", associations_df),
                               ("Détails", details_df)):
            _format_sheet(writer.sheets[sheet_name], df, workbook,
                          header_format, status_formats)

    output.seek(0)
    return output