from src.fcs_parser import parse_fcs
from src.excel_parser import parse_excel_file
from src.comparator import compare_excel_to_fcs


EXCEL_TO_TRANCHE = {
    "data/0-BELIE_3AUT.POS_2.1_240515-113404.xlsx": "3AUT.POS",
    "data/0-BELIE_CBO_1.1_231011-155353.xlsx": "3CBO.1",
    "data/0-BELIE_L31HOSTE_2.1_240513-144100.xlsx": "3HOSTE.1",
    "data/0-BELIE_L31MASQU_2.1_240513-151844.xlsx": "3MASQU.1",
    "data/BELIET - NOM_E9 SE 20230504 indH.xls": "T.GENE",
}


fcs_data = parse_fcs("data/FCS_BELIE_2.xml")

excel_data = {}

for filepath, tranche_name in EXCEL_TO_TRANCHE.items():
    with open(filepath, "rb") as file:
        excel_data[tranche_name] = parse_excel_file(file, filepath)

comparison = compare_excel_to_fcs(excel_data, fcs_data)

for tranche, sections in comparison.items():
    print()
    print("TRANCHE :", tranche)

    if "Erreur" in sections:
        print(sections["Erreur"])
        continue

    for section_name, rows in sections.items():
        ok = sum(1 for r in rows if r["Statut"] == "OK")
        only_excel = sum(1 for r in rows if r["Statut"] == "Présent Excel uniquement")
        only_fcs = sum(1 for r in rows if r["Statut"] == "Présent FCS uniquement")

        print(section_name)
        print("  OK :", ok)
        print("  Excel uniquement :", only_excel)
        print("  FCS uniquement :", only_fcs)