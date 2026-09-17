import re

from src.utils import normalize
from src.excel_parser import resolve_function, CAL_IGNORED_CODES

# --------------------------------------------------------------------------
# Statuts (seul endroit ou ces libelles sont definis : le rapport et
# l'interface les importent, aucune logique ne doit tester leur texte)
# --------------------------------------------------------------------------

STATUS_OK = "Comparaison conforme"
STATUS_OK_INSTANCE = "Comparaison conforme (mnémonique indicé)"
STATUS_OK_LABEL = "Comparaison conforme (libellé long)"
STATUS_OK_EQUIVALENCE = "Comparaison conforme (équivalence de code)"
STATUS_OK_CAL = "Comparaison conforme (recherche dans tout l'onglet CAL)"
STATUS_EXCEL_ONLY = "Fonction présente uniquement dans le fichier de nomenclature"
STATUS_FCS_ONLY = "Fonction présente uniquement dans le fichier FCS"

OK_STATUSES = {
    STATUS_OK, STATUS_OK_INSTANCE, STATUS_OK_LABEL,
    STATUS_OK_EQUIVALENCE, STATUS_OK_CAL,
}

# Titres des colonnes de comptage de l'onglet Resume
COLUMN_OK = "Comparaison conforme"
COLUMN_EXCEL_ONLY = "Fonctions présentes uniquement dans le fichier de nomenclature"
COLUMN_FCS_ONLY = "Fonctions présentes uniquement dans le fichier FCS"

METHOD_STATUS = {
    "code": STATUS_OK,
    "mnemonique_indice": STATUS_OK_INSTANCE,
    "libelle_long": STATUS_OK_LABEL,
    "equivalence": STATUS_OK_EQUIVALENCE,
    "onglet_cal_complet": STATUS_OK_CAL,
}

# Methodes dont la preuve est un code de la nomenclature : ce code ne doit
# plus apparaitre en 'present uniquement dans la nomenclature'.
CONSUMING_METHODS = {"code", "mnemonique_indice", "equivalence",
                     "onglet_cal_complet"}


def is_ok_status(status):
    return status in OK_STATUSES

# Statuts au niveau tranche (pas de ligne fonction a produire)
TRANCHE_NO_FILE = "Nomenclature absente"
TRANCHE_CONFLICT = "Plusieurs nomenclatures en conflit - à trancher manuellement"
TRANCHE_EMPTY_FILE = "Nomenclature présente mais sans onglet exploitable"
TRANCHE_TG_MISSING = "Nomenclature TG absente - comparaison poursuivie sans elle"
TRANCHE_E13_OK = "OK via onglet sous-tranche E13"
TRANCHE_E13_MISSING = "Nomenclature absente et aucun onglet sous-tranche E13 trouvé"

TG_ALIASES = {"TGENE", "TG", "TRANCHEGENERALE"}
SECTIONS = ["FonctionsNumériséesCCN", "EquipementsTiers"]

# Tranches hors perimetre de l'etude : elles ne sont ni comparees ni
# signalees comme depourvues de nomenclature.
EXCLUDED_TRANCHES = {"SAUX", "SI"}

# Fonctions hors perimetre, par section.
EXCLUDED_FUNCTIONS = {"EquipementsTiers": {"SONDE"}}

# Mnemoniques d'equipement TAC : ce sont les materiels, pas les fonctions.
TAC_EQUIPMENT_RE = re.compile(r"^TAC[-_ ]?N?\d*$", re.IGNORECASE)


def is_excluded_tranche(name):
    return normalize(name) in EXCLUDED_TRANCHES


def is_excluded_function(section, code):
    """
    Exclusion par prefixe : 'SONDE' ecarte aussi 'Sonde température',
    'SONDE 1', etc. Les nomenclatures nomment rarement ces lignes a
    l'identique d'un site a l'autre.
    """
    token = normalize(code)
    if not token:
        return False
    for excluded in EXCLUDED_FUNCTIONS.get(section, set()):
        reference = normalize(excluded)
        if reference and token.startswith(reference):
            return True
    return False


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

