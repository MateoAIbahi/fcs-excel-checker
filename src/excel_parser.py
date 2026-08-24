import re
import pandas as pd

from src.utils import (
    normalize,
    clean_code,
    is_section_title,
    section_title_text,
    is_excluded_option,
    is_tg_workbook,
    best_label_match,
)


# --------------------------------------------------------------------------
# Reperage des en-tetes et des onglets
# --------------------------------------------------------------------------

def find_header_row(df, required, limit=30):
    """
    Cherche la premiere ligne contenant TOUS les en-tetes normalises de
    `required`. Retourne (index_ligne, {en_tete_normalise: index_colonne})
    pour TOUTES les colonnes de cette ligne, pas seulement les requises.
    """
    required = [normalize(r) for r in required]
    for index, row in df.head(limit).iterrows():
        values = [normalize(v) for v in row.values]
        if all(r in values for r in required):
            columns = {}
            for position, value in enumerate(values):
                if value and value not in columns:
                    columns[value] = position
            return index, columns
    return None, {}


def cell(row, columns, key):
    index = columns.get(normalize(key))
    if index is None or index >= len(row):
        return None
    return clean_code(row.iloc[index])


def classify_sheets(sheet_names):
    """
    Repartit les onglets. Tolere les prefixes numeriques et les suffixes
    ('4- CCN 63kV', '2-Basse Tension Cable Unique', '3-TAC').
    """
    buckets = {"ccn": [], "bt": [], "tac": [], "cal": [], "e13": []}
    for name in sheet_names:
        token = normalize(name)
        if token.startswith("DOC"):
            continue          # onglets d'illustration, jamais de donnees
        if "SOUSTRANCHE" in token and "E13" in token:
            buckets["e13"].append(name)
        elif token == "CAL":
            buckets["cal"].append(name)
        elif "CCN" in token:
            buckets["ccn"].append(name)
        elif "BASSETENSION" in token:
            buckets["bt"].append(name)
        elif "TAC" in token:
            buckets["tac"].append(name)
    return buckets


# --------------------------------------------------------------------------
# Onglet CCN
# --------------------------------------------------------------------------

def extract_ccn_sheet(df):
    """
    Colonnes : Designation (mnemonique) | Nom Literal | Type option | ...
    Les lignes marquees 'NON' en Type option ne sont PAS retenues : les
    inclure produisait de fausses entrees 'presentes dans l'Excel'.
    """
    functions, labels, skipped = set(), [], set()

    header_row, columns = find_header_row(df, ["Designation"])
    if header_row is None:
        return functions, labels, skipped

    for _, row in df.iloc[header_row + 1:].iterrows():
        code = cell(row, columns, "Designation")
        if not code or is_section_title(code):
            continue

        option_index = columns.get("TYPEOPTION")
        option = clean_code(row.iloc[option_index]) if option_index is not None and option_index < len(row) else None

        literal_index = columns.get("NOMLITERAL")
        literal = clean_code(row.iloc[literal_index]) if literal_index is not None and literal_index < len(row) else None
        if literal:
            labels.append((literal, code))

        if is_excluded_option(option):
            skipped.add(code)
            continue
        functions.add(code)

    return functions, labels, skipped


# --------------------------------------------------------------------------
# Onglet CAL (Tranche Generale)
# --------------------------------------------------------------------------

# Colonne "Choix des fonctions" : Base / Option = O / Choix = C.
# Une fonction en Option ou en Choix n'est retenue que si la colonne
# "Selection" en face est renseignee ; une fonction Base l'est toujours.
CHOICE_VALUES = {"O", "OPTION", "C", "CHOIX"}


def is_retained_choice(decision, selection):
    """Applique la regle de la colonne de choix de l'onglet CAL."""
    token = normalize(decision)
    if not token or is_excluded_option(decision):
        return False
    if token in CHOICE_VALUES:
        return bool(normalize(selection)) and not is_excluded_option(selection)
    return True


CAL_START = "FONCTIONSNUMERISEESDANS"
CAL_STOP = "FONCTIONSOUEQUIPEMENTSINTERFACES"


def detect_cal_mode(df, mark_col=4):
    """
    Deux revisions du template E9 coexistent :
      - indice H : colonne E = 'Options retenues par DI', marquee 'X'
      - indice K : colonne E = 'Selection', valeurs 'C', 'Telealarme', 'Non'
                   -> c'est la colonne D ('Choix des fonctions') qui decide
    On tranche sur la donnee, pas sur le libelle d'en-tete, qui varie.
    """
    for _, row in df.iterrows():
        if mark_col < len(row) and normalize(row.iloc[mark_col]) == "X":
            return "marqueur"
    return "decision"


