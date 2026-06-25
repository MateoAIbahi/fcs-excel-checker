from src.utils import normalize


def compare_sets(excel_values, fcs_values):
    excel_norm = {normalize(v): v for v in excel_values}
    fcs_norm = {normalize(v): v for v in fcs_values}

    excel_keys = set(excel_norm.keys())
    fcs_keys = set(fcs_norm.keys())

    ok = excel_keys & fcs_keys
    only_excel = excel_keys - fcs_keys
    only_fcs = fcs_keys - excel_keys

    rows = []

    for key in sorted(ok):
        rows.append({
            "Fonction Excel": excel_norm[key],
            "Fonction FCS": fcs_norm[key],
            "Statut": "OK"
        })

    for key in sorted(only_excel):
        rows.append({
            "Fonction Excel": excel_norm[key],
            "Fonction FCS": "",
            "Statut": "Présent Excel uniquement"
        })

    for key in sorted(only_fcs):
        rows.append({
            "Fonction Excel": "",
            "Fonction FCS": fcs_norm[key],
            "Statut": "Présent FCS uniquement"
        })

    return rows


def compare_excel_to_fcs(excel_data, fcs_data):
    result = {}

    for tranche_name, excel_sections in excel_data.items():
        fcs_sections = fcs_data.get(tranche_name)

        if not fcs_sections:
            result[tranche_name] = {
                "Erreur": f"Tranche '{tranche_name}' introuvable dans le FCS"
            }
            continue

        result[tranche_name] = {}

        sections_to_compare = ["FonctionsNumériséesCCN"]

        if tranche_name != "T.GENE":
            sections_to_compare.append("EquipementsTiers")

        for section_name in sections_to_compare:
            excel_values = excel_sections.get(section_name, set())
            fcs_values = fcs_sections.get(section_name, set())

            result[tranche_name][section_name] = compare_sets(
                excel_values,
                fcs_values
            )

    return result