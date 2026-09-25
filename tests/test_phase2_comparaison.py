"""
Phase 2 : referentiel dicodata et jointure des trois sources.
Donnees synthetiques calquees sur MAUGE.
"""
from io import BytesIO

import pandas as pd

from src.signalisations.comparator import (
    STATUS_FCS_ONLY, STATUS_LOT_ONLY, STATUS_OK, compare_site,
)
from src.signalisations.dicodata import describe, load_dicodata
from src.signalisations.lot_parser import parse_lot
from tests.test_phase2_fonctions import fcs as build_fcs, tranche


# --------------------------------------------------------------------------
# Dicodata
# --------------------------------------------------------------------------

def dicodata_file(tmp_path):
    """La 1re ligne de donnees decrit les types de colonnes, pas des valeurs."""
    path = tmp_path / "dicodata.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([
            {"IDRC": "varchar(50)", "mnemo_info_court": "varchar(16)",
             "nom_info_type": "varchar(100)", "nature": "varchar(20)"},
            {"IDRC": "ID000608", "mnemo_info_court": "DT.PX",
             "nom_info_type": "Signalisation déclenchement PX", "nature": "Etat"},
            {"IDRC": "ID012165", "mnemo_info_court": "MES.PSL",
             "nom_info_type": "Commande mise en service", "nature": "Cde"},
        ]).to_excel(writer, sheet_name="information_type", index=False)
        pd.DataFrame([
            {"IDRC": "varchar(50)", "mnemo_info_cours": "varchar(16)",
             "nature": "NaN"},
            {"IDRC": "ID000872", "mnemo_info_cours": "DT.MAXI2", "nature": "EF"},
        ]).to_excel(writer, sheet_name="dd_idrc_it", index=False)
        pd.DataFrame([
            {"mnemo_fonction = libelle_court": "varchar(20)",
             "nom_fonction": "varchar(255)"},
            {"mnemo_fonction = libelle_court": "PXmulti-PX",
             "nom_fonction": "Fonction PX dans Protection multi-fonctionnelle"},
        ]).to_excel(writer, sheet_name="dd_fonction_tranche", index=False)
    return str(path)


def test_chargement_dicodata(tmp_path):
    dico = load_dicodata(dicodata_file(tmp_path))
    assert dico["compte"] == {"information_type": 2, "dd_idrc_it": 1}
    assert describe(dico, "ID000608")["mnemonique"] == "DT.PX"
    assert describe(dico, "ID000608")["source"] == "information_type"
    assert describe(dico, "varchar(50)") is None      # ligne de types ignorée
    assert dico["fonctions"]["PXmulti-PX"].startswith("Fonction PX")


def test_dicodata_complete_par_dd_idrc_it(tmp_path):
    dico = load_dicodata(dicodata_file(tmp_path))
    assert describe(dico, "ID000872")["source"] == "dd_idrc_it"
    assert describe(dico, "ID999999") is None


# --------------------------------------------------------------------------
# Jointure
# --------------------------------------------------------------------------

def lot_file(body, libelle="Liaison_225kV_AE_AS_EP_SE", indice="22"):
    xml = ('<?xml version="1.0" encoding="ISO-8859-1"?>'
           '<TrancheType IndiceTT="%s" LibelléTT="%s">'
           '<Conduite><Signalisations>%s</Signalisations></Conduite>'
           '</TrancheType>' % (indice, libelle, body))
    return parse_lot(BytesIO(xml.encode("ISO-8859-1")))


def sig(reference, idrc):
    return '<Signalisation Référence="%s" IDRC="%s" Inversion="non"/>' % (
        reference, idrc)


LOT = ("<!-- PX -->" + sig("DT.PX", "ID000608") + sig("DT.PX1", "ID000609")
       + "<!-- FIN PX -->"
       + "<!-- DIFC -->" + sig("DT.DIFC", "ID002000") + "<!-- FIN DIFC -->"
       + "<!-- COMMUN TRANCHE -->" + sig("DF.TRAN", "ID000422")
       + "<!-- FIN COMMUN TRANCHE -->")


def site():
    return build_fcs(tranche(
        "6CHOLE.1",
        fonctions=[("PXmulti-PX", "Fonction PX")],
        signalisations=[("ID000608", "DT.PX"), ("ID000422", "DF.TRAN")],
    ))


def rows_by_idrc(result):
    return {row["IDRC"]: row for row in result["lignes"]}


def test_statuts_de_base():
    result = compare_site(site(), [("lot.xml", lot_file(LOT))])
    rows = rows_by_idrc(result)
    assert rows["ID000608"]["Statut"] == STATUS_OK
    assert rows["ID000609"]["Statut"] == STATUS_LOT_ONLY
    assert rows["ID000608"]["Fonction FCS"] == "PXmulti-PX"
    assert rows["ID000608"]["Méthode"] == "apres le tiret"
    assert result["avertissements"] == []


def test_fonction_non_installee_ecartee():
    """DIFC n'est pas installée : ses signalisations ne sont pas des écarts."""
    result = compare_site(site(), [("lot.xml", lot_file(LOT))])
    assert "ID002000" not in rows_by_idrc(result)


def test_bloc_commun_pris_en_compte():
    """'COMMUN TRANCHE' n'est pas une fonction, mais s'applique à la tranche."""
    row = rows_by_idrc(compare_site(site(), [("lot.xml", lot_file(LOT))]))["ID000422"]
    assert row["Statut"] == STATUS_OK
    assert row["Méthode"] == "bloc commun (présent au FCS)"


def test_signalisation_du_fcs_absente_du_lot():
    fcs = build_fcs(tranche(
        "6CHOLE.1",
        fonctions=[("PXmulti-PX", "Fonction PX")],
        signalisations=[("ID000608", "DT.PX"), ("ID009999", "INCONNUE")],
    ))
    row = rows_by_idrc(compare_site(fcs, [("lot.xml", lot_file(LOT))]))["ID009999"]
    assert row["Statut"] == STATUS_FCS_ONLY
    assert row["Présente au lot"] == "non"


def test_colonnes_de_provenance_avec_dicodata(tmp_path):
    dico = load_dicodata(dicodata_file(tmp_path))
    rows = rows_by_idrc(compare_site(site(), [("lot.xml", lot_file(LOT))], dico))
    assert rows["ID000608"]["Connue du dicodata"] == "oui"
    assert rows["ID000608"]["Libellé dicodata"].startswith("Signalisation")
    assert rows["ID000422"]["Connue du dicodata"] == "non"


def test_lot_sans_type_correspondant():
    result = compare_site(site(), [("autre.xml", lot_file(LOT, libelle="Couplage_SE"))])
    assert result["lignes"] == []
    assert "aucun type de tranche" in result["avertissements"][0]


def test_tranche_sans_lot_signalee():
    fcs = build_fcs(tranche("6CHOLE.1") + tranche("4COND.1", libelle_tt="Condensateurs_SE"))
    result = compare_site(fcs, [("lot.xml", lot_file(LOT))])
    assert result["tranches"]["4COND.1"]["statut"].startswith("Aucun fichier de lot")
