"""Incadrarea pe categorii a articolelor, dupa denumire.

Regulile sunt ordonate: prima care se potriveste castiga. Ordinea conteaza -
"Capac Baterie" e o piesa de carcasa, nu o baterie, asa ca 'capac' vine inainte
de 'baterie'.
"""
import re, unicodedata

def fold(t):
    t = unicodedata.normalize("NFKD", str(t))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()

REGULI = [
    ("Huse si carcase",       r"\bhusa\b|\bhuse\b|\btoc\b|flipcover|\btpu\b|carcasa|capac baterie|capac spate|capac iphone|capac -|\bskin\b"),
    ("Folii de protectie",    r"\bfolie\b|\bfolii\b|laminare|sticla protectie|sticla securizata|hydrogel|\bstp crystal\b"),
    ("Ecrane si display",     r"\becran\b|display|\blcd\b|touchscreen|ansamblu lcd|\bpanel\b|barete? led|bareta tv|\bt-con\b"),
    ("Baterii si acumulatori", r"baterie|baterii|acumulator|powerbank|\bli-p\b|\bli-ion\b|\bli-pol\b|\bni-mh\b|\bmah\b"),
    ("Incarcatoare si alimentare", r"incarcator|adaptor priza|sursa|alimentare|\bmufa dc\b|posac|modul incarcare|conector incarcare|flex incarcare|banda incarcare"),
    ("Cabluri si adaptoare",  r"\bcablu\b|adaptor|\bhdmi\b|\bdvi\b|\bvga\b|\bjack\b|\bmufa\b|\bcablu iso\b"),
    ("Conectori si benzi flex", r"conector|\bflex\b|\bbanda\b|\bbareta\b|\bfpc\b|\bffc\b|tavita sim|suport sim|cititor sim"),
    ("Camere si senzori",     r"\bcamera\b|geam camera|sticla camera|senzor|microfon|difuzor|buzzer|sonerie|\bcasca\b"),
    ("Memorii si stocare",    r"\bstick\b|card sd|\bssd\b|\bram ddr\b|\bhdd\b|\brack\b|flash usb|cititor carduri|memorie"),
    ("Audio",                 r"\bcasti\b|handsfree|\bhertz\b|difuzoare|receptor bluetooth|audio|\bboxa\b|speaker"),
    ("Auto",                  r"\bauto\b|modulator fm|oglinda|compotech|\bopel\b|\brenault\b"),
    ("Laptop si PC",          r"laptop|tastatura|\basus\b|\bacer\b|\bkit placa baza\b|placa baza|ventilator|espressor|filtru apa"),
    ("Console",               r"\bps4\b|\bps5\b|playstation|joystick|controller|dualse|\bxbox\b"),
    ("Componente electronice", r"\bci cmos\b|\bic smd\b|mosfet|dioda|\birf\b|\birs\b|\bnte\b|\bntc\b|\bmicrochip\b|\btd15\b|\bstu\b|\bdda\b|\bncp\b|\bap1507\b|\bbq2\b|\bsta5\b|rasber|\bp1000b\b|rezistor|\bbareta 1x40\b|\br16148\b|\bwkgq\b|\bu5005\b|\bdalpo\b|\bhp470\b|\bgh64\b|\besselte\b|\blinijka\b"),
    ("Telefoane si tablete",  r"\btelefon\b|\bmaxcom\b|motorola edge|redmi note 8 pro|\bmediapad\b|\btableta\b"),
    ("Scule si intretinere",  r"\bflux\b|sita bga|microscop|programator|instrument|\bwd-?40\b|\bwd40\b|garnituri|\br-sim\b|telecomanda|\bcurier\b|transport|livrare"),
]

COMPILATE = [(nume, re.compile(rx)) for nume, rx in REGULI]

def categorie(nume):
    n = fold(nume)
    for eticheta, rx in COMPILATE:
        if rx.search(n):
            return eticheta
    return "Altele"
