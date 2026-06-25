from fcs_parser import parse_fcs

result = parse_fcs("data/FCS_BELIE_2.xml")

for tranche, data in result.items():
    print()
    print("TRANCHE :", tranche)
    print("CCN :", len(data["FonctionsNumériséesCCN"]))
    print("EQUIPEMENTS :", len(data["EquipementsTiers"]))