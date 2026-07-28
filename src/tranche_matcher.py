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
        exact[strip_site_prefix(normalize_name(tranche), site_norms)] = tranche
        key = strip_site_prefix(normalize_name(strip_tranche_index(tranche)), site_norms)
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

def match_workbook_to_tranche(filename, sheet_names, pdg_rows, tranches, site=None):
    """
    site : str ou iterable de str (typiquement CodeNationalSite ET NomSite).
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

    raw = read_codification(pdg_rows)
    if raw:
        exact, loose = build_tranche_index(tranches, site_norms)
        code = clean_codification(raw, site_norms)

        tranche = exact.get(code)
        method = "page_de_garde"
        warning = None

        if tranche is None:
            # repli : indice de tranche absent d'un cote ou de l'autre
            head = re.split(r"\s+-\s+", str(raw))[0]
            loose_code = strip_site_prefix(
                normalize_name(strip_tranche_index(head)), site_norms
            )
            tranche = loose.get(loose_code) or loose.get(code)
            if tranche:
                method = "page_de_garde_sans_indice"
                warning = (
                    f"Codification '{raw}' rapprochee de la tranche '{tranche}' "
                    f"en ignorant l'indice de tranche."
                )

        if tranche:
            return {
                "tranche": tranche,
                "method": method,
                "raw": raw,
                "warning": warning or filename_consistency_warning(filename, tranche),
            }
        return {
            "tranche": None,
            "method": "page_de_garde_sans_correspondance",
            "raw": raw,
            "warning": f"Codification '{raw}' absente du FCS.",
        }

    if looks_like_tg(sheet_names, pdg_rows):
        tranche = find_tg_tranche(tranches)
        if tranche:
            return {"tranche": tranche, "method": "tranche_generale",
                    "raw": None, "warning": None}
        return {"tranche": None, "method": "tranche_generale",
                "raw": None, "warning": "Fichier TG detecte mais absent du FCS."}

    return {"tranche": None, "method": "echec", "raw": None,
            "warning": "Aucune codification lisible sur la page de garde."}


def resolve_collisions(results):
    """
    results : {filename: match_dict}
    Deux fichiers sur la meme tranche = anomalie. On les remet en non resolus
    plutot que d'en choisir un au hasard.
    """
    by_tranche = {}
    for filename, match in results.items():
        if match.get("tranche"):
            by_tranche.setdefault(match["tranche"], []).append(filename)

    for tranche, filenames in by_tranche.items():
        if len(filenames) > 1:
            for filename in filenames:
                results[filename]["tranche"] = None
                results[filename]["method"] = "collision"
                results[filename]["warning"] = (
                    f"Conflit : {', '.join(filenames)} pointent tous vers "
                    f"'{tranche}'. Association a trancher manuellement."
                )
    return results
