"""
Phase 2 : lecture des signalisations du FCS et correspondance fonction/bloc.
Donnees synthetiques calquees sur FCS_MAUGE_1.xml.
"""
from io import BytesIO

from src.signalisations.fcs_signals import read_fcs_signals, tranches_of_type
from src.signalisations.fonctions import (
    METHOD_EXACT, METHOD_INDEX, METHOD_PREFIX, METHOD_SUFFIX, METHOD_TABLE,
    load_overrides, map_functions,
)


def fcs(tranches):
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        '<Site CodeNationalSite="MAUGE" NomSite="MAUGE">'
        '<NiveauTension LibelléNiveauTension="225kV">%s</NiveauTension></Site>'
        % tranches
    )
    return read_fcs_signals(BytesIO(xml.encode("ISO-8859-1")))


def tranche(nom, libelle_tt="Liaison_225kV_AE_AS_EP_SE", indice="22",
            fonctions=(), signalisations=(), commandes=()):
    objets = "".join(
        '<ObjetFonction LibelléCourtObjetFonction="%s" LibelléLongObjetFonction="%s"/>'
        % pair for pair in fonctions)
    sigs = "".join(
        '<Signalisation IDRC="%s" LibelléCourtInformationConduite="%s"'
        ' LibelléLongInformationConduite="" Désignation=""'
        ' LibelléBlocFonctionnel="PROTECTION" NatureSignalisation="Simple"/>'
        % pair for pair in signalisations)
    cmds = "".join(
        '<SignalisationCommande IDRC="%s" LibelléCourtInformationConduite="%s"'
        ' LibelléLongInformationConduite="" Désignation=""'
        ' LibelléBlocFonctionnel="" NatureSignalisation="Double"/>'
        % pair for pair in commandes)
    return (
        '<Tranche LibelléCourtTranche="%s" LibelléLongTranche="Ligne"'
        ' LibelléTT="%s" IndiceTT="%s">'
        '<FonctionsNumériséesCCN>%s</FonctionsNumériséesCCN>'
        '<Conduite><Signalisations>%s</Signalisations>'
        '<SignalisationsCommandes>%s</SignalisationsCommandes></Conduite>'
        '</Tranche>' % (nom, libelle_tt, indice, objets, sigs, cmds)
    )


def test_lecture_des_signalisations():
    result = fcs(tranche(
        "6CHOLE.1",
        fonctions=[("PXmulti-PX", "Fonction PX")],
        signalisations=[("ID000607", "DT.PX"), ("ID000623", "DT.PX.PHASE 0")],
        commandes=[("ID012165", "MES.PSL")],
    ))
    entry = result["tranches"]["6CHOLE.1"]
    assert entry["type"] == ("Liaison_225kV_AE_AS_EP_SE", "22")
    assert entry["fonctions"] == {"PXmulti-PX": "Fonction PX"}
    assert set(entry["signalisations"]) == {"ID000607", "ID000623", "ID012165"}
    assert entry["signalisations"]["ID000607"]["type"] == "signalisation"
    assert entry["signalisations"]["ID012165"]["type"] == "signalisation_commande"
    assert entry["signalisations"]["ID000607"]["code"] == "DT.PX"


def test_regroupement_par_type_de_tranche():
    result = fcs(tranche("6CHOLE.1") + tranche("6VERTO.1")
                 + tranche("6TR641", libelle_tt="Transformateur_THT-HT_SE"))
    assert tranches_of_type(result, "Liaison_225kV_AE_AS_EP_SE", "22") == [
        "6CHOLE.1", "6VERTO.1"]
    assert tranches_of_type(result, "Transformateur_THT-HT_SE", "22") == ["6TR641"]


def test_rattachement_malgre_un_indice_different():
    """L'indice ne doit pas faire perdre le rattachement : il ne discrimine pas."""
    result = fcs(tranche("6CHOLE.1", indice="22"))
    assert tranches_of_type(result, "Liaison_225kV_AE_AS_EP_SE", "23") == ["6CHOLE.1"]


BLOCS = ["PX", "PW", "PDL", "ARS", "EP", "ACC", "PSL-PSC", "DIFC"]


def test_correspondances_exactes_et_partielles():
    result = map_functions(
        ["ACC", "PSL-PSC", "PDL1", "EP-BARRE", "ARS-BASE", "PXmulti-PX",
         "PXmulti-PW", "SYNO", "UT"],
        BLOCS,
    )
    matches = result["correspondances"]
    assert matches["ACC"] == {"bloc": "ACC", "methode": METHOD_EXACT}
    assert matches["PSL-PSC"]["methode"] == METHOD_EXACT      # tiret mais exact
    assert matches["PDL1"] == {"bloc": "PDL", "methode": METHOD_INDEX}
    assert matches["EP-BARRE"] == {"bloc": "EP", "methode": METHOD_PREFIX}
    assert matches["ARS-BASE"] == {"bloc": "ARS", "methode": METHOD_PREFIX}
    assert matches["PXmulti-PX"] == {"bloc": "PX", "methode": METHOD_SUFFIX}
    assert matches["PXmulti-PW"] == {"bloc": "PW", "methode": METHOD_SUFFIX}
    assert result["sans_bloc"] == ["SYNO", "UT"]


def test_regle_appliquee_seulement_si_le_bloc_existe():
    """'ECH-TRFDEP' ne doit pas tomber sur un bloc 'ECH' inexistant."""
    result = map_functions(["ECH-TRFDEP"], BLOCS)
    assert result["correspondances"] == {}
    assert result["sans_bloc"] == ["ECH-TRFDEP"]


def test_table_client_prioritaire():
    overrides = load_overrides([("PXmulti-PX", "PW"), ("SYNO", "")])
    result = map_functions(["PXmulti-PX"], BLOCS, overrides)
    assert result["correspondances"]["PXmulti-PX"] == {
        "bloc": "PW", "methode": METHOD_TABLE}


def test_blocs_sans_fonction_installee():
    result = map_functions(["ACC"], ["ACC", "DIFC", "PX"])
    assert result["blocs_sans_fonction"] == ["DIFC", "PX"]
