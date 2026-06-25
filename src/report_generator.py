import pandas as pd
from io import BytesIO


def generate_excel_report(comparison):
    output = BytesIO()

    summary_rows = []
    detail_rows = []

    for tranche, sections in comparison.items():
        if "Erreur" in sections:
            summary_rows.append({
                "Tranche": tranche,
                "Section": "",
                "OK": 0,
                "Présent Excel uniquement": 0,
                "Présent FCS uniquement": 0,
                "Erreur": sections["Erreur"]
            })
            continue

        for section_name, rows in sections.items():
            ok = sum(1 for r in rows if r["Statut"] == "OK")
            only_excel = sum(1 for r in rows if r["Statut"] == "Présent Excel uniquement")
            only_fcs = sum(1 for r in rows if r["Statut"] == "Présent FCS uniquement")

            summary_rows.append({
                "Tranche": tranche,
                "Section": section_name,
                "OK": ok,
                "Présent Excel uniquement": only_excel,
                "Présent FCS uniquement": only_fcs,
                "Erreur": ""
            })

            for row in rows:
                detail_rows.append({
                    "Tranche": tranche,
                    "Section": section_name,
                    "Fonction Excel": row["Fonction Excel"],
                    "Fonction FCS": row["Fonction FCS"],
                    "Statut": row["Statut"]
                })

    summary_df = pd.DataFrame(summary_rows)
    detail_df = pd.DataFrame(detail_rows)

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="Résumé", index=False)
        detail_df.to_excel(writer, sheet_name="Détails", index=False)

        workbook = writer.book

        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#D9EAF7",
            "border": 1
        })

        ok_format = workbook.add_format({
            "bg_color": "#D9EAD3"
        })

        warning_format = workbook.add_format({
            "bg_color": "#FCE5CD"
        })

        error_format = workbook.add_format({
            "bg_color": "#F4CCCC"
        })

        for sheet_name in ["Résumé", "Détails"]:
            worksheet = writer.sheets[sheet_name]
            df = summary_df if sheet_name == "Résumé" else detail_df

            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
                worksheet.set_column(col_num, col_num, 25)

            if sheet_name == "Détails" and not df.empty:
                statut_col = df.columns.get_loc("Statut")

                for row_num, statut in enumerate(df["Statut"], start=1):
                    if statut == "OK":
                        worksheet.set_row(row_num, None, ok_format)
                    elif statut == "Présent Excel uniquement":
                        worksheet.set_row(row_num, None, warning_format)
                    elif statut == "Présent FCS uniquement":
                        worksheet.set_row(row_num, None, error_format)

    output.seek(0)
    return output