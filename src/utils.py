import re
import unicodedata


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

def strip_accents(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    return text.encode("ascii", "ignore").decode("ascii")


def normalize(value):
    """
    Normalisation 'agressive' : sert aux comparaisons de noms d'onglets,
    d'en-tetes et de codes fonction. Supprime tout ce qui n'est pas
    alphanumerique (et non plus seulement espace/-/_/.).
    """
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", strip_accents(value).upper())


def clean_code(value):
    """Valeur de cellule -> texte utilisable, ou None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none"):
        return None
    return text


# --------------------------------------------------------------------------
# Valeurs de la colonne 'Type option' / 'Choix des fonctions'
# --------------------------------------------------------------------------

EXCLUDED_OPTION_VALUES = {"NON", "N", "SANSOBJET", "NONAPPLICABLE"}


def is_excluded_option(value):
    """
    True si la cellule 'Type option' marque la fonction comme non retenue.
    Une cellule vide n'est PAS une exclusion : selon les revisions de
    template, l'absence de valeur signifie tantot 'non retenu', tantot
    'non renseigne'. C'est a l'appelant de trancher selon le template.
    """
    token = normalize(value)
    return token in EXCLUDED_OPTION_VALUES


def is_retained_option(value):
    """True si la cellule marque explicitement la fonction comme retenue."""
    token = normalize(value)
    if not token or token in EXCLUDED_OPTION_VALUES:
        return False
    return True


# --------------------------------------------------------------------------
# Titres de section
# --------------------------------------------------------------------------

SECTION_TITLE_RE = re.compile(r"^\s*\d{1,2}\s*[-–—.]\s*\S")


def is_section_title(value):
    """
    Titre de section du type '00-Protection Principale 1',
    '10-Détecteur de Défaut Siphon', '4- CCN 63kV', '1.Generalites'.
    Accepte 1 ou 2 chiffres et tolere les espaces autour du separateur.
    """
    if not value:
        return True
    return bool(SECTION_TITLE_RE.match(str(value)))


def section_title_text(value):
    """'10-Détecteur de Défaut Siphon' -> 'Détecteur de Défaut Siphon'."""
    if not value:
        return ""
    return re.sub(r"^\s*\d{1,2}\s*[-–—.]\s*", "", str(value)).strip()


# --------------------------------------------------------------------------
# Detection de la Tranche Generale (par contenu, pas par nom de fichier)
# --------------------------------------------------------------------------

def is_tg_workbook(sheet_names):
    """
    Le fichier de la Tranche Generale suit le template E9 : onglet 'CAL' et
    page de garde nommee 'PdG' (parfois avec espace final).

    Remplace is_tg_file(filename), qui produisait des faux positifs sur tout
    nom de poste contenant 'TG' (MONTGERON, MONTGISCARD, ...).
    """
    names = {normalize(n) for n in sheet_names}
    return "CAL" in names and any(n in ("PDG", "PAGEDEGARDE") for n in names)


# --------------------------------------------------------------------------
# Rapprochement par libelle long
# --------------------------------------------------------------------------

STOPWORDS = {
    "DE", "DU", "DES", "LA", "LE", "LES", "L", "UN", "UNE", "ET", "OU",
    "EN", "AU", "AUX", "DANS", "POUR", "PAR", "SUR", "AVEC", "CONTRE",
    "SANS", "D", "A",
}

STEM_LENGTH = 6


def label_tokens(value):
    """
    'Protection contre les ruptures de synchronisme'
        -> {'PROTEC', 'RUPTUR', 'SYNCHR'}
    Racinisation grossiere (troncature) : suffit a rapprocher
    'Détection' / 'Détecteur' ou 'ruptures' / 'rupture'.
    """
    words = re.split(r"[^A-Z0-9]+", strip_accents(value).upper())
    tokens = set()
    for word in words:
        if not word or word in STOPWORDS or len(word) < 3:
            continue
        tokens.add(word[:STEM_LENGTH])
    return tokens


def label_similarity(left, right):
    """Indice de Jaccard sur les racines. 0.0 -> 1.0."""
    a, b = label_tokens(left), label_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_label_match(target_label, candidates, threshold=0.6):
    """
    candidates : iterable de (texte, contexte). Retourne
    (contexte, texte, score) du meilleur candidat au-dessus du seuil,
    sinon None.
    """
    best = None
    for text, context in candidates:
        score = label_similarity(target_label, text)
        if score >= threshold and (best is None or score > best[2]):
            best = (context, text, score)
    return best