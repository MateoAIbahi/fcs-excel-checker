import re
from difflib import SequenceMatcher
from src.llm_matcher import ask_llm_for_tranche

def normalize_name(value):
    value = str(value).upper()
    return re.sub(r"[^A-Z0-9]", "", value)


def score_match(filename, tranche):
    file_norm = normalize_name(filename)
    tranche_norm = normalize_name(tranche)

    if tranche_norm in file_norm:
        return 1.0

    # Exemple : 3CBO1 doit matcher avec CBO
    tranche_without_digits = re.sub(r"\d", "", tranche_norm)

    if tranche_without_digits and tranche_without_digits in file_norm:
        return 0.95

    return SequenceMatcher(None, file_norm, tranche_norm).ratio()


def deterministic_match(filename, tranches, threshold=0.75):
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