def compare_section(parsed, fcs_objects, section, ignored_codes=()):
    """
    parsed        : sortie de parse_excel_file
    fcs_objects   : {code: libellé long} pour la section
    ignored_codes : codes normalises ecartes des deux cotes (egalite exacte)
    Retourne la liste de lignes du rapport.
    """
    rows = []
    consumed = set()
    ignored = {normalize(c) for c in ignored_codes}

    for code, label in sorted(fcs_objects.items()):
        if is_excluded_function(section, code) or normalize(code) in ignored:
            continue
        found, method, evidence = resolve_function(parsed, section, code, label)
        if found:
            if method in CONSUMING_METHODS:
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

    matched_codes = {row["Fonction FCS"] for row in rows
                     if is_ok_status(row["Statut"])}

    remaining = [
        raw for raw in sorted(parsed.get(section, set()))
        if normalize(raw) not in consumed
        and normalize(raw) not in ignored
        and not is_excluded_function(section, raw)
    ]

    # Tous les codes qui figureront au rapport pour cette section : sert a
    # reperer les mnemoniques parents devenus redondants.
    visible_codes = set(matched_codes) | set(remaining)

    for raw in remaining:
        if section == "EquipementsTiers" and _is_redundant_equipment(
                raw, visible_codes, parsed, matched_codes):
            continue
        rows.append({
            "Fonction Excel": raw,
            "Fonction FCS": "",
            "Libellé FCS": "",
            "Statut": STATUS_EXCEL_ONLY,
            "Détail": "",
        })

    return rows


def _is_redundant_equipment(raw, visible_codes, parsed, matched_codes):
    """
    Ecarte les lignes "Présent Excel uniquement" qui font double emploi :

    - le mnemonique parent d'une sous-fonction deja presente au rapport : si
      'PXmulti-PX' y figure, la ligne 'PXmulti' n'apporte rien. La
      sous-fonction compte qu'elle ait ete appariee ou non, sans quoi le
      rapport afficherait les deux lignes cote a cote ;
    - les mnemoniques d'equipement TAC ('TAC-N1', 'TAC-N2') des lors qu'au
      moins une fonction a ete reperee via l'onglet TAC.
    """
    token = normalize(raw)

    for code in visible_codes:
        if not code or normalize(code) == token:
            continue
        if "-" in str(code) and normalize(str(code).split("-", 1)[0]) == token:
            return True

    if TAC_EQUIPMENT_RE.match(str(raw).strip()):
        tac_codes = {normalize(c) for c in parsed.get("tac_codes", set())}
        if tac_codes & {normalize(c) for c in matched_codes}:
            return True

    return False


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
        if is_excluded_tranche(name):
            continue
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

        # TG / TGSI : ecartes des deux cotes sur la Tranche Generale.
        ignored = CAL_IGNORED_CODES if is_tg_tranche(name) else ()
        for section in sections:
            entry["sections"][section] = compare_section(
                merged, info.get(section, {}), section, ignored
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
        "tac_codes": set(),
        "cal_all_codes": set(),
        "sheets": {"ccn": [], "bt": [], "tac": [], "cal": [], "e13": []},
    }
    for parsed in parsed_list:
        for key in ("FonctionsNumériséesCCN", "EquipementsTiers",
                    "mnemonics", "tac_codes", "cal_all_codes"):
            merged[key].update(parsed.get(key, set()))
        merged["labels"].extend(parsed.get("labels", []))
        merged["notes"].extend(parsed.get("notes", []))
        merged["has_e13"] = merged["has_e13"] or parsed.get("has_e13", False)
        for key, value in (parsed.get("sheets") or {}).items():
            merged["sheets"].setdefault(key, []).extend(value)
    return merged