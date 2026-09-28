"""
Phase 2 : chaine de traitement et rapport Excel.
"""
import pandas as pd
import pytest

from src.signalisations.comparator import STATUS_LOT_ONLY, STATUS_OK
from src.signalisations.pipeline import read_overrides, run_analysis
from src.signalisations.report import generate_excel_report

FCS_XML = (
    '<?xml version="1.0" encoding="ISO-8859-1"?>'
    '<Site CodeNationalSite="MAUGE" NomSite="MAUGE">'
    '<NiveauTension LibelléNiveauTension="225kV">'
    '<Tranche LibelléCourtTranche="6CHOLE.1" LibelléLongTranche="Ligne"'
    ' LibelléTT="Liaison_225kV_AE_AS_EP_SE" IndiceTT="22">'
    '<FonctionsNumériséesCCN>'
    '<ObjetFonction LibelléCourtObjetFonction="PXmulti-PX"'
    ' LibelléLongObjetFonction="Fonction PX"/>'
    '</FonctionsNumériséesCCN>'
    '<Conduite><Signalisations>'
    '<Signalisation IDRC="ID000608" LibelléCourtInformationConduite="DT.PX"'
    ' LibelléLongInformationConduite="Déclenchement PX" Désignation=""'
    ' LibelléBlocFonctionnel="PROTECTION" NatureSignalisation="Simple"/>'
    '</Signalisations></Conduite></Tranche></NiveauTension></Site>'
)

LOT_XML = (
    '<?xml version="1.0" encoding="ISO-8859-1"?>'
    '<TrancheType IndiceTT="22" LibelléTT="Liaison_225kV_AE_AS_EP_SE">'
    '<Conduite><Signalisations>'
    '<!-- PX -->'
    '<Signalisation Référence="DT.PX" IDRC="ID000608" Inversion="non"/>'
    '<Signalisation Référence="DT.PX1" IDRC="ID000609" Inversion="non"/>'
    '<!-- FIN PX -->'
    '</Signalisations></Conduite></TrancheType>'
)


@pytest.fixture()
def files(tmp_path):
    fcs = tmp_path / "FCS_MAUGE_1.xml"
    fcs.write_bytes(FCS_XML.encode("ISO-8859-1"))
    lot = tmp_path / "Dossier 7 - Liaison.xml"
    lot.write_bytes(LOT_XML.encode("ISO-8859-1"))
    return str(fcs), str(lot)


def test_chaine_complete(files):
    fcs_path, lot_path = files
    fcs, comparison, report, sources, failures = run_analysis(
        fcs_path, [("Dossier 7 - Liaison.xml", lot_path)])

    assert failures == {}
    assert sources == [("Dossier 7 - Liaison.xml",
                        "Liaison_225kV_AE_AS_EP_SE", ["6CHOLE.1"])]
    statuses = {row["IDRC"]: row["Statut"] for row in comparison["lignes"]}
    assert statuses == {"ID000608": STATUS_OK, "ID000609": STATUS_LOT_ONLY}
    assert report.getvalue()[:2] == b"PK"          # classeur xlsx


def test_lot_illisible_signale(tmp_path, files):
    fcs_path, lot_path = files
    casse = tmp_path / "casse.xml"
    casse.write_text("<TrancheType>pas fermé")
    _fcs, comparison, _report, _sources, failures = run_analysis(
        fcs_path, [("casse.xml", str(casse)), ("bon.xml", lot_path)])
    assert "casse.xml" in failures
    assert comparison["lignes"], "le lot lisible doit quand même être traité"


def test_table_des_fonctions_atypiques(tmp_path, files):
    fcs_path, lot_path = files
    table = tmp_path / "atypiques.csv"
    table.write_text("fonction,bloc\nPXmulti-PX,PX\n", encoding="utf-8")
    overrides, message = read_overrides(str(table))
    assert overrides == {"PXMULTIPX": "PX"} and message == ""

    _fcs, comparison, _report, _sources, _failures = run_analysis(
        fcs_path, [("lot.xml", lot_path)], overrides_file=str(table))
    methods = {row["Méthode"] for row in comparison["lignes"]}
    assert methods == {"table client"}


def test_table_atypique_mal_formee(tmp_path):
    table = tmp_path / "atypiques.csv"
    table.write_text("colonne1,colonne2\na,b\n", encoding="utf-8")
    overrides, message = read_overrides(str(table))
    assert overrides == {} and "colonnes" in message


def test_rapport_excel(files, tmp_path):
    fcs_path, lot_path = files
    _fcs, comparison, report, sources, _failures = run_analysis(
        fcs_path, [("lot.xml", lot_path)])
    generated = generate_excel_report(comparison, sources)

    book = pd.ExcelFile(generated)
    assert book.sheet_names == ["Résumé", "Détails", "Sources"]
    details = pd.read_excel(book, "Détails")
    assert len(details) == 2
    assert "Connue du dicodata" in details.columns
    summary = pd.read_excel(book, "Résumé")
    assert summary.loc[0, "Tranche"] == "6CHOLE.1"
    assert summary.loc[0, "Présentes des deux côtés"] == 1
    assert summary.loc[0, "Prévues au lot, absentes du FCS"] == 1
