"""
Association fichier de nomenclature <-> tranche FCS.

Principe (corrigé) :
  1. Source de vérité = cellule "Codification cellule DPC²" de l'onglet page de
     garde. Elle contient le LibelléCourtTranche du FCS.
  2. Le nom de fichier ne sert plus qu'à un contrôle de cohérence (garde-fou),
     jamais à décider.
  3. La Tranche Générale a un template différent (.xls, onglet "PdG ") et suit
     un chemin de détection dédié.
  4. Aucune tranche ne peut être attribuée deux fois : les collisions sont
     signalées et laissées non résolues.
"""

import re
import unicodedata

# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def normalize_name(value):
    """MAJUSCULES, sans accents, sans séparateurs. '4CBO.1' -> '4CBO1'."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]", "", text.upper())


# Un meme radical s'ecrit differemment selon la source : 'AUT.POS' dans les
# nomenclatures, 'AUT.POST' pour la tranche 0 kV de certains FCS (MAUGE).
RADICAL_ALIASES = {"AUTPOST": "AUTPOS"}


def canonical_radical(radical):
    return RADICAL_ALIASES.get(radical, radical)


def canonical_code(code_norm):
    """'AUTPOST' -> 'AUTPOS', '6AUTPOST' -> '6AUTPOS' (codes normalises)."""
    for alias, canonical in RADICAL_ALIASES.items():
        if code_norm.endswith(alias):
            return code_norm[:-len(alias)] + canonical
    return code_norm


def strip_site_prefix(code_norm, site_norms):
    """'MATHA6TR642' -> '6TR642' (les rédacteurs préfixent parfois le site)."""
    for site_norm in sorted(site_norms or (), key=len, reverse=True):
        if site_norm and code_norm.startswith(site_norm) and len(code_norm) > len(site_norm):
            return code_norm[len(site_norm):]
    return code_norm


def strip_tranche_index(value):
    """
    Retire l'indice de tranche DPC2 : '3CBO.1' -> '3CBO', '6ZHUBY.1' -> '6ZHUBY'.
    A appliquer AVANT normalisation (le point est le separateur significatif).
    N'est utilise qu'en repli, jamais en cle primaire.
    """
    return re.sub(r"\.\d+\s*$", "", str(value or "").strip())


# --------------------------------------------------------------------------
# Lecture de la page de garde
# --------------------------------------------------------------------------

PDG_SHEET_HINTS = ("PAGEDEGARDE", "PDG")
CODIFICATION_LABEL = "CODIFICATIONCELLULE"   # "Codification cellule DPC²"


def find_page_de_garde(sheet_names):
    """Tolère 'Page de garde', 'PdG ' (espace final), casse variable."""
    for name in sheet_names:
        if normalize_name(name) in PDG_SHEET_HINTS:
            return name
    return None


def read_codification(rows):
    """
    rows : itérable de tuples de valeurs (openpyxl values_only=True) de la
    page de garde. Retourne la valeur brute de 'Codification cellule DPC²'.
    """
    for row in rows:
        if not row or row[0] is None:
            continue
        if CODIFICATION_LABEL in normalize_name(row[0]):
            for cell in row[1:]:
                if cell not in (None, ""):
                    return str(cell)
    return None


def clean_codification(raw, site_norms=()):
    """
    '4CBO.1 - DEP 90kV CONTROLE BARRE...' -> '4CBO1'
    'MATHA 6TR642'                        -> '6TR642'
    'MATHA-4TR412'                        -> '4TR412'
    """
    if not raw:
        return ""
    head = re.split(r"\s+-\s+", str(raw))[0]
    return strip_site_prefix(normalize_name(head), site_norms)


def build_tranche_index(tranches, site_norms=()):
    """
    Deux index :
      - exact   : cle = nom normalise complet          ('3CBO1' -> '3CBO.1')
      - sans_indice : cle = nom sans '.N' normalise    ('3CBO'  -> '3CBO.1')
    Les cles ambigues du second index (2 tranches y aboutissent) sont retirees :
    mieux vaut ne pas conclure que se tromper.
    """
    exact = {}
    loose = {}
    for tranche in tranches:
        exact[canonical_code(strip_site_prefix(normalize_name(tranche), site_norms))] = tranche
        key = canonical_code(strip_site_prefix(
            normalize_name(strip_tranche_index(tranche)), site_norms))
        loose.setdefault(key, []).append(tranche)
    loose = {k: v[0] for k, v in loose.items() if len(v) == 1}
    return exact, loose


# --------------------------------------------------------------------------
# Tranche Générale
# --------------------------------------------------------------------------

TG_TRANCHE_HINTS = ("TGENE", "TRANCHEGENERALE", "E9")


def looks_like_tg(sheet_names, pdg_rows=None):
    """
    Le fichier TG ne porte pas de 'Codification cellule DPC²'.
    On le reconnaît par : présence d'un onglet CAL + mention TRANCHE GENERALE
    ou E9 quelque part sur la page de garde.
    """
    has_cal = any(normalize_name(n) == "CAL" for n in sheet_names)
    if not has_cal:
        return False
    if pdg_rows is None:
        return True
    for row in pdg_rows:
        for cell in row or ():
            if cell is None:
                continue
            token = normalize_name(cell)
            if token in TG_TRANCHE_HINTS or "TRANCHEGENERALE" in token:
                return True
    return has_cal


def find_tg_tranche(tranches):
    """Retrouve la tranche générale dans la liste FCS ('T.GENE', 'TG', ...)."""
    for tranche in tranches:
        if normalize_name(tranche) in TG_TRANCHE_HINTS:
            return tranche
    return None


# --------------------------------------------------------------------------
# Repli : identification par "Nom de cellule InfoPoste"
# --------------------------------------------------------------------------
# Certains sites (COMPI) laissent "Codification cellule DPC2" vide sur la
# totalite des nomenclatures. Le seul identifiant restant est le nom de
# cellule InfoPoste, du type "L31RESER - DEP 63kV N0 1 RESERVE".

INFOPOSTE_LABEL = "NOMDECELLULEINFOPOSTE"
TYPE_TRANCHE_LABEL = "TYPEDETRANCHE"
CODE_REFERENCE_LABEL = "CODEREFERENCE"

# Prefixes de code cellule -> radical de tranche DPC2.
# Reprend les correspondances metier connues (BC -> Couplage, Cxxx -> COND,
# PDBN -> differentielle de barres) et les complete.
CODE_FAMILIES = [
    (re.compile(r"^SS\d*[.\-_]?(\d+)$", re.I), "SEC", 1),
    (re.compile(r"^BC(\d)(\d+)$", re.I), "COUPL", 2),
    (re.compile(r"^AU(\d)(\d+)$", re.I), "AUTPOS", None),
    (re.compile(r"^PDBN\w*$", re.I), "DIFB", None),
    (re.compile(r"^C(\d{3})$", re.I), "COND", 1),
    (re.compile(r"^CBO\w*$", re.I), "CBO", None),
]

TG_CODES = {"TGE", "TG", "TGENE"}
TG_TYPE_CODES = {"009"}
TG_REFERENCES = {"E9"}


def read_field(rows, label):
    """Lit une valeur de la page de garde a partir du libelle en colonne A."""
    target = normalize_name(label)
    for row in rows:
        if not row or row[0] is None:
            continue
        if target in normalize_name(row[0]):
            for value in row[1:]:
                text = None if value is None else str(value).strip()
                if text and text.lower() != "nan":
                    return text
    return None


def split_tranche_name(name):
    """
    Decoupe un nom de tranche en (prefixe tension, radical, indice) :
        '3CBO..1'  -> ('3', 'CBO',   '1')
        '3ZCNR6.1' -> ('3', 'ZCNR6', '1')   <- le radical peut finir par un chiffre
        '3TR311'   -> ('3', 'TR',    '311')
        '4AUT.POS' -> ('4', 'AUTPOS', '')   <- le point n'est pas un separateur d'indice
        '6COUPL'   -> ('6', 'COUPL', '')
    Le point ne separe un indice que si ce qui le suit est numerique : sinon il
    fait partie du radical, comme dans 'AUT.POS'.
    """
    prefix, radical, index = _split_tranche_name(name)
    return prefix, canonical_radical(radical), index


def _split_tranche_name(name):
    raw = str(name or "").strip()
    head = re.match(r"^(\d)(.*)$", raw)
    if not head:
        return None, normalize_name(raw), ""

    prefix, rest = head.group(1), head.group(2)

    if "." in rest:
        base, _, tail = rest.rpartition(".")
        if tail.isdigit():
            return prefix, normalize_name(base), tail

    match = re.match(r"^([A-Z]+?)(\d*)$", normalize_name(rest))
    if match:
        return prefix, match.group(1), match.group(2)
    return prefix, normalize_name(rest), ""


def voltage_prefix(text, voltage_prefixes):
    """'DEP 63kV N0 1 RESERVE' -> '3', via la table deduite du FCS."""
    if not text or not voltage_prefixes:
        return None
    for found in re.findall(r"(\d+)\s*kV", str(text), re.I):
        prefix = voltage_prefixes.get("%skV" % found)
        if prefix:
            return prefix
    return None


def free_index(text):
    """Indice de section : chiffre isole, hors tensions. 'BARRES 3 63kV' -> '3'."""
    if not text:
        return ""
    cleaned = re.sub(r"\d+\s*kV", " ", str(text), flags=re.I)
    cleaned = re.sub(r"\bN0?\b", " ", cleaned, flags=re.I)
    found = re.findall(r"(?<![A-Za-z0-9])(\d+)(?![A-Za-z0-9])", cleaned)
    return found[0] if found else ""


def decode_infoposte(raw, voltage_prefixes):
    """
    Retourne (prefixe_tension, radical, indice) ou (None, None, None).
      'L31RESER - DEP 63kV ...'  -> ('3', 'RESER', '1')
      'Y63161 - DEP 225kV ...'   -> ('6', 'TR', '631')
      'SS1.12 - SECT ... 63kV'   -> ('3', 'SEC', '12')
      'CBO - CONTROLES BARRES 3 63kV' -> ('3', 'CBO', '3')
    """
    if not raw:
        return None, None, None
    code, _, description = str(raw).partition(" - ")
    code = code.strip()
    token = normalize_name(code)
    prefix_from_text = voltage_prefix(description or raw, voltage_prefixes)

    # Liaison : L{tension}{indice}{NOM}
    match = re.match(r"^L(\d)(\d)([A-Z0-9]+)$", token)
    if match:
        return match.group(1), match.group(3), match.group(2)

    # Transformateur : Y{numero}{tension}{indice}
    match = re.match(r"^Y(\d{3})(\d)(\d)$", token)
    if match:
        return match.group(2), "TR", match.group(1)

    for pattern, radical, index_group in CODE_FAMILIES:
        match = pattern.match(code)
        if not match:
            continue
        if radical == "AUTPOS":
            return match.group(1), radical, ""
        if radical == "COUPL":
            return match.group(1), radical, match.group(2)
        index = match.group(index_group) if index_group else free_index(description)
        return prefix_from_text, radical, index

    return None, None, None


def match_by_infoposte(raw, tranches, voltage_prefixes):
    """Resout un nom de cellule InfoPoste vers une tranche, ou None."""
    prefix, radical, index = decode_infoposte(raw, voltage_prefixes)
    if not radical:
        return None

    candidates = []
    for tranche in tranches:
        t_prefix, t_radical, t_index = split_tranche_name(tranche)
        if prefix and t_prefix and t_prefix != prefix:
            continue
        if t_radical != radical:
            continue
        candidates.append((tranche, t_index))

    if len(candidates) == 1:
        return candidates[0][0]
    if index:
        exact = [name for name, t_index in candidates if t_index == index]
        if len(exact) == 1:
            return exact[0]
    return None


def looks_like_tg_page(rows):
    """Reconnait la Tranche Generale depuis la page de garde seule."""
    infoposte = read_field(rows, INFOPOSTE_LABEL)
    if infoposte:
        code = normalize_name(str(infoposte).partition(" - ")[0])
        if code in TG_CODES:
            return True
    type_tranche = read_field(rows, TYPE_TRANCHE_LABEL)
    if type_tranche and str(type_tranche).strip()[:3] in TG_TYPE_CODES:
        return True
    reference = read_field(rows, CODE_REFERENCE_LABEL)
    if reference and normalize_name(reference) in TG_REFERENCES:
        return True
    return False


# --------------------------------------------------------------------------
# Desambiguisation des tranches transformateur
# --------------------------------------------------------------------------
# Deux nomenclatures transformateur peuvent porter des noms de cellule tres
# proches et aboutir sur la meme tranche. Le "Type de tranche" de la page de
# garde les separe sans ambiguite :
#   003 - Tranche transformateur THT/HT      -> xTRx3x  (ex. 6TR631)
#   013 - Tranche raccordement transformateur -> xTRx1x  (ex. 6TR611)
# Le chiffre discriminant est celui du milieu du numero de transformateur.

TRANSFORMER_TYPE_DIGIT = {"003": "3", "013": "1"}


def transformer_digit(type_tranche):
    """'013-Tranche raccordement transformateur ...' -> '1'."""
    if not type_tranche:
        return None
    head = str(type_tranche).strip()[:3]
    return TRANSFORMER_TYPE_DIGIT.get(head)


def transformer_number_from_filename(filename):
    """'14-SENAR_Y61161_1.1_241220.xlsx' -> '611'."""
    match = re.search(r"Y(\d{3})\d?\d?", str(filename), re.IGNORECASE)
    return match.group(1) if match else None


def disambiguate_transformer(filename, match, tranches):
    """
    Tente de reattribuer une nomenclature transformateur prise dans une
    collision. Retourne un nom de tranche ou None.
    """
    target = match.get("tranche") or match.get("tranche_visee")
    if not target:
        return None
    prefix, radical, _ = split_tranche_name(target)
    if radical != "TR":
        return None

    candidates = []
    for tranche in tranches:
        t_prefix, t_radical, t_index = split_tranche_name(tranche)
        if t_radical == "TR" and t_prefix == prefix and t_index:
            candidates.append((tranche, t_index))
    if len(candidates) < 2:
        return None

    # 1. Le nom de fichier porte le numero de transformateur (Y611 / Y631).
    number = transformer_number_from_filename(filename)
    if number:
        exact = [name for name, index in candidates if index == number]
        if len(exact) == 1:
            return exact[0]

    # 2. A defaut, le type de tranche de la page de garde.
    digit = transformer_digit(match.get("type_tranche"))
    if digit:
        exact = [name for name, index in candidates
                 if len(index) >= 2 and index[1] == digit]
        if len(exact) == 1:
            return exact[0]

    return None


# --------------------------------------------------------------------------
# Garde-fou sur le nom de fichier
# --------------------------------------------------------------------------

FILENAME_FAMILY_HINTS = [
    (r"PDBN", ("DIFB", "PDBN")),
    (r"\bBC\b|_BC", ("COUPL",)),
    (r"C\d{3}", ("COND",)),
]


def filename_consistency_warning(filename, tranche):
    """Retourne un message si le nom de fichier contredit la tranche retenue."""
    file_norm = normalize_name(filename)
    tranche_norm = normalize_name(tranche)
    for pattern, expected_fragments in FILENAME_FAMILY_HINTS:
        if re.search(pattern, filename, re.IGNORECASE):
            if any(frag in tranche_norm for frag in expected_fragments):
                return None  # garde-fou satisfait, pas d'alerte generique
            return (
                f"Le nom de fichier suggere la famille {expected_fragments[0]} "
                f"mais la page de garde indique '{tranche}'. "
                f"Page de garde retenue."
            )
    if tranche_norm and tranche_norm not in file_norm:
        base = re.sub(r"\d+$", "", tranche_norm)
        if not base or base not in file_norm:
            return (
                f"Nom de fichier '{filename}' sans rapport evident avec la "
                f"tranche '{tranche}' (association issue de la page de garde)."
            )
    return None


# --------------------------------------------------------------------------
# Point d'entree
# --------------------------------------------------------------------------

def match_workbook_to_tranche(filename, sheet_names, pdg_rows, tranches,
                              site=None, voltage_prefixes=None):
    """
    site             : str ou iterable de str (CodeNationalSite ET NomSite).
    voltage_prefixes : {'63kV': '3', '225kV': '6'}, deduit du FCS. Sert au
                       repli par nom de cellule InfoPoste.
    Retourne un dict :
      {'tranche': str|None, 'method': str, 'raw': str|None, 'warning': str|None}
    """
    if site is None:
        site_norms = ()
    elif isinstance(site, str):
        site_norms = (normalize_name(site),)
    else:
        site_norms = tuple(normalize_name(s) for s in site if s)
    pdg_rows = list(pdg_rows or [])
    context = {
        "type_tranche": read_field(pdg_rows, TYPE_TRANCHE_LABEL),
        "description": read_field(pdg_rows, "DESCRIPTION"),
    }

    raw = read_codification(pdg_rows)
    if raw:
        exact, loose = build_tranche_index(tranches, site_norms)
        code = canonical_code(clean_codification(raw, site_norms))

        tranche = exact.get(code)
        method = "page_de_garde"
        warning = None

        if tranche is None:
            # repli : indice de tranche absent d'un cote ou de l'autre
            head = re.split(r"\s+-\s+", str(raw))[0]
            loose_code = canonical_code(strip_site_prefix(
                normalize_name(strip_tranche_index(head)), site_norms
            ))
            tranche = loose.get(loose_code) or loose.get(code)
            if tranche:
                method = "page_de_garde_sans_indice"
                warning = (
                    f"Codification '{raw}' rapprochee de la tranche '{tranche}' "
                    f"en ignorant l'indice de tranche."
                )

        if tranche:
            result = {
                "tranche": tranche,
                "method": method,
                "raw": raw,
                "warning": warning or filename_consistency_warning(filename, tranche),
            }
            result.update(context)
            return result
        result = {
            "tranche": None,
            "method": "page_de_garde_sans_correspondance",
            "raw": raw,
            "warning": f"Codification '{raw}' absente du FCS.",
        }
        result.update(context)
        return result

    # Repli 1 : nom de cellule InfoPoste (codification DPC2 vide sur certains sites)
    infoposte = read_field(pdg_rows, INFOPOSTE_LABEL)
    if infoposte:
        tranche = match_by_infoposte(infoposte, tranches, voltage_prefixes)
        if tranche:
            result = {
                "tranche": tranche,
                "method": "nom_cellule_infoposte",
                "raw": infoposte,
                "warning": ("Codification DPC2 absente : association deduite du "
                            "nom de cellule InfoPoste '%s'." % infoposte),
            }
            result.update(context)
            return result

    if looks_like_tg(sheet_names, pdg_rows) or looks_like_tg_page(pdg_rows):
        tranche = find_tg_tranche(tranches)
        if tranche:
            result = {"tranche": tranche, "method": "tranche_generale",
                      "raw": None, "warning": None}
        else:
            result = {"tranche": None, "method": "tranche_generale", "raw": None,
                      "warning": "Fichier TG detecte mais absent du FCS."}
        result.update(context)
        return result

    result = {"tranche": None, "method": "echec", "raw": infoposte,
              "warning": ("Ni codification DPC2 ni nom de cellule InfoPoste "
                          "exploitable sur la page de garde.")}
    result.update(context)
    return result


def resolve_collisions(results, tranches=None):
    """
    results : {filename: match_dict}
    Deux fichiers sur la meme tranche = anomalie. On les remet en non resolus
    plutot que d'en choisir un au hasard.
    """
    by_tranche = {}
    for filename, match in results.items():
        if match.get("tranche"):
            by_tranche.setdefault(match["tranche"], []).append(filename)

    tranches_ref = list(tranches) if tranches else list(by_tranche)

    for tranche, filenames in by_tranche.items():
        if len(filenames) > 1:
            # Tranches transformateur : le type de tranche ou le numero porte
            # par le nom de fichier permet souvent de les separer.
            reassigned = {}
            for filename in filenames:
                better = disambiguate_transformer(
                    filename, results[filename], tranches_ref
                )
                if better:
                    reassigned[filename] = better
            if (len(reassigned) == len(filenames)
                    and len(set(reassigned.values())) == len(filenames)):
                for filename, better in reassigned.items():
                    results[filename]["tranche"] = better
                    results[filename]["method"] = "desambiguisation_transformateur"
                    results[filename]["warning"] = (
                        "Plusieurs nomenclatures visaient '%s' ; celle-ci a ete "
                        "rattachee a '%s' d'apres son type de tranche." 
                        % (tranche, better)
                    )
                continue

            for filename in filenames:
                results[filename]["tranche"] = None
                results[filename]["method"] = "collision"
                # On conserve la cible visee pour que le rapport distingue
                # "aucune nomenclature" de "plusieurs nomenclatures en conflit".
                results[filename]["tranche_visee"] = tranche
                results[filename]["warning"] = (
                    f"Conflit : {', '.join(filenames)} pointent tous vers "
                    f"'{tranche}'. Association a trancher manuellement."
                )
    return results