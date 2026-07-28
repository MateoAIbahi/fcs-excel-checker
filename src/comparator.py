from src.utils import normalize
from src.excel_parser import resolve_function

# --------------------------------------------------------------------------
# Statuts
# --------------------------------------------------------------------------

STATUS_OK = "OK"
STATUS_OK_INSTANCE = "OK (mnémonique indicé)"
STATUS_OK_LABEL = "OK (libellé long)"
STATUS_EXCEL_ONLY = "Présent Excel uniquement"
STATUS_FCS_ONLY = "Présent FCS uniquement"

METHOD_STATUS = {
    "code": STATUS_OK,
    "mnemonique_indice": STATUS_OK_INSTANCE,
    "libelle_long": STATUS_OK_LABEL,
}

# Statuts au niveau tranche (pas de ligne fonction a produire)
TRANCHE_NO_FILE = "Nomenclature absente"
TRANCHE_CONFLICT = "Plusieurs nomenclatures en conflit - à trancher manuellement"
TRANCHE_EMPTY_FILE = "Nomenclature présente mais sans onglet exploitable"
TRANCHE_TG_MISSING = "Nomenclature TG absente - comparaison poursuivie sans elle"
TRANCHE_E13_OK = "OK via onglet sous-tranche E13"
TRANCHE_E13_MISSING = "Nomenclature absente et aucun onglet sous-tranche E13 trouvé"

TG_ALIASES = {"TGENE", "TG", "TRANCHEGENERALE"}
SECTIONS = ["FonctionsNumériséesCCN", "EquipementsTiers"]


def is_tg_tranche(name):
    return normalize(name) in TG_ALIASES


def is_raccordement_transformateur(tranche_info):
    """
    Les tranches "Raccordement Transformateur" se reconnaissent dans le FCS a
    leur type de tranche : LibelléTT du genre
    'Compact_CBO_SECT_E411_sous-tranche_E13_SE', CodeSchémathèqueTT 'E13'.
    Plus fiable qu'une liste de prefixes de noms.
    """
    tt = normalize(tranche_info.get("LibelléTT"))
    schema = normalize(tranche_info.get("CodeSchémathèqueTT"))
    return "SOUSTRANCHEE13" in tt or "E13" in schema


# --------------------------------------------------------------------------
# Comparaison d'une section
# --------------------------------------------------------------------------

