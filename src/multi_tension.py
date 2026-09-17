"""
Nomenclatures multi-tension.

Certaines nomenclatures AUT.POS regroupent tous les niveaux de tension du
poste dans un seul classeur, un onglet CCN par niveau :

    Page de garde | 2-CCN 225kV | 3- CCN 90kV | 5- CCN 0kV | 6-TAC

Chaque onglet CCN doit etre compare a la tranche AUT.POS du meme niveau de
tension dans le FCS. Le niveau d'une tranche est lu dans la hierarchie du FCS
(NiveauTension parent), et non deduit de son prefixe : la tranche 0 kV n'en
a pas ('AUT.POST' a MAUGE).

Le fichier est remplace, apres rattachement, par une association par niveau
de tension, nommee '<fichier> [<onglet>]'. Les onglets Basse Tension / TAC,
communs au classeur, suivent la tranche designee par la page de garde, a
defaut le niveau de tension le plus bas.

Si le FCS n'a pas de tranche AUT.POS pour un niveau, l'association porte
'tranche_absente' : les fonctions de l'onglet sont alors listees comme
presentes uniquement dans la nomenclature, sous un statut de tranche dedie.
"""

import re

from src.utils import normalize
from src.tranche_matcher import split_tranche_name

METHOD = "multi_tension"

# Radicaux concernes (forme canonique, voir tranche_matcher.RADICAL_ALIASES)
MULTI_VOLTAGE_RADICALS = {"AUTPOS"}
DISPLAY_RADICAL = {"AUTPOS": "AUT.POS"}
MULTI_VOLTAGE_TYPE_CODES = {"022"}      # '022-Tranche automate de poste'

VOLTAGE_RE = re.compile(r"(\d+)\s*kV", re.IGNORECASE)


def voltage_value(text):
    """'2-CCN 225kV' -> 225, '0kV' -> 0, sinon None."""
    match = VOLTAGE_RE.search(str(text or ""))
    return int(match.group(1)) if match else None


def voltage_sheets(parsed):
    """
    {tension: [onglets CCN]} si le classeur porte au moins deux niveaux de
    tension distincts, sinon {}. Un onglet CCN sans tension dans son nom
    interdit le decoupage : on ne saurait pas a quelle tranche le rattacher.
    """
    by_voltage = {}
    for sheet in parsed.get("ccn_by_sheet", {}):
        value = voltage_value(sheet)
        if value is None:
            return {}
        by_voltage.setdefault(value, []).append(sheet)
    return by_voltage if len(by_voltage) >= 2 else {}


def family_radical(match):
    """Radical multi-tension vise par la nomenclature, ou None."""
    for key in ("tranche", "tranche_visee", "raw"):
        value = match.get(key)
        if not value:
            continue
        head = re.split(r"\s+-\s+", str(value))[0]
        _, radical, _ = split_tranche_name(head)
        for family in MULTI_VOLTAGE_RADICALS:
            if radical == family or normalize(head).endswith(family):
                return family
    type_tranche = str(match.get("type_tranche") or "").strip()[:3]
    if type_tranche in MULTI_VOLTAGE_TYPE_CODES:
        return "AUTPOS"
    return None


def find_tranche(fcs, radical, voltage):
    """Tranche du FCS de ce radical et de ce niveau de tension, si unique."""
    hits = [
        name for name, info in fcs["tranches"].items()
        if split_tranche_name(name)[1] == radical
        and voltage_value(info.get("NiveauTension")) == voltage
    ]
    return hits[0] if len(hits) == 1 else None


def expected_tranche_name(fcs, radical, voltage):
    """Nom attendu d'une tranche absente : '6AUT.POS', 'AUT.POS' (0 kV)."""
    prefix = ""
    for label, value in (fcs.get("niveaux_tension") or {}).items():
        if voltage_value(label) == voltage:
            prefix = value
            break
    return "%s%s" % (prefix, DISPLAY_RADICAL.get(radical, radical))


def _subset(parsed, sheets, with_equipment):
    """Vue de `parsed` limitee a certains onglets CCN."""
    sub = dict(parsed)
    ccn = parsed.get("ccn_by_sheet", {})
    sub["ccn_by_sheet"] = {name: ccn[name] for name in sheets}
    sub["FonctionsNumériséesCCN"] = set().union(
        *(ccn[name]["functions"] for name in sheets)
    )
    sub["skipped_non"] = set().union(*(ccn[name]["skipped"] for name in sheets))
    sub["sheets"] = dict(parsed.get("sheets") or {})
    sub["sheets"]["ccn"] = list(sheets)
    sub["notes"] = list(parsed.get("notes", []))
    if not with_equipment:
        sub["EquipementsTiers"] = set()
        sub["mnemonics"] = set()
        sub["tac_codes"] = set()
        sub["labels"] = []
        sub["sheets"]["bt"] = []
        sub["sheets"]["tac"] = []
        sub["notes"] = [n for n in sub["notes"]
                        if "Basse Tension" not in n and "TAC" not in n]
    return sub


def expand_multi_voltage(associations, parsed_by_file, fcs):
    """
    Remplace chaque nomenclature multi-tension par une association par
    niveau de tension. Modifie et renvoie les deux dictionnaires.
    """
    for filename in list(associations):
        match = associations[filename]
        parsed = parsed_by_file.get(filename)
        if not parsed:
            continue
        radical = family_radical(match)
        if not radical:
            continue
        by_voltage = voltage_sheets(parsed)
        if not by_voltage:
            continue

        home = None
        if match.get("tranche"):
            info = fcs["tranches"].get(match["tranche"], {})
            home = voltage_value(info.get("NiveauTension"))
        if home not in by_voltage:
            home = min(by_voltage)
        has_equipment = bool((parsed.get("sheets") or {}).get("bt")
                             or (parsed.get("sheets") or {}).get("tac"))

        del associations[filename]
        del parsed_by_file[filename]

        for voltage in sorted(by_voltage, reverse=True):
            sheets = by_voltage[voltage]
            key = "%s [%s]" % (filename, ", ".join(sheets))
            with_equipment = voltage == home
            tranche = find_tranche(fcs, radical, voltage)

            entry = dict(match)
            entry.update({
                "tranche": tranche,
                "method": METHOD,
                "fichier_source": filename,
                "tension": "%d kV" % voltage,
            })
            entry.pop("tranche_visee", None)

            if tranche:
                warning = ("Nomenclature multi-tension : onglet %s rattaché à "
                           "la tranche %s (%d kV)." % (", ".join(sheets),
                                                      tranche, voltage))
            else:
                entry["tranche_absente"] = "%s (absente du FCS)" % (
                    expected_tranche_name(fcs, radical, voltage))
                warning = ("Nomenclature multi-tension : le FCS ne contient "
                           "aucune tranche %s de niveau %d kV pour l'onglet %s."
                           % (DISPLAY_RADICAL.get(radical, radical), voltage,
                              ", ".join(sheets)))
            if with_equipment and has_equipment:
                warning += (" Les onglets Basse Tension / TAC du classeur sont "
                            "comparés à ce niveau de tension.")
            entry["warning"] = warning

            associations[key] = entry
            parsed_by_file[key] = _subset(parsed, sheets, with_equipment)

    return associations, parsed_by_file
