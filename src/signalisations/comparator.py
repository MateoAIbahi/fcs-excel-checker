"""
Comparaison des signalisations : lot, FCS et dicodata.

Contrairement a la phase 1, qui faisait une difference d'ensembles de codes,
on construit ici un TABLEAU : une ligne par signalisation, avec des colonnes
de provenance (lot / FCS / dicodata). C'est une jointure, cle = IDRC.

Les deux controles du devis se lisent alors dans la colonne Statut :

* lot -> FCS : 'Prévue au lot, absente du FCS'
* FCS -> lot et dicodata : 'Présente au FCS, absente du lot', completee par
  la presence ou non au dicodata.

Point de methode important, mesure sur MAUGE : le lot est un CATALOGUE du
type de tranche, pas la liste de ce qui est installe. Compare brutalement,
il fait ressortir 237 signalisations manquantes sur 330 pour une tranche qui
n'en a aucune en trop. Le premier controle est donc restreint aux fonctions
reellement declarees au FCS pour la tranche (voir fonctions.map_functions) ;
les autres blocs sont comptes a part, sans etre presentes comme des ecarts.
"""

from src.signalisations.dicodata import describe
from src.signalisations.fcs_signals import tranches_of_type
from src.signalisations.fonctions import map_functions
from src.signalisations.lot_parser import block_names

STATUS_OK = "Présente des deux côtés"
STATUS_LOT_ONLY = "Prévue au lot, absente du FCS"
STATUS_FCS_ONLY = "Présente au FCS, absente du lot"
STATUS_FCS_OUT_OF_SCOPE = "Présente au FCS, fonction non installée sur la tranche"

TYPE_LABELS = {
    "signalisation": "Signalisation",
    "signalisation_commande": "Signalisation de commande",
}


def compare_site(fcs, lots, dicodata=None, overrides=None):
    """
    fcs   : sortie de fcs_signals.read_fcs_signals
    lots  : iterable de (nom de fichier, sortie de lot_parser.parse_lot)
    Retourne {"lignes": [...], "tranches": {...}, "avertissements": [...]}.
    """
    rows, summary, warnings = [], {}, []
    covered = set()

    for filename, lot in lots:
        libelle = lot["type_tranche"].get("LibelléTT", "")
        indice = lot["type_tranche"].get("IndiceTT", "")
        targets = tranches_of_type(fcs, libelle, indice)
        if not targets:
            warnings.append(
                "%s : aucun type de tranche '%s' dans le FCS." % (filename, libelle))
            continue

        blocks = block_names(lot)
        for tranche in targets:
            covered.add(tranche)
            entry = fcs["tranches"][tranche]
            mapping = map_functions(entry["fonctions"], blocks, overrides)
            tranche_rows = _compare_tranche(
                tranche, entry, lot, filename, mapping, dicodata)
            rows.extend(tranche_rows)
            summary[tranche] = _summarize(tranche, entry, lot, filename,
                                          mapping, tranche_rows)

    for tranche in sorted(set(fcs["tranches"]) - covered):
        summary[tranche] = {
            "tranche": tranche,
            "type": fcs["tranches"][tranche]["type"][0],
            "statut": "Aucun fichier de lot fourni pour ce type de tranche",
        }
    return {"lignes": rows, "tranches": summary, "avertissements": warnings}


METHOD_COMMON_BLOCK = "bloc commun (présent au FCS)"


def _common_blocks(lot, mapping, fcs_signals):
    """
    Certains blocs ne correspondent a aucune fonction parce que ce n'en sont
    pas : 'COMMUN TRANCHE', 'DISJONCTEUR', 'SA', 'POSITION DES ORGANES'
    portent les signalisations des parties communes et des organes. Les
    ecarter ferait passer leurs signalisations pour 'non installees'.

    Un tel bloc est retenu des qu'au moins une de ses signalisations figure
    au FCS de la tranche : la preuve qu'il s'y applique. Regle a valider
    avec le client.
    """
    common = set()
    for item in lot["entrees"]:
        block = item["fonction"]
        if not block or block in common:
            continue
        if block in mapping["blocs_sans_fonction"] and item["idrc"] in fcs_signals:
            common.add(block)
    return common


def _compare_tranche(tranche, entry, lot, filename, mapping, dicodata):
    """Une ligne par signalisation, cote lot puis cote FCS."""
    installed = {info["bloc"]: (function, info["methode"])
                 for function, info in mapping["correspondances"].items()}
    for block in _common_blocks(lot, mapping, entry["signalisations"]):
        installed.setdefault(block, ("", METHOD_COMMON_BLOCK))
    fcs_signals = entry["signalisations"]
    rows, seen = [], set()

    for item in lot["entrees"]:
        block = item["fonction"]
        if block not in installed:
            continue                      # fonction non installee sur la tranche
        function, method = installed[block]
        idrc = item["idrc"]
        present = idrc in fcs_signals
        seen.add(idrc)
        rows.append(_row(
            tranche, entry, function, block, method, item["type"], idrc,
            reference=item["reference"], instance=item["instance"],
            in_lot=True, fcs=fcs_signals.get(idrc), dicodata=dicodata,
            status=STATUS_OK if present else STATUS_LOT_ONLY, source=filename))

    lot_index = {item["idrc"]: item for item in lot["entrees"]}
    for idrc, signal in fcs_signals.items():
        if idrc in seen:
            continue
        item = lot_index.get(idrc)
        status = STATUS_FCS_OUT_OF_SCOPE if item else STATUS_FCS_ONLY
        rows.append(_row(
            tranche, entry,
            function="", block=item["fonction"] if item else "", method="",
            kind=item["type"] if item else signal["type"], idrc=idrc,
            reference=item["reference"] if item else "",
            instance=item["instance"] if item else "",
            in_lot=bool(item), fcs=signal, dicodata=dicodata,
            status=status, source=filename))
    return rows


def _row(tranche, entry, function, block, method, kind, idrc, reference,
         instance, in_lot, fcs, dicodata, status, source):
    reference_dico = describe(dicodata, idrc)
    return {
        "Tranche": tranche,
        "Type de tranche": entry["type"][0],
        "Fichier de lot": source,
        "Fonction FCS": function,
        "Bloc du lot": block or "",
        "Méthode": method or "",
        "Type": TYPE_LABELS.get(kind, kind),
        "Référence lot": reference or "",
        "Instance": instance or "",
        "IDRC": idrc,
        "Mnémonique FCS": fcs["code"] if fcs else "",
        "Libellé FCS": fcs["LibelléLongInformationConduite"] if fcs else "",
        "Présente au lot": "oui" if in_lot else "non",
        "Présente au FCS": "oui" if fcs else "non",
        "Connue du dicodata": "oui" if reference_dico else "non",
        # dd_idrc_it n'a pas les memes colonnes qu'information_type : les
        # champs absents sont simplement vides.
        "Mnémonique dicodata": (reference_dico or {}).get("mnemonique", ""),
        "Libellé dicodata": (reference_dico or {}).get("libellé", ""),
        "Statut": status,
    }


def _summarize(tranche, entry, lot, filename, mapping, rows):
    counts = {}
    for row in rows:
        counts[row["Statut"]] = counts.get(row["Statut"], 0) + 1
    return {
        "tranche": tranche,
        "type": entry["type"][0],
        "fichier": filename,
        "fonctions": len(entry["fonctions"]),
        "fonctions_avec_bloc": len(mapping["correspondances"]),
        "fonctions_sans_bloc": mapping["sans_bloc"],
        "signalisations_fcs": len(entry["signalisations"]),
        "statut": "",
        "compte": counts,
    }
