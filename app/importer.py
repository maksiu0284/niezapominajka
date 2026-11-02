"""Niezapominajka – import danych z Excela (pracownicy, pojazdy, maszyny, terminy).

Przebieg: właściciel pobiera wzór, uzupełnia arkusze, wgrywa plik, program pokazuje
podgląd z błędami i dopiero po zatwierdzeniu zapisuje wszystko w jednej transakcji.
"""
import io
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from . import config, db, services as svc

SHEETS = {"employees": "Pracownicy", "vehicles": "Pojazdy", "machines": "Maszyny"}
TERM_SHEET = "Terminy"
MODULE_BY_LABEL = {m["label"].lower(): k for k, m in config.MODULES.items()}
UNIT_BY_LABEL = {"dni": "days", "dzień": "days", "dni.": "days", "miesięcy": "months", "miesiące": "months",
                 "miesiąc": "months", "mies.": "months", "lat": "years", "lata": "years", "rok": "years"}

TERM_COLUMNS = [
    ("module", "Moduł", True), ("object", "Dotyczy", False), ("category", "Rodzaj sprawy", True),
    ("title", "Opis / szczegół", False), ("due_date", "Termin", True), ("interval_value", "Co ile", False),
    ("interval_unit", "Jednostka (dni / miesięcy / lat)", False), ("responsible", "Osoba odpowiedzialna", False),
    ("remind_days", "Przypomnienie (dni przed)", False), ("counterparty", "Kontrahent / urząd", False),
    ("amount", "Kwota", False), ("document_number", "Nr dokumentu", False), ("notes", "Uwagi", False),
]


def _object_columns(module):
    return [(f["name"], f["label"] + (" *" if f.get("required") else ""), f) for f in config.MODULES[module]["fields"]]


# ---------------------------------------------------------------- wzór

def template_xlsx():
    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2D5BA8")
    info = wb.active
    info.title = "Instrukcja"
    rows = [
        [f"{config.APP_NAME} – wzór importu danych"], [],
        ["1. Uzupełnij arkusze Pracownicy, Pojazdy, Maszyny i Terminy. Kolumny z gwiazdką (*) są wymagane."],
        ["2. Daty wpisuj jako datę Excela albo w formacie RRRR-MM-DD lub DD.MM.RRRR."],
        ["3. Kierowcę, opiekuna i osobę odpowiedzialną wpisz jako „Imię Nazwisko” – tak jak w arkuszu Pracownicy lub w programie."],
        ["4. W arkuszu Terminy kolumna „Dotyczy”:"],
        ["    • Pracownicy – „Imię Nazwisko”,  • Pojazdy – numer rejestracyjny,  • Maszyny – numer inwentarzowy lub nazwa,"],
        ["    • Sprawy firmy – zostaw puste (kontrahenta wpisz w kolumnie „Kontrahent / urząd”)."],
        ["5. Nieznany rodzaj sprawy zostanie dodany do listy rodzajów."],
        ["6. Termin cykliczny: wpisz „Co ile” (np. 12) i jednostkę (dni / miesięcy / lat)."],
        ["7. Wgraj plik w Panelu właściciela → Import z Excela. Program najpierw pokaże podgląd i błędy."],
        [], ["Przykład wiersza w arkuszu Terminy:"],
        ["Pojazdy", "DW 12345", "Przegląd techniczny", "", "2027-03-15", 12, "miesięcy", "Jan Kowalski", "", "", "", "", ""],
    ]
    for r in rows:
        info.append(r)
    info["A1"].font = Font(bold=True, size=14, color="2D5BA8")
    info.column_dimensions["A"].width = 110

    for module, title in SHEETS.items():
        ws = wb.create_sheet(title)
        cols = _object_columns(module)
        ws.append([label for _, label, _ in cols])
        for i, (_, label, f) in enumerate(cols, start=1):
            cell = ws.cell(row=1, column=i)
            cell.font, cell.fill = head_font, head_fill
            cell.alignment = Alignment(vertical="center")
            ws.column_dimensions[cell.column_letter].width = max(16, len(label) + 4)
        ws.freeze_panes = "A2"
    ws = wb.create_sheet(TERM_SHEET)
    ws.append([label + (" *" if req else "") for _, label, req in TERM_COLUMNS])
    for i in range(1, len(TERM_COLUMNS) + 1):
        cell = ws.cell(row=1, column=i)
        cell.font, cell.fill = head_font, head_fill
        ws.column_dimensions[cell.column_letter].width = max(16, len(str(cell.value)) + 4)
    ws.freeze_panes = "A2"
    dv = DataValidation(type="list", formula1='"' + ",".join(m["label"] for m in config.MODULES.values()) + '"',
                        allow_blank=False)
    dv2 = DataValidation(type="list", formula1='"dni,miesięcy,lat"', allow_blank=True)
    ws.add_data_validation(dv)
    ws.add_data_validation(dv2)
    dv.add("A2:A2000")
    dv2.add("G2:G2000")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- odczyt

