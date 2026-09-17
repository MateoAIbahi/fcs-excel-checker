import re
import pandas as pd

from src.utils import (
    normalize,
    clean_code,
    is_section_title,
    section_title_text,
    is_excluded_option,
    is_negative_answer,
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

        # Intitule de rubrique sans prefixe numerique ('Protection câble') :
        # seule la colonne Designation est remplie, le reste de la ligne est
        # vide. Une vraie fonction porte toujours un nom litteral ou un type.
        if not literal and not option:
            labels.append((code, "%s (rubrique)" % "CCN"))
            continue

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

# Regle de selection de l'onglet CAL, commune a toutes les revisions du
# template E9 observees :
#   indice F / H (P.SIM, BELIET) : colonne E = 'X' sur les Base et Options
#   indice J (CASSE)             : 'X' sur les seules Options, Base vides
#   indice K (MATHA)             : colonne D = Base / Oui / non, E = C, Non...
#   ICE ind 3                    : colonne E en texte libre ('Oui TCT',
#                                  'non (car que sur poste blindé)')
# Colonne D (decision) :
#   - vide ou 'non'           -> non retenue
#   - Option / O / Choix / C  -> retenue si la colonne E porte une reponse
#                                positive ('X', 'C', 'Oui ...', 'Téléalarme')
#   - Base, Oui, autre        -> retenue, sauf refus explicite en colonne E
# L'ancienne distinction 'mode marqueur / mode decision' ecartait toutes les
# Base non cochees de l'indice J.
CHOICE_VALUES = {"O", "OPTION", "C", "CHOIX"}

# Une reponse 'non ...' en colonne E ecarte-t-elle aussi une Base ?
# Cas observe : ALTECH (Inc), Base, 'non suite à la FQR 04'. A confirmer par
# ICE ; passer a False pour revenir a 'Base toujours retenue'.
NEGATIVE_EXCLUDES_BASE = True

# Lignes de l'onglet CAL a ignorer (demande ICE) : ce sont les systemes
# eux-memes, pas des fonctions. Correspondance EXACTE : un prefixe ecarterait
# d'autres codes commencant par 'TG'.
CAL_IGNORED_CODES = {"TG", "TGSI"}

# Codes a chercher dans TOUT l'onglet CAL, hors zone des fonctions et sans
# regle de selection : ils portent un bloc (en-tete + sous-lignes) plutot
# qu'une ligne Base/Option.
CAL_WHOLE_SHEET_CODES = {"IFTG"}


def is_retained_choice(decision, selection):
    """Applique la regle de selection de l'onglet CAL (voir ci-dessus)."""
    token = normalize(decision)
    if not token or is_excluded_option(decision) or is_negative_answer(decision):
        return False
    refused = is_excluded_option(selection) or is_negative_answer(selection)
    if token in CHOICE_VALUES:
        return bool(normalize(selection)) and not refused
    if NEGATIVE_EXCLUDES_BASE and refused:
        return False
    return True


CAL_START = "FONCTIONSNUMERISEESDANS"
CAL_STOP = "FONCTIONSOUEQUIPEMENTSINTERFACES"


def _cal_function_rows(df):
    """
    Lignes de la zone des fonctions de l'onglet CAL (entre CAL_START et
    CAL_STOP) portant un code en colonne A. Rend (code, libelle, row).
    """
    started = False
    for _, row in df.iterrows():
        code = clean_code(row.iloc[0]) if len(row) > 0 else None
        label = clean_code(row.iloc[1]) if len(row) > 1 else None
        if label and CAL_STOP in normalize(label):
            return
        if label and CAL_START in normalize(label):
            started = True
            continue
        if started and code:
            yield code, label, row


def extract_cal_sheet(df, decision_col=3, selection_col=4):
    """
    Retourne (functions, labels, all_codes).
    all_codes : tous les codes de la colonne A, sur tout l'onglet, pour les
                recherches de CAL_WHOLE_SHEET_CODES.
    """
    functions, labels = set(), []

    all_codes = set()
    for _, row in df.iterrows():
        code = clean_code(row.iloc[0]) if len(row) > 0 else None
        if code:
            all_codes.add(code)

    for code, label, row in _cal_function_rows(df):
        if normalize(code) in CAL_IGNORED_CODES:
            continue
        decision = clean_code(row.iloc[decision_col]) if decision_col < len(row) else None
        selection = clean_code(row.iloc[selection_col]) if selection_col < len(row) else None
        if is_retained_choice(decision, selection):
            functions.add(code)
            if label:
                labels.append((label, code))

    return functions, labels, all_codes


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

        # Meme regle pour les onglets Basse Tension et TAC : un mnemonique
        # seul sur sa ligne est un intitule de rubrique, pas un equipement.
        if mnemonic and not designation and not option:
            labels.append((mnemonic, "%s (rubrique)" % sheet_name))
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
    # Seuls les onglets exploites sont lus : les onglets 'DOC ...' des
    # nomenclatures DIFB pesent plusieurs dizaines de Mo et ne servent pas.
    # Les autres restent presents (vides) pour la detection du template.
    buckets = classify_sheets(xls.sheet_names)
    wanted = {name for names in buckets.values() for name in names}
    frames = {
        name: (pd.read_excel(xls, sheet_name=name, header=None)
               if name in wanted else pd.DataFrame())
        for name in xls.sheet_names
    }
    return parse_sheet_frames(frames)


def parse_sheet_frames(frames):
    """
    Coeur de l'analyse, commun aux classeurs Excel et aux nomenclatures PDF.
    `frames` : {nom d'onglet: DataFrame sans en-tete}.
    """
    sheet_names = list(frames)
    buckets = classify_sheets(sheet_names)

    result = {
        "is_tg": is_tg_workbook(sheet_names),
        "FonctionsNumériséesCCN": set(),
        "EquipementsTiers": set(),
        "mnemonics": set(),
        "tac_codes": set(),
        "labels": [],
        "skipped_non": set(),
        "sheets": {k: list(v) for k, v in buckets.items()},
        "has_e13": bool(buckets["e13"]),
        "cal_all_codes": set(),
        "ccn_by_sheet": {},
        "notes": [],
    }

    if result["is_tg"]:
        for sheet_name in buckets["cal"]:
            functions, labels, all_codes = extract_cal_sheet(frames[sheet_name])
            result["FonctionsNumériséesCCN"].update(functions)
            result["cal_all_codes"].update(all_codes)
            result["labels"].extend(labels)
        if not buckets["cal"]:
            result["notes"].append("Fichier TG sans onglet CAL.")
        return result

    for sheet_name in buckets["ccn"]:
        functions, labels, skipped = extract_ccn_sheet(frames[sheet_name])
        # Conserve par onglet : les nomenclatures AUT.POS multi-tension
        # rattachent chaque onglet CCN a une tranche differente.
        result["ccn_by_sheet"][sheet_name] = {
            "functions": set(functions), "labels": list(labels),
            "skipped": set(skipped),
        }
        result["FonctionsNumériséesCCN"].update(functions)
        result["labels"].extend(labels)
        result["skipped_non"].update(skipped)

    for sheet_name in buckets["bt"] + buckets["tac"]:
        codes, mnemonics, labels = extract_equipment_sheet(
            frames[sheet_name], sheet_name
        )
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

# Equivalences de codes FCS -> nomenclature, conditionnees au libelle long.
# (section, code FCS, libelle long FCS ou None, code nomenclature)
# Le libelle est compare apres normalisation (casse, accents, ponctuation).
FUNCTION_EQUIVALENCES = [
    ("EquipementsTiers", "UT",
     "Unité de travée différentielle de barres numérique", "PDBN"),
]


def _instance_order(raw):
    """'DDS2' < 'DDS10' : tri naturel, le plus petit indice d'abord."""
    token = normalize(raw)
    match = re.match(r"^(.*?)(\d+)$", token)
    if match:
        return (match.group(1), int(match.group(2)), token)
    return (token, -1, token)


def _find_code(parsed, section, target):
    """Code normalise `target` present tel quel ou sous forme indicee."""
    for raw in parsed.get(section, set()):
        if normalize(raw) == target:
            return raw
    if section == "EquipementsTiers":
        pattern = re.compile(NUMBERED_INSTANCE_RE % re.escape(target))
        for raw in sorted(parsed.get("mnemonics", set()), key=_instance_order):
            if normalize(raw) == target or pattern.match(normalize(raw)):
                return raw
    return None


def resolve_equivalence(parsed, section, code, long_label):
    """Retourne le code nomenclature equivalent trouve, ou None."""
    for eq_section, fcs_code, fcs_label, nom_code in FUNCTION_EQUIVALENCES:
        if eq_section != section or normalize(fcs_code) != normalize(code):
            continue
        if fcs_label is not None and normalize(fcs_label) != normalize(long_label):
            continue
        found = _find_code(parsed, section, normalize(nom_code))
        if found:
            return found
    return None


def resolve_function(parsed, section, code, long_label=None):
    """
    Cherche `code` dans l'Excel selon une cascade de methodes, de la plus
    sure a la plus permissive. Retourne (trouve, methode, preuve).
    """
    target = normalize(code)

    direct = {normalize(c): c for c in parsed.get(section, set())}
    if target in direct:
        return True, "code", direct[target]

    if section == "FonctionsNumériséesCCN" and target in CAL_WHOLE_SHEET_CODES:
        for raw in parsed.get("cal_all_codes", set()):
            if normalize(raw) == target:
                return True, "onglet_cal_complet", raw

    equivalent = resolve_equivalence(parsed, section, code, long_label)
    if equivalent:
        return True, "equivalence", equivalent

    if section == "EquipementsTiers":
        # 'DIFC' present sous la forme 'DIFC11', 'DDS' sous 'DDS1'
        # Parcours trie : un set n'a pas d'ordre stable d'une execution a
        # l'autre, et 'DDS' tombait tantot sur 'DDS1', tantot sur 'DDS2'.
        pattern = re.compile(NUMBERED_INSTANCE_RE % re.escape(target))
        for raw in sorted(parsed.get("mnemonics", set()), key=_instance_order):
            if pattern.match(normalize(raw)):
                return True, "mnemonique_indice", raw

        if long_label:
            match = best_label_match(long_label, parsed.get("labels", []))
            if match:
                context, text, score = match
                return True, "libelle_long", "%s ~ %s (%.2f)" % (text, context, score)

    return False, None, None
