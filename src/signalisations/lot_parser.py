"""
Lecture d'un fichier de lot (XML), une des trois sources de la phase 2.

Un lot decrit UN type de tranche : sa racine est <TrancheType LibelléTT=...
IndiceTT=...>, et c'est ce couple qui le rattache aux tranches du FCS.

Les signalisations sont a plat sous Conduite/Signalisations (et
Conduite/SignalisationsCommandes). Le regroupement par fonction n'existe que
sous forme de COMMENTAIRES XML encadrant les lignes :

    <!-- PX -->  ... signalisations ...  <!-- FIN PX -->

D'ou les precautions prises ici :

* Les bannieres decoratives (<!-- ****DJ**** -->) ne sont pas des blocs.
* Les notes de modification (<!-- GMA - 28/05/2019 - LOT H1 ... -->)
  s'intercalent au milieu des blocs et ne doivent pas casser l'appariement.
* Les commentaires descriptifs ('Polarite declenchement de la voie de
  secours') ressemblent a des ouvertures : n'est retenu comme bloc que ce
  qui trouve une fermeture.
* Ouvertures et fermetures ne sont pas litterales : 'POSITIONS DES ORGANES'
  ferme sur 'FIN POSITION DES ORGANES', 'TCAB SF6 LIGNE' sur
  'FIN TCAB SF6', 'REBTAM' sur 'Fin REBTAM'.
* Une meme fonction peut avoir PLUSIEURS blocs disjoints (ARS apparait
  quatre fois) : ses signalisations sont l'union de ses blocs.

Le lecteur ne traduit pas les noms de blocs en codes de fonction : cette
correspondance (exacte, partielle ou atypique) releve du comparateur et de
la table fournie par le client.
"""

import re

from lxml import etree

from src.utils import normalize

# <!-- *******DJ******* --> : banniere de section, pas un bloc.
BANNER_RE = re.compile(r"\*{3,}")

# <!-- GMA - 28/05/2019 - LOT H1 - Modification 1029 -->
NOTE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}|\bmodification\b", re.IGNORECASE)

CLOSER_RE = re.compile(r"^fin\b[\s:.-]*", re.IGNORECASE)

SIGNAL_TAGS = {
    "Signalisation": "signalisation",
    "SignalisationCommande": "signalisation_commande",
}


def parse_lot(file):
    """
    Retourne :
      {
        "type_tranche": {"LibelléTT": ..., "IndiceTT": ..., "Périmètre": ...},
        "entrees":   [ligne par signalisation concrete, voir _entry()],
        "blocs":     [{"nom", "debut", "fin", "entrees"}],
        "sections":  [bannieres rencontrees, pour information],
        "avertissements": [...],
      }
    """
    tree = etree.parse(file) if not hasattr(file, "getroot") else file
    root = tree.getroot()

    nodes = list(root.iter())
    positions = {id(node): index for index, node in enumerate(nodes)}
    blocks, sections, warnings = _read_blocks(nodes, positions)

    entries = []
    for node in nodes:
        kind = SIGNAL_TAGS.get(node.tag if isinstance(node.tag, str) else "")
        if not kind:
            continue
        position = positions[id(node)]
        names = [block["nom"] for block in blocks
                 if block["debut"] < position < block["fin"]]
        entries.extend(_entries_of(node, kind, names, position))

    for block in blocks:
        block["entrees"] = [entry for entry in entries
                            if block["debut"] < entry["position"] < block["fin"]]

    return {
        "type_tranche": dict(root.attrib),
        "entrees": entries,
        "blocs": blocks,
        "sections": sections,
        "avertissements": warnings,
    }


def _entries_of(node, kind, block_names, position):
    """
    Une ligne par signalisation concrete : chaque <Instance> quand il y en a
    (DT.PX*, gabarit, donne DT.PX, DT.PX1 et DT.PX2), sinon la signalisation
    elle-meme. Chaque instance porte son propre IDRC.
    """
    reference = node.get("Référence") or ""
    common = {
        "type": kind,
        "reference": reference,
        "idrc_gabarit": node.get("IDRC") or "",
        "inversion": node.get("Inversion") or "",
        "fonction": block_names[-1] if block_names else None,
        "fonctions": block_names,
        "statut": _import_status(node),
        "position": position,
    }

    instances = node.findall("Instance")
    if not instances:
        return [dict(common, instance="", idrc=common["idrc_gabarit"],
                     gabarit=bool("*" in reference))]

    return [
        dict(common,
             instance=instance.get("LibelléInstance") or "",
             idrc=instance.get("IDRC") or common["idrc_gabarit"],
             gabarit=False)
        for instance in instances
    ]


def _import_status(node):
    """Conditions d'applicabilite portees par <Import Statut="Obligatoire"...>."""
    imports = node.findall("Import")
    return imports[0].get("Statut") or "" if imports else ""


def _read_blocks(nodes, positions):
    """
    Apparie les commentaires d'ouverture et de fermeture.

    Principe : tout commentaire non decoratif est empile comme ouverture
    possible ; a la rencontre d'une fermeture, on depile jusqu'a trouver une
    ouverture compatible. Les entrees depilees au passage etaient des
    commentaires descriptifs, pas des blocs.
    """
    blocks, sections, warnings = [], [], []
    stack = []

    for node in nodes:
        if isinstance(node.tag, str):          # pas un commentaire
            continue
        text = (node.text or "").strip()
        position = positions[id(node)]

        if BANNER_RE.search(text):
            label = text.strip("* \t")
            if label:
                sections.append({"nom": label, "position": position})
            continue
        if not text or NOTE_RE.search(text):
            continue

        closing = CLOSER_RE.match(text)
        if not closing:
            stack.append({"nom": text, "debut": position})
            continue

        name = text[closing.end():].strip()
        index = _find_opener(stack, name)
        if index is None:
            warnings.append("Fermeture sans ouverture : '%s'." % text)
            continue
        opener = stack[index]
        del stack[index:]
        blocks.append({"nom": opener["nom"], "debut": opener["debut"],
                       "fin": position, "entrees": []})

    for opener in stack:
        warnings.append("Bloc ouvert et jamais fermé : '%s'." % opener["nom"])
    blocks.sort(key=lambda block: block["debut"])
    return blocks, sections, warnings


def _find_opener(stack, name):
    """
    Position dans la pile de l'ouverture que ferme `name`, la plus interne
    d'abord. Tolere les ecarts de redaction : pluriel ('POSITIONS DES
    ORGANES' / 'FIN POSITION DES ORGANES') et fermeture abregee
    ('TCAB SF6 LIGNE' / 'FIN TCAB SF6').
    """
    target = normalize(name)
    if not target:
        return None
    for index in range(len(stack) - 1, -1, -1):
        opener = normalize(stack[index]["nom"])
        if opener == target:
            return index
        if opener.startswith(target) or target.startswith(opener):
            return index
        if _singular(opener) == _singular(target):
            return index
    return None


def _singular(token):
    return re.sub(r"S(?=[A-Z]|$)", "", token)


def block_names(lot):
    """Noms de blocs distincts du lot, dans l'ordre de premiere apparition."""
    seen, names = set(), []
    for block in lot["blocs"]:
        if block["nom"] not in seen:
            seen.add(block["nom"])
            names.append(block["nom"])
    return names
