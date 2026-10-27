import hashlib
import re
import unicodedata

_SUFFIXES = {"srl", "sa", "ltd", "gmbh", "llc", "inc", "corp"}


def normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"(?:s\W*r\W*l|s\W*a|l\W*t\W*d|g\W*m\W*b\W*h|l\W*l\W*c|i\W*n\W*c|c\W*o\W*r\W*p)\W*$", "", value)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    words = [word for word in value.split() if word not in _SUFFIXES]
    return " ".join(words).strip()


def fingerprint(company: str, title: str, city: str = "") -> str:
    value = "|".join((normalise(company), normalise(title), normalise(city)))
    return hashlib.sha256(value.encode()).hexdigest()
