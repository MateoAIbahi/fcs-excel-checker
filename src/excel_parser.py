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

def extract_ccn_sheet(df, struck=()):
    """
    Colonnes : Designation (mnemonique) | Nom Literal | Type option | ...
    Les lignes marquees 'NON' en Type option ne sont PAS retenues : les
    inclure produisait de fausses entrees 'presentes dans l'Excel'.
    `struck` : index des lignes barrees, ecartees comme non retenues.
    """
    functions, labels, skipped = set(), [], set()

    header_row, columns = find_header_row(df, ["Designation"])
    if header_row is None:
        return functions, labels, skipped

    for index, row in df.iloc[header_row + 1:].iterrows():
        if index in struck:
            continue
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

# Une reponse 'non ...' en colonne E ecarte aussi une Base : confirme par
# ICE en septembre 2026 (cas ALTECH (Inc), Base, 'non suite à la FQR 04').
NEGATIVE_EXCLUDES_BASE = True

# Lignes de l'onglet CAL a ignorer (demande ICE) : ce sont les systemes
# eux-memes, pas des fonctions. Correspondance EXACTE : un prefixe ecarterait
# d'autres codes commencant par 'TG'.
CAL_IGNORED_CODES = {"TG", "TGSI"}

# Codes portant un BLOC dans l'onglet CAL (une ligne d'en-tete, puis des
# sous-lignes sans code) plutot qu'une ligne Base/Option, et cherches dans
# tout l'onglet, hors zone des fonctions. Le bloc compte comme retenu si au
# moins une de ses sous-lignes l'est, au sens de is_retained_choice
# (demande ICE : "une sous-ligne doit etre cochee").
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
    CAL_STOP) portant un code en colonne A. Rend (index, code, libelle, row).
    """
    started = False
    for index, row in df.iterrows():
        code = clean_code(row.iloc[0]) if len(row) > 0 else None
        label = clean_code(row.iloc[1]) if len(row) > 1 else None
        if label and CAL_STOP in normalize(label):
            return
        if label and CAL_START in normalize(label):
            started = True
            continue
        if started and code:
            yield index, code, label, row


def _cal_blocks(df, struck=(), decision_col=3, selection_col=4):
    """
    Codes de CAL_WHOLE_SHEET_CODES dont le bloc compte au moins une
    sous-ligne retenue, cherches sur tout l'onglet.
    """
    retained = set()
    rows = list(df.iterrows())
    for position, (_, row) in enumerate(rows):
        code = clean_code(row.iloc[0]) if len(row) > 0 else None
        if not code or normalize(code) not in CAL_WHOLE_SHEET_CODES:
            continue
        for sub_index, sub in rows[position + 1:]:
            if len(sub) > 0 and clean_code(sub.iloc[0]):
                break                      # ligne de code suivante : fin du bloc
            decision = clean_code(sub.iloc[decision_col]) if decision_col < len(sub) else None
            selection = clean_code(sub.iloc[selection_col]) if selection_col < len(sub) else None
            if is_struck_out(sub_index, selection, struck):
                continue
            if is_retained_choice(decision, selection):
                retained.add(code)
                break
    return retained


def is_struck_out(index, selection, struck):
    """
    Ligne barree donc non retenue. Regle ICE : une mention dans la colonne
    de selection reste prioritaire sur le barre, quel que soit son sens.
    """
    return index in struck and not normalize(selection)


def extract_cal_sheet(df, struck=(), decision_col=3, selection_col=4):
    """
    Retourne (functions, labels, block_codes).
    block_codes : codes a bloc retenus (voir CAL_WHOLE_SHEET_CODES).
    """
    functions, labels = set(), []
    block_codes = _cal_blocks(df, struck, decision_col, selection_col)

    for index, code, label, row in _cal_function_rows(df):
        if normalize(code) in CAL_IGNORED_CODES:
            continue
        decision = clean_code(row.iloc[decision_col]) if decision_col < len(row) else None
        selection = clean_code(row.iloc[selection_col]) if selection_col < len(row) else None
        if is_struck_out(index, selection, struck):
            continue
        if is_retained_choice(decision, selection):
            functions.add(code)
            if label:
                labels.append((label, code))

    return functions, labels, block_codes


# --------------------------------------------------------------------------
# Onglets Basse Tension / TAC (EquipementsTiers)
# --------------------------------------------------------------------------

SUBFUNCTION_RE = re.compile(r"^\s*(.+?)\s*-\s*Fonctions?\s+(.+?)\s*$", re.IGNORECASE)

# 'Fonctions utilisees: ... (DSARB, TDPCB et TPAPB dans DPC2)'
DPC_BLOCK_RE = re.compile(r"\(([^)]*?)\s+dans\s+DPC", re.IGNORECASE)
# 'Em.1 : VER   Rec.1 : VER'
COLON_CODE_RE = re.compile(r":\s*([A-Za-z0-9_.\-]+)")


def extract_equipment_sheet(df, sheet_name, struck=()):
    """
    Retourne (codes, mnemonics, labels).
      codes     : codes directement exploitables comme LibelleCourtObjetFonction
      mnemonics : tous les mnemoniques colonne A (sert au repli 'DIFC' -> 'DIFC11')
      labels    : titres de section + designations, pour le repli libelle long
      designations : (designation, mnemonique, onglet) des lignes retenues
    """
    codes, mnemonics, labels, designations = set(), set(), [], []

    header_row, columns = find_header_row(df, ["Mnemonique"])
    if header_row is None:
        return codes, mnemonics, labels, designations

    mnemonic_col = columns["MNEMONIQUE"]
    designation_col = columns.get("DESIGNATION", mnemonic_col + 1)
    option_col = columns.get("TYPEOPTION", columns.get("FCTTAC"))
    free_text_cols = [
        columns[key] for key in ("FCTTAC", "COMMENTAIRESDI") if key in columns
    ]
    # Colonnes de commentaire libre : versees aux libelles pour le repli par
    # libelle long, mais JAMAIS a l'extraction de codes ('2ème seuil : MAX I
    # Harmonique' y produirait un mnemonique 'MAX').
    comment_cols = [columns[key] for key in ("INFORMATIONSCLI",) if key in columns]

    for index, row in df.iloc[header_row + 1:].iterrows():
        if index in struck:
            continue
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
            if not is_excluded_option(option):
                # Conserve avec son mnemonique : sert aux recherches par
                # designation ('PX-Bi-Tiers' en face de 'PXmulti-PX').
                designations.append((designation, mnemonic, sheet_name))
            match = SUBFUNCTION_RE.match(designation)
            if match and not is_excluded_option(option):
                # 'PXmulti-Fonction PX' -> 'PXmulti-PX'
                codes.add("%s-%s" % (match.group(1), match.group(2)))

        for index in comment_cols:
            comment = clean_code(row.iloc[index]) if index < len(row) else None
            if comment:
                labels.append((comment, f"{sheet_name} (commentaire)"))

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

    return codes, mnemonics, labels, designations


# --------------------------------------------------------------------------
# Point d'entree
# --------------------------------------------------------------------------

def read_struck_rows(file, filename=None):
    """
    Lignes barrees du classeur : {onglet: {index de ligne}}.

    Une option barree signifie 'non retenue' (regle ICE), mais la colonne de
    selection reste prioritaire quand elle porte une mention.

    pandas ne remonte pas la mise en forme : le fichier est relu une seconde
    fois, avec xlrd pour les .xls et openpyxl pour les .xlsx. Les index de
    ligne correspondent a ceux des DataFrames lus avec header=None.
    Renvoie {} si la mise en forme n'est pas lisible (PDF, fichier protege).
    """
    name = filename or (file if isinstance(file, str) else "") or ""
    try:
        if hasattr(file, "seek"):
            file.seek(0)
        if str(name).lower().endswith(".xlsx"):
            return _struck_rows_xlsx(file)
        return _struck_rows_xls(file)
    except Exception:                                   # noqa: BLE001
        return {}
    finally:
        if hasattr(file, "seek"):
            file.seek(0)


def _struck_rows_xlsx(file):
    from openpyxl import load_workbook

    struck = {}
    workbook = load_workbook(file)
    for sheet in workbook.worksheets:
        rows = {
            index for index, row in enumerate(sheet.iter_rows())
            if any(cell.value is not None and str(cell.value).strip()
                   and cell.font is not None and cell.font.strike
                   for cell in row)
        }
        if rows:
            struck[sheet.title] = rows
    return struck


def _struck_rows_xls(file):
    import xlrd

    if isinstance(file, str):
        workbook = xlrd.open_workbook(file, formatting_info=True)
    else:
        workbook = xlrd.open_workbook(file_contents=file.read(),
                                      formatting_info=True)
    struck = {}
    for sheet in workbook.sheets():
        rows = set()
        for index in range(sheet.nrows):
            for column in range(sheet.ncols):
                if not str(sheet.cell_value(index, column)).strip():
                    continue
                style = workbook.xf_list[sheet.cell_xf_index(index, column)]
                if workbook.font_list[style.font_index].struck_out:
                    rows.add(index)
                    break
        if rows:
            struck[sheet.name] = rows
    return struck


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


def parse_excel_file(file, filename=None, struck_rows=None):
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
    return parse_sheet_frames(frames, struck_rows)


def parse_sheet_frames(frames, struck_rows=None):
    """
    Coeur de l'analyse, commun aux classeurs Excel et aux nomenclatures PDF.
    `frames`      : {nom d'onglet: DataFrame sans en-tete}.
    `struck_rows` : {nom d'onglet: index des lignes barrees}, vide pour un PDF.
    """
    struck_rows = struck_rows or {}
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
        "cal_block_codes": set(),
        "ccn_by_sheet": {},
        "designations": [],
        "notes": [],
    }

    if result["is_tg"]:
        for sheet_name in buckets["cal"]:
            functions, labels, block_codes = extract_cal_sheet(
                frames[sheet_name], struck_rows.get(sheet_name, ()))
            result["FonctionsNumériséesCCN"].update(functions)
            result["cal_block_codes"].update(block_codes)
            result["labels"].extend(labels)
        if not buckets["cal"]:
            result["notes"].append("Fichier TG sans onglet CAL.")
        return result

    for sheet_name in buckets["ccn"]:
        functions, labels, skipped = extract_ccn_sheet(
            frames[sheet_name], struck_rows.get(sheet_name, ()))
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
        codes, mnemonics, labels, designations = extract_equipment_sheet(
            frames[sheet_name], sheet_name, struck_rows.get(sheet_name, ())
        )
        result["EquipementsTiers"].update(codes)
        result["mnemonics"].update(mnemonics)
        result["labels"].extend(labels)
        result["designations"].extend(designations)
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

# Equivalences de codes FCS -> nomenclature.
# (sections, code FCS, libelle long FCS ou None, jeton cherche cote
#  nomenclature). Le jeton est cherche dans les codes, les mnemoniques et les
#  designations : la ligne 'PDBN UT 1/3 RACK 1-5A 48Vcc' vaut PDBN (demande
#  ICE : associer UT a l'element CONTENANT PDBN).
# Le libelle long, quand il est renseigne, doit correspondre exactement
# (apres normalisation) ; a None, l'equivalence vaut pour tout libelle.
FUNCTION_EQUIVALENCES = [
    (("EquipementsTiers", "FonctionsNumériséesCCN"), "UT", None, "PDBN"),
]


def label_tokens(text):
    """Jetons normalises d'un libelle : 'PDBN UT 1/3 RACK' -> {PDBN, UT...}."""
    return {normalize(part) for part in re.split(r"[^0-9A-Za-zÀ-ÿ]+", str(text or ""))
            if normalize(part)}


def _split_index(code_norm):
    """'PBF1' -> 'PBF', 'PBCS31S' -> 'PBCS', 'PDL' -> None."""
    match = re.match(r"^([A-Z]{2,})(\d+)([A-Z]?)$", code_norm)
    return match.group(1) if match else None


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


def _find_token(parsed, section, token):
    """
    Ligne de nomenclature contenant `token` : code exact, mnemonique, ou
    designation ou le jeton apparait comme mot entier.
    """
    found = _find_code(parsed, section, token)
    if found:
        return found
    for raw in sorted(parsed.get("mnemonics", set()), key=_instance_order):
        if token in label_tokens(raw):
            return raw
    for designation, mnemonic, sheet in parsed.get("designations", []):
        if token in label_tokens(designation):
            return "%s (%s)" % (mnemonic or sheet, designation)
    return None


def resolve_equivalence(parsed, section, code, long_label):
    """Retourne la ligne de nomenclature equivalente trouvee, ou None."""
    for sections, fcs_code, fcs_label, token in FUNCTION_EQUIVALENCES:
        if isinstance(sections, str):
            sections = (sections,)
        if section not in sections or normalize(fcs_code) != normalize(code):
            continue
        if fcs_label is not None and normalize(fcs_label) != normalize(long_label):
            continue
        found = _find_token(parsed, section, normalize(token))
        if found:
            return found
    return None


def resolve_designation(parsed, code):
    """
    Cherche le code du FCS dans la colonne Designation des onglets
    equipements tiers ('PX-Bi-Tiers' en face du mnemonique 'PXmulti-PX').
    Le code doit y figurer en entier, seul ou comme mot de la designation.
    """
    target = normalize(code)
    if len(target) < 2:
        return None
    for designation, mnemonic, sheet in parsed.get("designations", []):
        if normalize(designation) == target or target in label_tokens(designation):
            return "%s ~ %s" % (mnemonic or sheet, designation)
    return None


def resolve_radical(parsed, code):
    """
    Code du FCS indice, nomenclature sans indice : 'PBF1' et 'PBF2' en face
    de 'PBF', 'PBCS 31' en face de 'PBCS'. Symetrique de
    'mnemonique_indice', qui traite le cas inverse.
    """
    radical = _split_index(normalize(code))
    if not radical:
        return None
    return _find_code(parsed, "EquipementsTiers", radical)


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
        for raw in parsed.get("cal_block_codes", set()):
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

        radical = resolve_radical(parsed, code)
        if radical:
            return True, "mnemonique_radical", radical

        designation = resolve_designation(parsed, code)
        if designation:
            return True, "designation", designation

        if long_label:
            match = best_label_match(long_label, parsed.get("labels", []))
            if match:
                context, text, score = match
                return True, "libelle_long", "%s ~ %s (%.2f)" % (text, context, score)

    return False, None, None
