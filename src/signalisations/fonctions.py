"""
Correspondance entre les fonctions du FCS et les blocs d'un lot.

Le premier controle de la phase 2 (lot -> FCS) ne vaut que pour les
fonctions REELLEMENT installees sur la tranche : le lot est un catalogue qui
decrit toutes les variantes du type de tranche. Sans ce filtre, sur MAUGE,
237 des 330 signalisations du lot ressortiraient comme manquantes alors que
leurs fonctions ne sont pas installees.

Il faut donc relier chaque fonction du FCS au bloc de commentaires qui porte
ses signalisations. Aucune regle lexicale unique ne convient :

    PDL1        -> PDL          (indice en fin de code)
    EP-BARRE    -> EP           (ce qui PRECEDE le tiret)
    ARS-BASE    -> ARS          (idem)
    PXmulti-PX  -> PX           (ce qui SUIT le tiret)
    PXmulti-PW  -> PW           (idem)

Les regles ci-dessous couvrent ces cas, mais ne sont appliquees que si le
candidat existe reellement parmi les blocs du lot, et la methode retenue est
reportee au rapport. Elles restent PROVISOIRES : le client doit fournir une
table des fonctions atypiques par lot, qui sera chargee ici et aura la
priorite (voir load_overrides).

Les fonctions sans bloc ne sont pas des anomalies : elles relevent du second
controle (FCS -> lot et dicodata).
"""

import re

from src.utils import normalize

METHOD_EXACT = "exacte"
METHOD_TABLE = "table client"
METHOD_INDEX = "sans indice"
METHOD_PREFIX = "avant le tiret"
METHOD_SUFFIX = "apres le tiret"


def _strip_index(code):
    """'PDL1' -> 'PDL' ; 'PDL' -> None."""
    match = re.match(r"^(.*[A-Z])\d+$", normalize(code))
    return match.group(1) if match else None


def _before_dash(code):
    head = str(code).split("-", 1)[0]
    return normalize(head) if "-" in str(code) and head else None


def _after_dash(code):
    parts = str(code).split("-", 1)
    return normalize(parts[1]) if len(parts) == 2 and parts[1] else None


RULES = (
    (METHOD_INDEX, _strip_index),
    (METHOD_PREFIX, _before_dash),
    (METHOD_SUFFIX, _after_dash),
)


def load_overrides(rows):
    """
    Table des fonctions atypiques fournie par le client :
    iterable de (fonction, bloc). Renvoie {fonction normalisee: bloc}.
    """
    return {normalize(function): block for function, block in rows
            if normalize(function) and block}


def map_functions(functions, blocks, overrides=None):
    """
    functions : codes de fonction du FCS pour une tranche
    blocks    : noms de blocs du lot
    overrides : table client {fonction normalisee: nom de bloc}

    Retourne :
      {
        "correspondances": {fonction: {"bloc": ..., "methode": ...}},
        "sans_bloc":       [fonctions sans bloc, pour le second controle],
        "blocs_sans_fonction": [blocs dont aucune fonction n'est installee],
      }
    """
    overrides = overrides or {}
    index = {}
    for block in blocks:
        index.setdefault(normalize(block), block)

    matches, orphans = {}, []
    for function in sorted(functions):
        block, method = _match(function, index, overrides)
        if block:
            matches[function] = {"bloc": block, "methode": method}
        else:
            orphans.append(function)

    used = {entry["bloc"] for entry in matches.values()}
    return {
        "correspondances": matches,
        "sans_bloc": orphans,
        "blocs_sans_fonction": [block for block in blocks if block not in used],
    }


def _match(function, index, overrides):
    override = overrides.get(normalize(function))
    if override and normalize(override) in index:
        return index[normalize(override)], METHOD_TABLE

    target = normalize(function)
    if target in index:
        return index[target], METHOD_EXACT

    for method, rule in RULES:
        candidate = rule(function)
        if candidate and candidate in index:
            return index[candidate], method
    return None, None
