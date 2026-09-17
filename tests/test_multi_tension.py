"""Nomenclatures AUT.POS multi-tension (cas MAUGE), donnees synthetiques."""
import pandas as pd

from src.comparator import compare_all, TRANCHE_NOT_IN_FCS, STATUS_OK, STATUS_EXCEL_ONLY
from src.excel_parser import parse_sheet_frames
from src.multi_tension import expand_multi_voltage, voltage_value
from src.tranche_matcher import match_workbook_to_tranche, resolve_collisions


def ccn(*codes):
    rows = [["Fonctions numérisées"], ["Toute fonction..."],
            ["Désignation", "Nom Litéral", "Type option"]]
    rows += [[code, "Libellé " + code, "Option"] for code in codes]
    return pd.DataFrame(rows)


def tranche(level, **functions):
    return {"LibelléLongTranche": "", "LibelléTT": "", "CodeSchémathèqueTT": "",
            "NiveauTension": level,
            "FonctionsNumériséesCCN": functions, "EquipementsTiers": {}}


FCS = {
    "site": {"code": "MAUGE", "nom": "MAUGE"},
    "niveaux_tension": {"90kV": "4", "225kV": "6"},
    "tranches": {
        "AUT.POST": tranche("0kV", **{"SMACC-1UREF": "Système avancé"}),
        "4AUT.POS": tranche("90kV", ASLD="Automate secours"),
        "4CBO": tranche("90kV"),
    },
}

PDG = [("Codification cellule DPC²", "AUT.POS"),
       ("Type de tranche", "022-Tranche automate de poste")]

FRAMES = {
    "Page de garde": pd.DataFrame(),
    "2-CCN 225kV": ccn("ASLD", "AUTOMATE"),
    "3- CCN 90kV": ccn("ASLD"),
    "5- CCN 0kV": ccn("SMACC-1UREF"),
    "6-TAC": pd.DataFrame([["Mnémonique", "Désignation", "Type option"]]),
}


def run():
    name = "0-MAUGE_AUT_POS.xlsx"
    parsed = {name: parse_sheet_frames(FRAMES)}
    assoc = {name: match_workbook_to_tranche(
        name, list(FRAMES), PDG, list(FCS["tranches"]), ("MAUGE",),
        FCS["niveaux_tension"])}
    assoc, parsed = expand_multi_voltage(assoc, parsed, FCS)
    assoc = resolve_collisions(assoc, list(FCS["tranches"]))
    return assoc, compare_all(FCS, assoc, parsed)


def test_voltage_value():
    assert voltage_value("2-CCN 225kV") == 225
    assert voltage_value("5- CCN 0kV") == 0
    assert voltage_value("4-CCN") is None


def test_alias_aut_post():
    match = match_workbook_to_tranche(
        "x.xlsx", list(FRAMES), PDG, list(FCS["tranches"]), ("MAUGE",), {})
    assert match["tranche"] == "AUT.POST"


def test_un_onglet_par_tension():
    assoc, comparison = run()
    targets = {k.split("[")[1].rstrip("]"): v.get("tranche") or v.get("tranche_absente")
               for k, v in assoc.items()}
    assert targets == {
        "2-CCN 225kV": "6AUT.POS (absente du FCS)",
        "3- CCN 90kV": "4AUT.POS",
        "5- CCN 0kV": "AUT.POST",
    }
    tranches = comparison["tranches"]
    assert not comparison["fichiers_non_associes"]

    def statuses(name):
        return {r["Fonction FCS"] or r["Fonction Excel"]: r["Statut"]
                for r in tranches[name]["sections"]["FonctionsNumériséesCCN"]}

    assert statuses("AUT.POST") == {"SMACC-1UREF": STATUS_OK}
    assert statuses("4AUT.POS") == {"ASLD": STATUS_OK}
    absent = tranches["6AUT.POS (absente du FCS)"]
    assert absent["statut_tranche"] == TRANCHE_NOT_IN_FCS
    assert statuses("6AUT.POS (absente du FCS)") == {
        "ASLD": STATUS_EXCEL_ONLY, "AUTOMATE": STATUS_EXCEL_ONLY}
    # Les onglets TAC suivent la tranche de la page de garde (0 kV)
    tac_notes = {name for name, entry in tranches.items()
                 if any("TAC" in note for note in entry["avertissements"])}
    assert tac_notes == {"AUT.POST"}


def test_classeur_mono_tension_inchange():
    frames = {"Page de garde": pd.DataFrame(), "4-CCN 90kV": ccn("ASLD")}
    name = "4AUT.xlsx"
    pdg = [("Codification cellule DPC²", "4AUT.POS")]
    parsed = {name: parse_sheet_frames(frames)}
    assoc = {name: match_workbook_to_tranche(
        name, list(frames), pdg, list(FCS["tranches"]), ("MAUGE",), {})}
    assoc, parsed = expand_multi_voltage(assoc, parsed, FCS)
    assert list(assoc) == [name] and assoc[name]["tranche"] == "4AUT.POS"