def extract_cal_sheet(df, decision_col=3, mark_col=4):
    functions, labels = set(), []
    mode = detect_cal_mode(df, mark_col)
    started = False

    for _, row in df.iterrows():
        code = clean_code(row.iloc[0]) if len(row) > 0 else None
        label = clean_code(row.iloc[1]) if len(row) > 1 else None

        if label and CAL_STOP in normalize(label):
            break
        if label and CAL_START in normalize(label):
            started = True
            continue
        if not started or not code:
            continue

        decision = clean_code(row.iloc[decision_col]) if decision_col < len(row) else None
        mark = clean_code(row.iloc[mark_col]) if mark_col < len(row) else None

        if mode == "marqueur":
            retained = bool(mark) and not is_excluded_option(mark)
        else:
            retained = is_retained_choice(decision, mark)

        if retained:
            functions.add(code)
            if label:
                labels.append((label, code))

    return functions, labels, mode


# --------------------------------------------------------------------------
# Onglets Basse Tension / TAC (EquipementsTiers)
# --------------------------------------------------------------------------

SUBFUNCTION_RE = re.compile(r"^\s*(.+?)\s*-\s*Fonctions?\s+(.+?)\s*$", re.IGNORECASE)

# 'Fonctions utilisees: ... (DSARB, TDPCB et TPAPB dans DPC2)'
DPC_BLOCK_RE = re.compile(r"\(([^)]*?)\s+dans\s+DPC", re.IGNORECASE)
# 'Em.1 : VER   Rec.1 : VER'
COLON_CODE_RE = re.compile(r":\s*([A-Za-z0-9_.\-]+)")


def extract_equipment_sheet(df, sheet_name):
    """
    Retourne (codes, mnemonics, labels).
      codes     : codes directement exploitables comme LibelleCourtObjetFonction
      mnemonics : tous les mnemoniques colonne A (sert au repli 'DIFC' -> 'DIFC11')
      labels    : titres de section + designations, pour le repli libelle long
    """
    codes, mnemonics, labels = set(), set(), []

    header_row, columns = find_header_row(df, ["Mnemonique"])
    if header_row is None:
        return codes, mnemonics, labels

    mnemonic_col = columns["MNEMONIQUE"]
    designation_col = columns.get("DESIGNATION", mnemonic_col + 1)
    option_col = columns.get("TYPEOPTION", columns.get("FCTTAC"))
    free_text_cols = [
        columns[key] for key in ("FCTTAC", "COMMENTAIRESDI") if key in columns
    ]

    for _, row in df.iloc[header_row + 1:].iterrows():
        mnemonic = clean_code(row.iloc[mnemonic_col]) if mnemonic_col < len(row) else None
        designation = clean_code(row.iloc[designation_col]) if designation_col < len(row) else None
        option = clean_code(row.iloc[option_col]) if option_col is not None and option_col < len(row) else None

        if mnemonic and is_section_title(mnemonic):
            labels.append((section_title_text(mnemonic), f"{sheet_name} (section)"))
            continue

        if mnemonic:
            mnemonics.add(mnemonic)
            if not is_excluded_option(option):
                codes.add(mnemonic)

        if designation:
            labels.append((designation, f"{sheet_name} (designation)"))
            match = SUBFUNCTION_RE.match(designation)
            if match and not is_excluded_option(option):
                # 'PXmulti-Fonction PX' -> 'PXmulti-PX'
                codes.add("%s-%s" % (match.group(1), match.group(2)))

        # Colonnes de texte libre : 'Fct TAC' et 'Commentaires DI'
        for index in free_text_cols:
            text = clean_code(row.iloc[index]) if index < len(row) else None
            if not text:
                continue
            labels.append((text, f"{sheet_name} (texte libre)"))
            for block in DPC_BLOCK_RE.findall(text):
                for part in re.split(r",|\bet\b", block):
                    part = part.strip()
                    if part:
                        codes.add(part)
            if "dans DPC" not in text:
                for found in COLON_CODE_RE.findall(text):
                    if 2 <= len(found) <= 12:
                        codes.add(found)

    return codes, mnemonics, labels


