from src.excel_parser import parse_excel_file

files = [
    "data/0-BELIE_3AUT.POS_2.1_240515-113404.xlsx",
    "data/0-BELIE_CBO_1.1_231011-155353.xlsx",
    "data/0-BELIE_L31HOSTE_2.1_240513-144100.xlsx",
    "data/0-BELIE_L31MASQU_2.1_240513-151844.xlsx",
    "data/BELIET - NOM_E9 SE 20230504 indH.xls",
]

for filepath in files:
    print()
    print("FICHIER :", filepath)

    with open(filepath, "rb") as file:
        result = parse_excel_file(file, filepath)

    print("CCN :", len(result["FonctionsNumériséesCCN"]))
    print("EQUIPEMENTS :", len(result["EquipementsTiers"]))

    print("Exemples CCN :", list(result["FonctionsNumériséesCCN"])[:5])
    print("Exemples EQUIPEMENTS :", list(result["EquipementsTiers"])[:5])