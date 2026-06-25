from lxml import etree


def parse_fcs(file):
    tree = etree.parse(file)
    root = tree.getroot()

    result = {}

    for tranche in root.xpath(".//*[local-name()='Tranche']"):
        tranche_name = tranche.get("LibelléCourtTranche", "")

        result[tranche_name] = {
            "FonctionsNumériséesCCN": set(),
            "EquipementsTiers": set()
        }

        for section_name in ["FonctionsNumériséesCCN", "EquipementsTiers"]:
            objets = tranche.xpath(
                f".//*[local-name()='{section_name}']/*[local-name()='ObjetFonction']"
            )

            for obj in objets:
                code = obj.get("LibelléCourtObjetFonction")
                if code:
                    result[tranche_name][section_name].add(code.strip())

    return result