def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return " ".join(str(v).split())


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _text(v)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _num(v, integer=False):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v) if integer else float(v)
    s = _text(v).replace(" ", "").replace(",", ".")
    try:
        return int(float(s)) if integer else float(s)
    except ValueError:
        return "BŁĄD"


def _rows(ws):
    header = [(_text(c.value).rstrip(" *").lower()) for c in ws[1]]
    for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row is None or all(v in (None, "") for v in row):
            continue
        yield idx, {header[i]: row[i] for i in range(min(len(header), len(row))) if header[i]}


def _emp_key(name):
    return " ".join(str(name or "").lower().split())


def parse(content: bytes):
    """Zwraca (plan, błędy, ostrzeżenia). Plan zawiera gotowe rekordy do zapisu."""
    errors, warnings = [], []
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    except Exception:
        return None, [("plik", 0, "To nie jest poprawny plik Excela (.xlsx).")], []
    plan = {"employees": [], "vehicles": [], "machines": [], "terms": [], "new_categories": []}

    existing_emps = {_emp_key(f"{e['first_name']} {e['last_name']}"): e["id"] for e in svc.employees_brief()}
    new_emps = set()

    for module, title in SHEETS.items():
        if title not in wb.sheetnames:
            continue
        cols = _object_columns(module)
        meta = config.MODULES[module]
        seen_unique = {}
        for rownum, row in _rows(wb[title]):
            rec, emp_refs = {}, {}
            for name, label, f in cols:
                raw = row.get(f["label"].lower())
                if f["type"] == "date":
                    val = _date(raw) if raw not in (None, "") else None
                    if raw not in (None, "") and not val:
                        errors.append((title, rownum, f"„{f['label']}”: nieprawidłowa data „{_text(raw)}”."))
                    val = val.isoformat() if val else None
                elif f["type"] == "number":
                    val = _num(raw, integer=True)
                    if val == "BŁĄD":
                        errors.append((title, rownum, f"„{f['label']}” musi być liczbą."))
                        val = None
                elif f["type"] == "select":
                    lbl = _text(raw).lower()
                    val = next((k for k, v in f["options"].items() if v.lower() == lbl or k == lbl), f.get("default"))
                elif f["type"] == "employee":
                    val = None
                    if _text(raw):
                        emp_refs[name] = _text(raw)
                else:
                    val = _text(raw) or None
                    if val and f.get("upper"):
                        val = val.upper()
                if f.get("required") and val in (None, "") and f["type"] != "employee":
                    errors.append((title, rownum, f"Brak wymaganego pola „{f['label']}”."))
                if f["type"] == "email" and val and "@" not in val:
                    errors.append((title, rownum, f"Nieprawidłowy e-mail „{val}”."))
                if f.get("unique") and val:
                    key = val.lower()
                    if key in seen_unique:
                        errors.append((title, rownum, f"{f['label']} „{val}” powtarza się (wiersz {seen_unique[key]})."))
                    elif db.one(f"SELECT id FROM {meta['table']} WHERE {name}=? COLLATE NOCASE", (val,)):
                        errors.append((title, rownum, f"{f['label']} „{val}” jest już w programie."))
                    seen_unique[key] = rownum
                rec[name] = val
            if module == "employees" and rec.get("first_name") and rec.get("last_name"):
                k = _emp_key(f"{rec['first_name']} {rec['last_name']}")
                if k in existing_emps or k in new_emps:
                    warnings.append((title, rownum, f"Pracownik „{rec['first_name']} {rec['last_name']}” już istnieje – zostanie dodany drugi raz."))
                new_emps.add(k)
            plan[module].append({"row": rownum, "data": rec, "emp_refs": emp_refs})

    known_emps = set(existing_emps) | new_emps
    for module in ("vehicles", "machines"):
        for item in plan[module]:
            for name, ref in item["emp_refs"].items():
                if _emp_key(ref) not in known_emps:
                    errors.append((SHEETS[module], item["row"], f"Nie znaleziono pracownika „{ref}”."))

    # Indeksy obiektów do arkusza Terminy
    veh_keys = {v["registration"].lower() for v in svc.all_objects("vehicles") if v.get("registration")}
    veh_keys |= {i["data"]["registration"].lower() for i in plan["vehicles"] if i["data"].get("registration")}
    mach_keys = set()
    for m in svc.all_objects("machines"):
        mach_keys |= {str(m.get("inventory_number") or "").lower(), str(m.get("name") or "").lower()}
    for i in plan["machines"]:
        mach_keys |= {str(i["data"].get("inventory_number") or "").lower(), str(i["data"].get("name") or "").lower()}
    mach_keys.discard("")
    cats = {(c["module"], c["name"].lower()) for c in svc.categories()}

    if TERM_SHEET in wb.sheetnames:
        for rownum, row in _rows(wb[TERM_SHEET]):
            g = {key: row.get(label.lower()) for key, label, _ in TERM_COLUMNS}
            module = MODULE_BY_LABEL.get(_text(g["module"]).lower())
            if not module:
                errors.append((TERM_SHEET, rownum, f"Nieznany moduł „{_text(g['module'])}”. Użyj: Pracownicy, Pojazdy, Maszyny, Sprawy firmy."))
                continue
            obj = _text(g["object"])
            if module == "employees" and _emp_key(obj) not in known_emps:
                errors.append((TERM_SHEET, rownum, f"Nie znaleziono pracownika „{obj}”."))
            if module == "vehicles" and obj.lower() not in veh_keys:
                errors.append((TERM_SHEET, rownum, f"Nie znaleziono pojazdu o numerze „{obj}”."))
            if module == "machines" and obj.lower() not in mach_keys:
                errors.append((TERM_SHEET, rownum, f"Nie znaleziono maszyny „{obj}”."))
            category = _text(g["category"])
            if not category:
                errors.append((TERM_SHEET, rownum, "Brak rodzaju sprawy."))
            elif (module, category.lower()) not in cats:
                cats.add((module, category.lower()))
                plan["new_categories"].append((module, category))
                warnings.append((TERM_SHEET, rownum, f"Nowy rodzaj sprawy „{category}” zostanie dodany."))
            due = _date(g["due_date"])
            if not due:
                errors.append((TERM_SHEET, rownum, f"Nieprawidłowa lub pusta data terminu „{_text(g['due_date'])}”."))
            iv = _num(g["interval_value"], integer=True)
            iu_raw = _text(g["interval_unit"]).lower()
            iu = UNIT_BY_LABEL.get(iu_raw, iu_raw if iu_raw in config.INTERVAL_UNITS else None)
            if iv == "BŁĄD" or (iv is not None and iv < 1):
                errors.append((TERM_SHEET, rownum, "„Co ile” musi być liczbą większą od zera."))
                iv = None
            if iv and not iu:
                errors.append((TERM_SHEET, rownum, "Podaj jednostkę cyklu: dni, miesięcy albo lat."))
            remind = _num(g["remind_days"], integer=True)
            if remind == "BŁĄD" or (remind is not None and not 0 <= remind <= 365):
                errors.append((TERM_SHEET, rownum, "Przypomnienie: liczba dni 0–365."))
                remind = None
            amount = _num(g["amount"])
            if amount == "BŁĄD":
                errors.append((TERM_SHEET, rownum, "Kwota musi być liczbą."))
                amount = None
            resp = _text(g["responsible"])
            if resp and _emp_key(resp) not in known_emps:
                errors.append((TERM_SHEET, rownum, f"Nie znaleziono osoby odpowiedzialnej „{resp}”."))
            plan["terms"].append({"row": rownum, "module": module, "object": obj, "category": category,
                                  "title": _text(g["title"]) or None, "due_date": due.isoformat() if due else None,
                                  "interval_value": iv if iu else None, "interval_unit": iu if iv else None,
                                  "remind_days": remind, "responsible": resp, "counterparty": _text(g["counterparty"]) or None,
                                  "amount": amount, "document_number": _text(g["document_number"]) or None,
                                  "notes": _text(g["notes"]) or None})
    total = sum(len(plan[k]) for k in ("employees", "vehicles", "machines", "terms"))
    if total == 0 and not errors:
        errors.append(("plik", 0, "Plik nie zawiera danych do importu. Uzupełnij arkusze wzoru."))
    return plan, errors, warnings


