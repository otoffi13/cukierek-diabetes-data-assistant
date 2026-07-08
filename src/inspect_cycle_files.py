from pathlib import Path
import csv
import re

ROOT = Path("data_raw/samsung_health")

cycle_file_patterns = [
    "cycle.flow",
    "cycle.profile",
    "cycle.prediction",
]

def is_relevant_cycle_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() == ".csv"
        and any(pattern in name for pattern in cycle_file_patterns)
    )

def read_lines(path: Path):
    encodings = ["utf-8-sig", "utf-8", "cp1250", "latin1"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                return f.readlines(), enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Nie udało się odczytać pliku: {path}")

def parse_csv_line(line: str):
    return next(csv.reader([line], delimiter=",", quotechar='"'))

def classify_value(value: str) -> str:
    v = value.strip()

    if v == "":
        return "empty"

    if re.fullmatch(r"-?\d+", v):
        if len(v) >= 12:
            return "timestamp_or_long_number"
        return "integer"

    if re.fullmatch(r"-?\d+\.\d+", v):
        return "float"

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return "date"

    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", v):
        return "date"

    if re.fullmatch(r"[0-9a-fA-F-]{16,}", v):
        return "uuid_like"

    if "." in v and re.search(r"[a-zA-Z]", v):
        return "package_or_text"

    if v.startswith("{") or v.startswith("["):
        return "json_like"

    return "text"

def expected_score(column: str, value: str) -> int:
    c = column.lower()
    kind = classify_value(value)
    score = 0

    if "time" in c:
        if kind in {"timestamp_or_long_number", "integer", "date"}:
            score += 2

    if "date" in c:
        if kind in {"timestamp_or_long_number", "integer", "date"}:
            score += 2

    if "uuid" in c:
        if kind in {"uuid_like", "text", "package_or_text"} and len(value.strip()) >= 8:
            score += 2

    if "pkg" in c or "package" in c:
        if kind == "package_or_text":
            score += 3

    if c in {
        "amount", "period", "cycle", "spotting", "source",
        "ovulation_status", "unrealistic_menstruation", "data_version"
    }:
        if kind in {"integer", "float", "empty"}:
            score += 2

    if c == "custom":
        score += 1

    return score

def score_mapping(header, row):
    return sum(expected_score(col, val) for col, val in zip(header, row))

def inspect_file(path: Path):
    print("\n" + "=" * 80)
    print("PLIK:", path)

    lines, encoding = read_lines(path)
    header = parse_csv_line(lines[1])
    rows = [
        parse_csv_line(line)
        for line in lines[2:]
        if line.strip()
    ]

    print("Kodowanie:", encoding)
    print("Kolumn w nagłówku:", len(header))
    print("Wierszy danych:", len(rows))

    if not rows:
        print("Brak wierszy danych.")
        return

    first_row = rows[0]

    print("Pól w pierwszym wierszu danych:", len(first_row))

    candidates = {}

    if len(first_row) == len(header) + 1:
        candidates["drop_first_extra_field"] = first_row[1:]
        candidates["drop_last_extra_field"] = first_row[:-1]
    elif len(first_row) == len(header):
        candidates["as_is"] = first_row
    else:
        print("Nietypowa różnica długości — trzeba będzie obsłużyć ręcznie.")
        return

    print("\nOcena możliwego wyrównania kolumn:")
    best_name = None
    best_score = -1

    for name, candidate_row in candidates.items():
        score = score_mapping(header, candidate_row)

        if score > best_score:
            best_score = score
            best_name = name

        print(f"\nKandydat: {name}")
        print("Score:", score)
        print("Typy danych po mapowaniu, bez wartości:")

        for col, val in zip(header, candidate_row):
            print(f" - {col}: {classify_value(val)}")

    print("\nNajbardziej prawdopodobne wyrównanie:", best_name)

files = sorted(
    p for p in ROOT.rglob("*")
    if p.is_file() and is_relevant_cycle_file(p)
)

print("Znalezione właściwe pliki cyklu:", len(files))

for file in files:
    inspect_file(file)