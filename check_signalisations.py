"""
Verification des signalisations hors Streamlit (phase 2).

    python check_signalisations.py FCS.xml dossier_lots/ [dicodata.xls] [rapport.xlsx]

Le dossier de lots contient un fichier XML par type de tranche.
"""

import os
import sys
import warnings
from collections import Counter

from src.signalisations.comparator import (
    STATUS_FCS_ONLY, STATUS_FCS_OUT_OF_SCOPE, STATUS_LOT_ONLY, STATUS_OK,
)
from src.signalisations.pipeline import run_analysis


def main(argv):
    if not 3 <= len(argv) <= 5:
        print(__doc__)
        return 2
    fcs_path, folder = argv[1], argv[2]
    dicodata = argv[3] if len(argv) > 3 and argv[3].lower().endswith((".xls", ".xlsx")) else None
    output = next((a for a in argv[3:] if a.lower().endswith(".xlsx")
                   and a != dicodata), None)
    warnings.simplefilter("ignore")

    lots = [(name, os.path.join(folder, name))
            for name in sorted(os.listdir(folder)) if name.lower().endswith(".xml")]
    fcs, comparison, report, sources, failures = run_analysis(
        fcs_path, lots, dicodata)

    print("Site : %s - %d tranches, %d types, %d fichier(s) de lot"
          % (fcs["site"]["nom"], len(fcs["tranches"]), len(fcs["types"]), len(lots)))
    print("\nFichiers de lot")
    for name, libelle, tranches in sources:
        print("  %-52s %-34s %s" % (name[:52], libelle[:34],
                                    ", ".join(tranches) or "aucune tranche"))
    for name, message in failures.items():
        print("  ILLISIBLE %s : %s" % (name, message))

    print("\n%-14s %6s %6s %6s %6s  %s"
          % ("Tranche", "Fonct.", "OK", "Lot", "FCS", "Statut"))
    for tranche, entry in sorted(comparison["tranches"].items()):
        counts = entry.get("compte") or {}
        print("%-14s %6s %6s %6s %6s  %s" % (
            tranche, entry.get("fonctions", ""),
            counts.get(STATUS_OK, "") if counts else "",
            counts.get(STATUS_LOT_ONLY, "") if counts else "",
            counts.get(STATUS_FCS_ONLY, "") if counts else "",
            entry.get("statut", "")))

    totals = Counter(row["Statut"] for row in comparison["lignes"])
    print("\nTotal %d lignes" % len(comparison["lignes"]))
    for status in (STATUS_OK, STATUS_LOT_ONLY, STATUS_FCS_ONLY,
                   STATUS_FCS_OUT_OF_SCOPE):
        if totals.get(status):
            print("   %-58s %d" % (status, totals[status]))
    for warning in comparison["avertissements"]:
        print("   ! %s" % warning)

    if output:
        with open(output, "wb") as handle:
            handle.write(report.getvalue())
        print("\nRapport écrit : %s" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