# ---------------------------------------------------------------- zapis

def apply(plan, user_id):
    """Zapisuje plan w jednej transakcji. Zwraca liczniki."""
    now = db.now_str()
    counts = {"employees": 0, "vehicles": 0, "machines": 0, "terms": 0, "categories": 0}
    with db.tx() as conn:
        emp_ids = {}
        for e in conn.execute("SELECT id, first_name, last_name FROM employees").fetchall():
            emp_ids[_emp_key(f"{e['first_name']} {e['last_name']}")] = e["id"]
        for item in plan["employees"]:
            d = dict(item["data"])
            cols = list(d) + ["created_at", "updated_at"]
            cur = conn.execute(f"INSERT INTO employees({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                               list(d.values()) + [now, now])
            emp_ids[_emp_key(f"{d['first_name']} {d['last_name']}")] = cur.lastrowid
            counts["employees"] += 1
        obj_ids = {"vehicles": {}, "machines": {}}
        for module in ("vehicles", "machines"):
            for item in plan[module]:
                d = dict(item["data"])
                for name, ref in item["emp_refs"].items():
                    d[name] = emp_ids.get(_emp_key(ref))
                cols = list(d) + ["created_at", "updated_at"]
                cur = conn.execute(f"INSERT INTO {module}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                   list(d.values()) + [now, now])
                counts[module] += 1
        for r in conn.execute("SELECT id, registration FROM vehicles").fetchall():
            obj_ids["vehicles"][str(r["registration"]).lower()] = r["id"]
        for r in conn.execute("SELECT id, name, inventory_number, responsible_employee_id FROM machines").fetchall():
            obj_ids["machines"].setdefault(str(r["name"] or "").lower(), r["id"])
            if r["inventory_number"]:
                obj_ids["machines"][str(r["inventory_number"]).lower()] = r["id"]
        for module, name in plan["new_categories"]:
            cur = conn.execute("INSERT OR IGNORE INTO categories(module,name,sort) VALUES(?,?,99)", (module, name))
            counts["categories"] += cur.rowcount
        for t in plan["terms"]:
            m = t["module"]
            oid = None
            if m == "employees":
                oid = emp_ids.get(_emp_key(t["object"]))
            elif m in obj_ids:
                oid = obj_ids[m].get(t["object"].lower())
            resp = emp_ids.get(_emp_key(t["responsible"])) if t["responsible"] else None
            if resp is None:
                if m == "employees":
                    resp = oid
                elif m in ("vehicles", "machines") and oid:
                    row = conn.execute(f"SELECT responsible_employee_id FROM {m} WHERE id=?", (oid,)).fetchone()
                    resp = row["responsible_employee_id"] if row else None
            conn.execute(
                """INSERT INTO terms(module,object_id,category,title,due_date,status,interval_value,interval_unit,
                   remind_days,responsible_employee_id,counterparty,amount,document_number,notes,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,'open',?,?,?,?,?,?,?,?,?,?,?)""",
                (m, oid, t["category"], t["title"], t["due_date"], t["interval_value"], t["interval_unit"],
                 t["remind_days"], resp, t["counterparty"], t["amount"], t["document_number"], t["notes"],
                 user_id, now, now))
            counts["terms"] += 1
    return counts
