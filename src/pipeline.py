"""
Chaine de traitement complete, independante de Streamlit.

Utilisee par l'interface (app.py) et par la verification en ligne de
commande (check_install.py) : les deux produisent donc le meme resultat.
"""

from src.fcs_parser import parse_fcs
from src.nomenclature import load_nomenclature
from src.comparator import compare_all
from src.multi_tension import expand_multi_voltage
from src.report_generator import generate_excel_report
from src.tranche_matcher import match_workbook_to_tranche, resolve_collisions


def run_analysis(fcs_file, nomenclatures):
    """
    fcs_file      : chemin ou objet fichier du FCS
    nomenclatures : iterable de (nom de fichier, chemin ou objet fichier)

    Retourne (fcs, associations, comparison, report, failures).
    """
    fcs = parse_fcs(fcs_file)
    tranche_names = list(fcs["tranches"])
    site = (fcs["site"]["code"], fcs["site"]["nom"])
    volts = fcs.get("niveaux_tension", {})

    associations, parsed_by_file, failures = {}, {}, {}

    for name, file in nomenclatures:
        try:
            sheet_names, pdg_rows, parsed = load_nomenclature(file, name)
            associations[name] = match_workbook_to_tranche(
                name, sheet_names, pdg_rows, tranche_names, site, volts
            )
            parsed_by_file[name] = parsed
        except Exception as error:              # noqa: BLE001
            failures[name] = "%s : %s" % (type(error).__name__, error)

    # Avant la gestion des collisions : une nomenclature multi-tension vise
    # plusieurs tranches, ce n'est pas un conflit.
    associations, parsed_by_file = expand_multi_voltage(
        associations, parsed_by_file, fcs
    )
    associations = resolve_collisions(associations, tranche_names)
    comparison = compare_all(fcs, associations, parsed_by_file)
    report = generate_excel_report(comparison, associations)
    return fcs, associations, comparison, report, failures
