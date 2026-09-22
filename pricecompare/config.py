"""Which region and which chains to collect.

The Israeli Price Transparency Law (חוק קידום התחרות בענף המזון) requires every
large chain to publish full price files for every branch. Each chain publishes
through one of a few portals; the ones below are supported by this project.
"""

# A store is included when its City code matches, or when one of the names
# appears in the store's name / address / city fields (some chains leave the
# city code empty, e.g. Yohananof).
REGION = {
    "name": "חדרה",
    "city_codes": {"6500"},  # קוד יישוב של הלמ"ס
    "names": ["חדרה", "בית אליעזר", "גבעת אולגה"],
}

# Shufersal has its own portal.
SHUFERSAL = {"key": "shufersal", "name": "שופרסל"}

# Carrefour (formerly Yenot Bitan / Mega) has its own portal.
CARREFOUR = {"key": "carrefour", "name": "קרפור"}

# Chains that publish via the Cerberus portal (url.publishedprices.co.il).
# The username is public and the password is empty.
CERBERUS = [
    {"key": "ramilevy", "name": "רמי לוי", "user": "RamiLevi"},
    {"key": "yohananof", "name": "יוחננוף", "user": "yohananof"},
    {"key": "osherad", "name": "אושר עד", "user": "osherad"},
    {"key": "keshet", "name": "קשת טעמים", "user": "Keshet"},
    {"key": "tivtaam", "name": "טיב טעם", "user": "TivTaam"},
    {"key": "doralon", "name": "דור אלון", "user": "doralon"},
    {"key": "stopmarket", "name": "סטופמרקט", "user": "Stop_Market"},
    {"key": "politzer", "name": "פוליצר", "user": "politzer"},
    {"key": "salachdabach", "name": "סאלח דבאח", "user": "SalachD"},
    {"key": "freshmarket", "name": "פרש מרקט", "user": "freshmarket"},
]
