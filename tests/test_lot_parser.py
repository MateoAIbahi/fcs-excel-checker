"""
Lecteur de lot (phase 2) : donnees synthetiques reproduisant les pieges
releves sur 'Dossier 7 - Liaison_225kV_AE_AS_EP.xml'.

    python -m pytest tests -q
"""
from io import BytesIO

import pytest

from src.signalisations.lot_parser import block_names, parse_lot


def lot(body, indice="22", libelle="Liaison_225kV_AE_AS_EP_SE"):
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        '<TrancheType IndiceTT="%s" LibelléTT="%s" Périmètre="Tranche numérisée">'
        '<Conduite><Signalisations>%s</Signalisations></Conduite></TrancheType>'
        % (indice, libelle, body)
    )
    return parse_lot(BytesIO(xml.encode("ISO-8859-1")))


def sig(reference, idrc, instances=()):
    inner = "".join(
        '<Instance LibelléInstance="%s" IDRC="%s"/>' % pair for pair in instances
    )
    return '<Signalisation Référence="%s" IDRC="%s" Inversion="non">%s</Signalisation>' % (
        reference, idrc, inner)


def test_type_de_tranche():
    result = lot(sig("DT.PX", "ID000607"))
    assert result["type_tranche"]["IndiceTT"] == "22"
    assert result["type_tranche"]["LibelléTT"] == "Liaison_225kV_AE_AS_EP_SE"


def test_bloc_simple():
    result = lot("<!-- PX -->" + sig("DT.PX", "ID000607") + "<!-- FIN PX -->")
    assert [e["fonction"] for e in result["entrees"]] == ["PX"]
    assert result["avertissements"] == []


def test_instances_une_ligne_chacune():
    """'DT.PX*' est un gabarit : ses instances portent chacune son IDRC."""
    result = lot("<!-- PX -->" + sig("DT.PX*", "ID000607", [
        ("DT.PX", "ID000608"), ("DT.PX1", "ID000609"), ("DT.PX2", "ID000610"),
    ]) + "<!-- FIN PX -->")
    entries = result["entrees"]
    assert [e["instance"] for e in entries] == ["DT.PX", "DT.PX1", "DT.PX2"]
    assert [e["idrc"] for e in entries] == ["ID000608", "ID000609", "ID000610"]
    assert {e["idrc_gabarit"] for e in entries} == {"ID000607"}
    assert all(e["fonction"] == "PX" for e in entries)


def test_signalisation_sans_instance():
    result = lot("<!-- EP -->" + sig("EP.DECL", "ID001000") + "<!-- FIN EP -->")
    entry = result["entrees"][0]
    assert entry["instance"] == "" and entry["idrc"] == "ID001000"


def test_banniere_ignoree():
    body = ("<!-- *********DJ********* -->" + sig("POS.DJ", "ID002000"))
    result = lot(body)
    assert result["entrees"][0]["fonction"] is None
    assert [s["nom"] for s in result["sections"]] == ["DJ"]
    assert result["avertissements"] == []


def test_note_de_modification_ignoree():
    body = ("<!-- TDPR -->" + sig("TDPR.1", "ID003000")
            + "<!-- GMA - 28/05/2019 - LOT H1 - Modification 1029 -->"
            + sig("TDPR.2", "ID003001") + "<!-- FIN TDPR -->")
    result = lot(body)
    assert [e["fonction"] for e in result["entrees"]] == ["TDPR", "TDPR"]
    assert result["avertissements"] == []


def test_commentaire_descriptif_non_pris_pour_un_bloc():
    body = ("<!-- TCAB SF6 LIGNE -->"
            "<!-- Traversée SF6 et têtes de câbles SF6 -->"
            + sig("TCAB.1", "ID004000") + "<!-- FIN TCAB SF6 -->")
    result = lot(body)
    assert [e["fonction"] for e in result["entrees"]] == ["TCAB SF6 LIGNE"]
    assert block_names(result) == ["TCAB SF6 LIGNE"]


@pytest.mark.parametrize("ouverture, fermeture", [
    ("POSITIONS DES ORGANES", "FIN POSITION DES ORGANES"),   # pluriel
    ("REBTAM", "Fin REBTAM"),                                # minuscules
    ("TCAB SF6 LIGNE", "FIN TCAB SF6"),                      # abrege
    ("PMC sur ligne hors SP", "FIN PMC"),                    # abrege
    ("ECH-CDS", "FIN ECH-CDS"),
])
def test_fermetures_non_litterales(ouverture, fermeture):
    result = lot("<!-- %s -->%s<!-- %s -->"
                 % (ouverture, sig("X.1", "ID005000"), fermeture))
    assert result["entrees"][0]["fonction"] == ouverture
    assert result["avertissements"] == []


def test_blocs_disjoints_de_meme_fonction():
    """ARS apparaît quatre fois dans le lot : union de ses blocs."""
    body = ("<!-- ARS -->" + sig("ARS.1", "ID006000") + "<!-- FIN ARS -->"
            + sig("HORS.BLOC", "ID006001")
            + "<!-- ARS -->" + sig("ARS.2", "ID006002") + "<!-- FIN ARS -->")
    result = lot(body)
    assert [e["fonction"] for e in result["entrees"]] == ["ARS", None, "ARS"]
    assert len(result["blocs"]) == 2
    assert block_names(result) == ["ARS"]


def test_blocs_imbriques():
    body = ("<!-- COMMUN TRANCHE -->" + sig("A", "ID007000")
            + "<!-- PDB -->" + sig("B", "ID007001") + "<!-- FIN PDB -->"
            + "<!-- FIN COMMUN TRANCHE -->")
    result = lot(body)
    entries = result["entrees"]
    assert entries[0]["fonctions"] == ["COMMUN TRANCHE"]
    assert entries[1]["fonctions"] == ["COMMUN TRANCHE", "PDB"]
    assert entries[1]["fonction"] == "PDB"


def test_bloc_non_ferme_signale():
    result = lot("<!-- PX -->" + sig("DT.PX", "ID000607"))
    assert result["entrees"][0]["fonction"] is None
    assert result["avertissements"] == ["Bloc ouvert et jamais fermé : 'PX'."]


def test_fermeture_orpheline_signalee():
    result = lot(sig("DT.PX", "ID000607") + "<!-- FIN PX -->")
    assert result["avertissements"] == ["Fermeture sans ouverture : 'FIN PX'."]


def test_signalisations_commandes():
    body = ('<Conduite><SignalisationsCommandes>'
            '<!-- PSL-PSC -->'
            '<SignalisationCommande Référence="MES.PSL PSC" IDRC="ID012165"'
            ' Inversion="non" TDéfautExtérieur="5"/>'
            '<!-- FIN PSL-PSC -->'
            '</SignalisationsCommandes></Conduite>')
    xml = ('<?xml version="1.0" encoding="ISO-8859-1"?>'
           '<TrancheType IndiceTT="22" LibelléTT="L">%s</TrancheType>' % body)
    result = parse_lot(BytesIO(xml.encode("ISO-8859-1")))
    entry = result["entrees"][0]
    assert entry["type"] == "signalisation_commande"
    assert (entry["idrc"], entry["fonction"]) == ("ID012165", "PSL-PSC")
