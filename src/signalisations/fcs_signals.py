"""
Lecture des signalisations du FCS, deuxieme source de la phase 2.

La phase 1 ne lit du FCS que ses fonctions (ObjetFonction). La phase 2 a
besoin, pour chaque tranche, de ses SIGNALISATIONS et de ses SIGNALISATIONS
DE COMMANDE, identifiees par leur IDRC : c'est la cle de jointure avec les
fichiers de lot et le dicodata.

Chaque tranche porte aussi 'LibelléTT' et 'IndiceTT', qui la rattachent a un
type de tranche, donc a un lot. Sur MAUGE, les 27 tranches se repartissent
en 12 types ; 'IndiceTT' y vaut 22 partout, c'est donc bien 'LibelléTT' qui
discrimine.
"""

from lxml import etree

SIGNAL_TAGS = {
    "Signalisation": "signalisation",
    "SignalisationCommande": "signalisation_commande",
}

# Attributs repris tels quels pour le rapport.
KEPT = (
    "LibelléCourtInformationConduite",
    "LibelléLongInformationConduite",
    "Désignation",
    "LibelléBlocFonctionnel",
    "LibelléSousBlocFonctionnel",
    "NatureSignalisation",
    "Inversion",
)


def read_fcs_signals(file):
    """
    Retourne :
      {
        "site": {"code", "nom"},
        "tranches": {
           "6CHOLE.1": {
              "type": ("Liaison_225kV_AE_AS_EP_SE", "22"),
              "fonctions": {"PXmulti-PX": "libellé long", ...},
              "signalisations": {"ID000607": {...}, ...},
           }, ...
        },
        "types": {("LibelléTT", "IndiceTT"): ["6CHOLE.1", ...]},
      }
    """
    parser = etree.XMLParser(recover=True)
    root = etree.parse(file, parser).getroot()

    site_node = root if root.tag == "Site" else root.find(".//Site")
    site = {
        "code": (site_node.get("CodeNationalSite") if site_node is not None else "") or "",
        "nom": (site_node.get("NomSite") if site_node is not None else "") or "",
    }

    tranches, types = {}, {}
    for node in root.iter("Tranche"):
        name = node.get("LibelléCourtTranche") or ""
        if not name:
            continue
        key = (node.get("LibelléTT") or "", node.get("IndiceTT") or "")
        tranches[name] = {
            "type": key,
            "libellé": node.get("LibelléLongTranche") or "",
            "fonctions": {
                objet.get("LibelléCourtObjetFonction") or "":
                    objet.get("LibelléLongObjetFonction") or ""
                for objet in node.iter("ObjetFonction")
                if objet.get("LibelléCourtObjetFonction")
            },
            "signalisations": _signals_of(node),
        }
        types.setdefault(key, []).append(name)

    return {"site": site, "tranches": tranches, "types": types}


def _signals_of(node):
    """{IDRC: signalisation}. Les doublons d'IDRC sont signales par 'doublon'."""
    signals = {}
    for element in node.iter():
        kind = SIGNAL_TAGS.get(element.tag if isinstance(element.tag, str) else "")
        if not kind:
            continue
        idrc = element.get("IDRC") or ""
        if not idrc:
            continue
        entry = {
            "type": kind,
            "idrc": idrc,
            "code": element.get("LibelléCourtInformationConduite") or "",
        }
        entry.update({key: element.get(key) or "" for key in KEPT})
        if idrc in signals:
            signals[idrc].setdefault("doublons", 0)
            signals[idrc]["doublons"] += 1
            continue
        signals[idrc] = entry
    return signals


def tranches_of_type(fcs, libelle_tt, indice_tt=None):
    """
    Tranches du FCS correspondant au type d'un lot. L'indice n'est utilise
    que s'il discrimine : il est identique pour tous les types sur les FCS
    observes, et une divergence ne doit pas faire perdre le rattachement.
    """
    exact = fcs["types"].get((libelle_tt, indice_tt or ""), [])
    if exact:
        return list(exact)
    return [name for (libelle, _indice), names in fcs["types"].items()
            if libelle == libelle_tt for name in names]