def compare_section(parsed, fcs_objects, section):
    """
    parsed      : sortie de parse_excel_file
    fcs_objects : {code: libellé long} pour la section
    Retourne la liste de lignes du rapport.
    """
    rows = []
    consumed = set()

    for code, label in sorted(fcs_objects.items()):
        found, method, evidence = resolve_function(parsed, section, code, label)
        if found:
            if method in ("code", "mnemonique_indice"):
                consumed.add(normalize(evidence))
            rows.append({
                "Fonction Excel": evidence if method != "libelle_long" else "",
                "Fonction FCS": code,
                "Libellé FCS": label,
                "Statut": METHOD_STATUS.get(method, STATUS_OK),
                "Détail": evidence if method == "libelle_long" else "",
            })
        else:
            rows.append({
                "Fonction Excel": "",
                "Fonction FCS": code,
                "Libellé FCS": label,
                "Statut": STATUS_FCS_ONLY,
                "Détail": "",
            })

    for raw in sorted(parsed.get(section, set())):
        if normalize(raw) in consumed:
            continue
        rows.append({
            "Fonction Excel": raw,
            "Fonction FCS": "",
            "Libellé FCS": "",
            "Statut": STATUS_EXCEL_ONLY,
            "Détail": "",
        })

    return rows


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def compare_all(fcs, associations, parsed_by_file):
    """
    fcs            : sortie de parse_fcs (clé 'tranches')
    associations   : {nom_fichier: dict issu de match_workbook_to_tranche}
    parsed_by_file : {nom_fichier: sortie de parse_excel_file}

    Itere sur les TRANCHES DU FCS et non sur les fichiers Excel : c'est ce
    qui permet de signaler une tranche sans nomenclature au lieu de
    l'ignorer silencieusement.
    """
    tranches = fcs["tranches"]

    by_tranche = {}
    for filename, match in associations.items():
        if match.get("tranche"):
            by_tranche.setdefault(match["tranche"], []).append(filename)

    # Un fichier CBO porteur d'un onglet "sous-tranche E13" couvre les
    # tranches raccordement transformateur depourvues de nomenclature.
    e13_sources = [
        filename for filename, parsed in parsed_by_file.items()
        if parsed.get("has_e13")
    ]

    result = {}
    for name, info in tranches.items():
        files = by_tranche.get(name, [])

        entry = {
            "fichiers": files,
            "statut_tranche": None,
            "avertissements": [],
            "sections": {},
        }
        for filename in files:
            warning = associations[filename].get("warning")
            if warning:
                entry["avertissements"].append("%s : %s" % (filename, warning))

        if not files:
            conflicting = sorted(
                filename for filename, match in associations.items()
                if match.get("tranche_visee") == name
            )
            if conflicting:
                entry["statut_tranche"] = TRANCHE_CONFLICT
                entry["avertissements"].append(
                    "Fichiers en conflit : %s" % ", ".join(conflicting)
                )
                result[name] = entry
                continue
            if is_tg_tranche(name):
                entry["statut_tranche"] = TRANCHE_TG_MISSING
            elif is_raccordement_transformateur(info):
                if e13_sources:
                    entry["statut_tranche"] = TRANCHE_E13_OK
                    entry["avertissements"].append(
                        "Couverte par l'onglet sous-tranche E13 de : %s"
                        % ", ".join(sorted(e13_sources))
                    )
                else:
                    entry["statut_tranche"] = TRANCHE_E13_MISSING
            else:
                entry["statut_tranche"] = TRANCHE_NO_FILE
            result[name] = entry
            continue

        # Les sections a comparer dependent du type de tranche.
        sections = ["FonctionsNumériséesCCN"]
        if not is_tg_tranche(name):
            sections.append("EquipementsTiers")

        merged = _merge_parsed([parsed_by_file[f] for f in files])

        # Nomenclature reduite a sa page de garde (cas du fichier TGE de COMPI) :
        # comparer produirait une liste de faux "présent FCS uniquement".
        sheets = merged.get("sheets") or {}
        if not any(sheets.get(key) for key in ("ccn", "bt", "tac", "cal")):
            entry["statut_tranche"] = TRANCHE_EMPTY_FILE
            entry["avertissements"].append(
                "Aucun onglet CCN / Basse Tension / TAC / CAL dans %s"
                % ", ".join(files)
            )
            result[name] = entry
            continue

        for section in sections:
            entry["sections"][section] = compare_section(
                merged, info.get(section, {}), section
            )

        for note in merged.get("notes", []):
            entry["avertissements"].append(note)

        result[name] = entry

    # Fichiers qu'on n'a pas su rattacher : ils doivent apparaitre au rapport.
    orphans = {
        filename: match for filename, match in associations.items()
        if not match.get("tranche")
    }

    return {"tranches": result, "fichiers_non_associes": orphans}


def _merge_parsed(parsed_list):
    """Plusieurs fichiers peuvent alimenter une meme tranche."""
    if len(parsed_list) == 1:
        return parsed_list[0]
    merged = {
        "FonctionsNumériséesCCN": set(),
        "EquipementsTiers": set(),
        "mnemonics": set(),
        "labels": [],
        "notes": [],
        "has_e13": False,
        "sheets": {"ccn": [], "bt": [], "tac": [], "cal": [], "e13": []},
    }
    for parsed in parsed_list:
        for key in ("FonctionsNumériséesCCN", "EquipementsTiers", "mnemonics"):
            merged[key].update(parsed.get(key, set()))
        merged["labels"].extend(parsed.get("labels", []))
        merged["notes"].extend(parsed.get("notes", []))
        merged["has_e13"] = merged["has_e13"] or parsed.get("has_e13", False)
        for key, value in (parsed.get("sheets") or {}).items():
            merged["sheets"].setdefault(key, []).extend(value)
    return merged