from lxml import etree

SECTIONS = ["FonctionsNumériséesCCN", "EquipementsTiers"]


def _voltage_of(tranche):
    """Libelle du NiveauTension parent : '225kV', '0kV'... ou ''."""
    levels = tranche.xpath("ancestor::*[local-name()='NiveauTension'][1]")
    return (levels[0].get("LibelléNiveauTension") or "") if levels else ""


def parse_fcs(file):
    """
    Retourne :
    {
      "site": {"code": "MATHA", "nom": "MATHA"},
      "tranches": {
         "4TR411": {
            "LibelléLongTranche": "TRANSFORMATEUR 411",
            "LibelléTT": "Compact_CBO_SECT_E411_sous-tranche_E13_SE",
            "CodeSchémathèqueTT": "E13",
            "FonctionsNumériséesCCN": {"SYNO": "SYNOPTIQUE"},
            "EquipementsTiers": {},
         },
         ...
      }
    }

    Deux changements par rapport a la version precedente :
      - on conserve le LibelléLongObjetFonction, indispensable au
        rapprochement par libelle long demande pour les EQ TIERS ;
      - on conserve LibelléTT et CodeSchémathèqueTT, qui identifient les
        tranches "raccordement transformateur" (regle sous-tranche E13).
    """
    tree = etree.parse(file)
    root = tree.getroot()

    # Table NiveauTension -> prefixe de tranche, deduite du FCS lui-meme
    # plutot que codee en dur : '63kV' -> '3', '225kV' -> '6', etc.
    voltage_prefixes = {}
    for level in root.xpath(".//*[local-name()='NiveauTension']"):
        label = level.get("LibelléNiveauTension")
        if not label:
            continue
        for child in level.xpath(".//*[local-name()='Tranche']"):
            name = (child.get("LibelléCourtTranche") or "").strip()
            if name and name[0].isdigit():
                voltage_prefixes.setdefault(label, name[0])

    tranches = {}
    for tranche in root.xpath(".//*[local-name()='Tranche']"):
        name = (tranche.get("LibelléCourtTranche") or "").strip()
        if not name:
            continue

        entry = {
            "LibelléLongTranche": tranche.get("LibelléLongTranche") or "",
            "LibelléTT": tranche.get("LibelléTT") or "",
            "CodeSchémathèqueTT": tranche.get("CodeSchémathèqueTT") or "",
            "NiveauTension": _voltage_of(tranche),
        }

        for section in SECTIONS:
            objects = tranche.xpath(
                ".//*[local-name()='%s']/*[local-name()='ObjetFonction']" % section
            )
            entry[section] = {}
            for obj in objects:
                code = obj.get("LibelléCourtObjetFonction")
                if not code:
                    continue
                label = obj.get("LibelléLongObjetFonction") or ""
                entry[section][code.strip()] = label.strip()

        tranches[name] = entry

    return {
        "site": {
            "code": root.get("CodeNationalSite") or "",
            "nom": root.get("NomSite") or "",
        },
        "tranches": tranches,
        "niveaux_tension": voltage_prefixes,
    }