"""
Verification hors Streamlit.

    python check_install.py chemin/FCS_XXX.xml chemin/dossier_nomenclatures/ [rapport.xlsx]

Affiche les associations et la synthese par tranche, et ecrit le rapport
Excel si un chemin de sortie est donne.
"""

import os
import sys
import warnings

from src.comparator import (
    is_ok_status, STATUS_EXCEL_ONLY, STATUS_FCS_ONLY,
)
from src.nomenclature import SUPPORTED_EXTENSIONS
from src.pipeline import run_analysis


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    fcs_path, folder = argv[1], argv[2]
    warnings.simplefilter("ignore")      # styles openpyxl absents, sans effet

    files = sorted(
        name for name in os.listdir(folder)
        if name.rsplit(".", 1)[-1].lower() in SUPPORTED_EXTENSIONS
    )
    fcs, associations, comparison, report, failures = run_analysis(
        fcs_path, [(name, os.path.join(folder, name)) for name in files]
    )

    print("Site : %s - %d tranches, %d nomenclatures"
          % (fcs["site"]["nom"], len(fcs["tranches"]), len(files)))
    print("\nAssociations")
    for name, match in sorted(associations.items()):
        target = match.get("tranche") or match.get("tranche_absente") or "-"
        print("  %-60s %-28s %s" % (name[:60], target, match.get("method")))
    for name, message in failures.items():
        print("  ILLISIBLE %s : %s" % (name, message))

    print("\n%-28s %-24s %5s %5s %5s  %s"
          % ("Tranche", "Section", "OK", "NOM", "FCS", "Statut tranche"))
    totals = [0, 0, 0]
    for name, entry in sorted(comparison["tranches"].items()):
        if not entry["sections"]:
            print("%-28s %-24s %5s %5s %5s  %s"
                  % (name, "", "", "", "", entry["statut_tranche"]))
        for section, rows in entry["sections"].items():
            counts = [
                sum(1 for r in rows if is_ok_status(r["Statut"])),
                sum(1 for r in rows if r["Statut"] == STATUS_EXCEL_ONLY),
                sum(1 for r in rows if r["Statut"] == STATUS_FCS_ONLY),
            ]
            totals = [a + b for a, b in zip(totals, counts)]
            print("%-28s %-24s %5d %5d %5d  %s"
                  % (name, section, *counts, entry["statut_tranche"] or ""))
    print("%-28s %-24s %5d %5d %5d" % ("TOTAL", "", *totals))

    if len(argv) == 4:
        with open(argv[3], "wb") as handle:
            handle.write(report.getvalue())
        print("\nRapport écrit : %s" % argv[3])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
