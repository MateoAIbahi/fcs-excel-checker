import re
import unicodedata


def normalize(value):
    if value is None:
        return ""

    value = str(value).strip()
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.upper()

    value = value.replace(" ", "")
    value = value.replace("-", "")
    value = value.replace("_", "")
    value = value.replace(".", "")

    return value


def is_tg_file(filename):
    name = normalize(filename)
    return "E9" in name or "TG" in name or "TRANCHEGENERALE" in name


def clean_code(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value or value.lower() == "nan":
        return None

    return value


def is_section_title(value):
    if not value:
        return True

    return bool(re.match(r"^\d{2}[- ]", str(value).strip()))