import re
from difflib import SequenceMatcher

from src.llm_matcher import ask_llm_for_tranche


def normalize_name(value):
    value = str(value).upper()
    return re.sub(r"[^A-Z0-9]", "", value)


def remove_version_suffix(tranche_norm):
    """
    Exemples :
    3CBO1 -> 3CBO
    3MURET2 -> 3MURET
    6VERFE3 -> 6VERFE
    3TR631 -> 3TR631  # on garde les TR entiers
    """
    if re.match(r"^\dTR\d+$", tranche_norm):
        return tranche_norm

    return re.sub(r"\d+$", "", tranche_norm)


def score_match(filename, tranche):
    file_norm = normalize_name(filename)
    tranche_norm = normalize_name(tranche)

    # On ignore les tranches trop courtes pour éviter SI, TG, etc.
    if len(tranche_norm) < 4:
        return 0.0

    if tranche_norm in file_norm:
        return 1.0

    tranche_base = remove_version_suffix(tranche_norm)

    if len(tranche_base) >= 4 and tranche_base in file_norm:
        return 0.98

    return SequenceMatcher(None, file_norm, tranche_norm).ratio()


def deterministic_match(filename, tranches, threshold=0.85):
    scored = []

    for tranche in tranches:
        score = score_match(filename, tranche)
        scored.append((tranche, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    best_tranche, best_score = scored[0]

    if best_score >= threshold:
        return best_tranche, best_score

    return None, best_score


def match_files_to_tranches(filenames, tranches):
    matches = {}
    unresolved = {}

    for filename in filenames:
        tranche, score = deterministic_match(filename, tranches)

        if tranche:
            matches[filename] = {
                "tranche": tranche,
                "method": "deterministic",
                "score": score
            }
        else:
            unresolved[filename] = {
                "best_score": score
            }

    return matches, unresolved


def match_files_to_tranches_with_llm(filenames, tranches):
    matches, unresolved = match_files_to_tranches(filenames, tranches)

    for filename in list(unresolved.keys()):
        llm_tranche = ask_llm_for_tranche(filename, tranches)

        if llm_tranche:
            matches[filename] = {
                "tranche": llm_tranche,
                "method": "llm",
                "score": None
            }
            unresolved.pop(filename)

    return matches, unresolved