# --------------------------------------------------------------------------
# Point d'entree
# --------------------------------------------------------------------------

def load_workbook_context(file, max_rows=30):
    """
    Lit un classeur une seule fois et renvoie ce dont le matcher a besoin :
    (objet ExcelFile, noms d'onglets, lignes de la page de garde).

    Passe par pandas pour traiter .xls et .xlsx de la meme facon (le .xls
    des fichiers TG exige xlrd>=2.0.1). Les cellules vides remontent en None
    et non en NaN, sinon le matcher lit la chaine 'nan' comme une valeur.
    """
    from src.tranche_matcher import find_page_de_garde

    xls = pd.ExcelFile(file)
    sheet_names = list(xls.sheet_names)

    page = find_page_de_garde(sheet_names)
    if not page:
        return xls, sheet_names, []

    frame = pd.read_excel(xls, sheet_name=page, header=None, nrows=max_rows)
    rows = []
    for row in frame.itertuples(index=False):
        rows.append(tuple(
            None if (value is None or (isinstance(value, float) and pd.isna(value)))
            else value
            for value in row
        ))
    return xls, sheet_names, rows


def parse_excel_file(file, filename=None):
    xls = file if isinstance(file, pd.ExcelFile) else pd.ExcelFile(file)
    buckets = classify_sheets(xls.sheet_names)

    result = {
        "is_tg": is_tg_workbook(xls.sheet_names),
        "FonctionsNumériséesCCN": set(),
        "EquipementsTiers": set(),
        "mnemonics": set(),
        "tac_codes": set(),
        "labels": [],
        "skipped_non": set(),
        "sheets": {k: list(v) for k, v in buckets.items()},
        "has_e13": bool(buckets["e13"]),
        "notes": [],
    }

    if result["is_tg"]:
        for sheet_name in buckets["cal"]:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
            functions, labels, mode = extract_cal_sheet(df)
            result["FonctionsNumériséesCCN"].update(functions)
            result["labels"].extend(labels)
            result["notes"].append("Onglet %s lu en mode '%s'." % (sheet_name, mode))
        if not buckets["cal"]:
            result["notes"].append("Fichier TG sans onglet CAL.")
        return result

    for sheet_name in buckets["ccn"]:
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        functions, labels, skipped = extract_ccn_sheet(df)
        result["FonctionsNumériséesCCN"].update(functions)
        result["labels"].extend(labels)
        result["skipped_non"].update(skipped)

    for sheet_name in buckets["bt"] + buckets["tac"]:
        df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        codes, mnemonics, labels = extract_equipment_sheet(df, sheet_name)
        result["EquipementsTiers"].update(codes)
        result["mnemonics"].update(mnemonics)
        result["labels"].extend(labels)
        if sheet_name in buckets["tac"]:
            # Sert au rapport : on masque les lignes 'TAC-Nx' des lors qu'une
            # fonction a bien ete identifiee via cet onglet.
            result["tac_codes"].update(codes - mnemonics)

    if not buckets["ccn"]:
        result["notes"].append("Aucun onglet CCN dans ce fichier.")
    if not buckets["bt"] and not buckets["tac"]:
        result["notes"].append("Ni onglet Basse Tension ni onglet TAC.")

    return result


# --------------------------------------------------------------------------
# Resolution d'un ObjetFonction du FCS dans l'Excel
# --------------------------------------------------------------------------

NUMBERED_INSTANCE_RE = "^%s\\d+$"


def resolve_function(parsed, section, code, long_label=None):
    """
    Cherche `code` dans l'Excel selon une cascade de methodes, de la plus
    sure a la plus permissive. Retourne (trouve, methode, preuve).
    """
    target = normalize(code)

    direct = {normalize(c): c for c in parsed.get(section, set())}
    if target in direct:
        return True, "code", direct[target]

    if section == "EquipementsTiers":
        # 'DIFC' present sous la forme 'DIFC11', 'DDS' sous 'DDS1'
        pattern = re.compile(NUMBERED_INSTANCE_RE % re.escape(target))
        for raw in parsed.get("mnemonics", set()):
            if pattern.match(normalize(raw)):
                return True, "mnemonique_indice", raw

        if long_label:
            match = best_label_match(long_label, parsed.get("labels", []))
            if match:
                context, text, score = match
                return True, "libelle_long", "%s ~ %s (%.2f)" % (text, context, score)

    return False, None, None