from pathlib import Path
import csv
from collections import Counter

ROOT = Path("data_raw/glooko")

interesting_file_patterns = [
    "bg_data",
    "cgm_data",
    "cgm_carbs_data",
    "basal_data",
    "bolus_data",
    "insulin_data",
    "food_data",
    "manual_insulin_data",
]

header_keywords = [
    # English
    "date", "time", "timestamp", "device", "type", "value",
    "glucose", "cgm", "blood", "bg",
    "insulin", "bolus", "basal", "dose", "units",
    "carb", "carbs", "food", "meal",
    "event", "source",

    # Polish
    "data", "czas", "godzina", "urządzenie", "typ", "wartość",
    "glukoza", "cukier", "insulina", "bolus", "baza", "bazal",
    "dawka", "jednostki", "węglowodany", "weglowodany",
    "posiłek", "posilek", "jedzenie", "zdarzenie", "źródło", "zrodlo",
]

metadata_keywords = [
    "imię", "imie", "nazwisko", "zakres dat", "date range", "name"
]

def is_interesting_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        path.suffix.lower() in [".csv", ".txt"]
        and any(pattern in name for pattern in interesting_file_patterns)
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

def parse_line(line: str, delimiter: str):
    return next(csv.reader([line], delimiter=delimiter, quotechar='"'))

def detect_delimiter(lines):
    delimiters = [",", ";", "\t"]
    scores = {}

    for delimiter in delimiters:
        counts = []
        for line in lines[:30]:
            if not line.strip():
                continue
            try:
                cells = parse_line(line, delimiter)
                counts.append(len(cells))
            except Exception:
                pass

        if counts:
            scores[delimiter] = max(counts)
        else:
            scores[delimiter] = 0

    return max(scores, key=scores.get)

def looks_like_metadata(cells):
    joined = " ".join(str(c).lower() for c in cells)
    return any(k in joined for k in metadata_keywords)

def header_score(cells):
    joined = " ".join(str(c).lower() for c in cells)

    score = 0

    for keyword in header_keywords:
        if keyword in joined:
            score += 1

    # Nagłówek danych zwykle ma więcej niż 2 kolumny.
    if len(cells) >= 3:
        score += 2

    if len(cells) >= 5:
        score += 2

    # Metadane typu "Imię i nazwisko" nie są właściwym nagłówkiem danych.
    if looks_like_metadata(cells):
        score -= 5

    return score

def inspect_file(path: Path):
    print("\n" + "=" * 100)
    print("PLIK:", path)

    lines, encoding = read_lines(path)
    delimiter = detect_delimiter(lines)

    print("Kodowanie:", encoding)
    print("Separator:", repr(delimiter))
    print("Liczba surowych linii:", len(lines))

    field_counts = Counter()

    for line in lines:
        if not line.strip():
            continue
        try:
            cells = parse_line(line, delimiter)
            field_counts[len(cells)] += 1
        except Exception:
            field_counts["parse_error"] += 1

    print("Rozkład liczby pól w liniach:")
    for fields_count, count in field_counts.items():
        print(f" - {fields_count} pól: {count} linii")

    candidates = []

    for idx, line in enumerate(lines):
        if not line.strip():
            continue

        try:
            cells = parse_line(line, delimiter)
        except Exception:
            continue

        score = header_score(cells)

        if score >= 3:
            candidates.append((score, idx, cells))

    candidates = sorted(candidates, reverse=True, key=lambda x: x[0])

    if not candidates:
        print("\nNie znaleziono oczywistego nagłówka.")
        print("Diagnostyka pierwszych 15 niepustych linii, bez wartości:")
        shown = 0

        for idx, line in enumerate(lines):
            if not line.strip():
                continue

            try:
                cells = parse_line(line, delimiter)
                print(f" - linia {idx + 1}: {len(cells)} pól")
                shown += 1
            except Exception:
                print(f" - linia {idx + 1}: błąd parsowania")
                shown += 1

            if shown >= 15:
                break

        return

    print("\nNajlepsi kandydaci na prawdziwy nagłówek:")

    for score, idx, cells in candidates[:3]:
        print("\nKandydat:")
        print("  linia:", idx + 1)
        print("  score:", score)
        print("  liczba kolumn:", len(cells))
        print("  kolumny:")
        for col in cells:
            print("   -", col)

files = sorted(
    p for p in ROOT.rglob("*")
    if p.is_file() and is_interesting_file(p)
)

print("Znalezione interesujące pliki Glooko:", len(files))

for file in files:
    inspect_file(file)