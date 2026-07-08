from pathlib import Path
import csv
from datetime import date, timedelta
import pandas as pd
from history_store import merge_history
import os

RAW_ROOT = Path(
    os.environ.get(
        "SAMSUNG_RAW_ROOT",
        "data_raw/samsung_health",
    )
).resolve()
OUT_ROOT = Path("data_processed")
CLEAN_ROOT = OUT_ROOT / "samsung_cycle_clean"

CLEAN_ROOT.mkdir(parents=True, exist_ok=True)


CYCLE_PATTERNS = {
    "flow": "cycle.flow",
    "profile": "cycle.profile",
    "prediction": "cycle.prediction",
}

def find_file(pattern: str) -> Path | None:
    pattern = pattern.lower()

    matches = [
        path
        for path in RAW_ROOT.rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() == ".csv"
            and pattern in path.name.lower()
        )
    ]

    if not matches:
        return None

    return max(matches, key=lambda path: path.stat().st_mtime)

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


def read_samsung_csv(path: Path) -> pd.DataFrame:
    lines, encoding = read_lines(path)

    if len(lines) < 2:
        raise ValueError(f"Plik ma za mało linii: {path}")

    header = parse_csv_line(lines[1])
    rows = []

    for line in lines[2:]:
        if not line.strip():
            continue

        cells = parse_csv_line(line)

        # W Twoim eksporcie każdy wiersz ma jedno dodatkowe pole na końcu.
        if len(cells) == len(header) + 1:
            cells = cells[:-1]

        if len(cells) > len(header):
            cells = cells[:len(header)]

        if len(cells) < len(header):
            cells = cells + [""] * (len(header) - len(cells))

        rows.append(cells)

    return pd.DataFrame(rows, columns=header)


def clean_all_files() -> dict[str, pd.DataFrame]:
    result = {}

    for logical_name, pattern in CYCLE_PATTERNS.items():
        path = find_file(pattern)

        if path is None:
            print(f"Nie znaleziono pliku: {pattern}")
            result[logical_name] = pd.DataFrame()
            continue

        df = read_samsung_csv(path)
        result[logical_name] = df

        out_path = CLEAN_ROOT / f"{logical_name}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")

        print(f"Oczyszczono {logical_name}:")
        print(f"  źródło: {path}")
        print(f"  wiersze: {len(df)}")
        print(f"  kolumny: {list(df.columns)}")
        print(f"  zapisano: {out_path}")

    return result


def parse_date_value(value):
    if pd.isna(value):
        return pd.NaT

    v = str(value).strip()

    if v == "":
        return pd.NaT

    if v.lstrip("-").isdigit():
        n = int(v)

        if abs(n) > 10_000_000_000:
            return pd.to_datetime(n, unit="ms", errors="coerce")

        if abs(n) > 1_000_000_000:
            return pd.to_datetime(n, unit="s", errors="coerce")

    return pd.to_datetime(v, errors="coerce", dayfirst=True)


def normalize_date_only(value):
    if pd.isna(value):
        return None

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.date()


def parse_number(value):
    if pd.isna(value):
        return pd.NA

    v = str(value).strip()

    if v == "":
        return pd.NA

    v = v.replace(" ", "").replace(",", ".")
    return pd.to_numeric(v, errors="coerce")


def get_profile_values(profile_df: pd.DataFrame):
    default_cycle_length = 28
    default_period_length = 5
    last_start_date = pd.NaT

    if profile_df.empty:
        return default_cycle_length, default_period_length, last_start_date

    row = profile_df.iloc[0]

    cycle_length = parse_number(row.get("cycle"))
    period_length = parse_number(row.get("period"))
    last_start_raw = row.get("last_start_date")

    if pd.isna(cycle_length):
        cycle_length = default_cycle_length

    if pd.isna(period_length):
        period_length = default_period_length

    last_start_date = parse_date_value(last_start_raw)

    return int(cycle_length), int(period_length), last_start_date


def date_range(start: date, end: date):
    current = start

    while current <= end:
        yield current
        current += timedelta(days=1)


def build_flow_daily(flow_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "period_actual",
        "spotting_actual",
        "flow_amount",
    ]

    if flow_df.empty:
        return pd.DataFrame(columns=columns)

    df = flow_df.copy()

    df["date"] = df["start_time"].apply(parse_date_value).dt.date
    df["flow_amount"] = df.get("amount").apply(parse_number)
    df["spotting_value"] = df.get("spotting").apply(parse_number)

    df = df.dropna(subset=["date"])

    if df.empty:
        return pd.DataFrame(columns=columns)

    df["period_actual"] = df["flow_amount"].fillna(0) > 0
    df["spotting_actual"] = df["spotting_value"].fillna(0) > 0

    daily = (
        df.groupby("date", as_index=False)
        .agg(
            period_actual=("period_actual", "max"),
            spotting_actual=("spotting_actual", "max"),
            flow_amount=("flow_amount", "max"),
        )
    )

    return daily[columns]


def safe_int(value, default):
    n = parse_number(value)

    if pd.isna(n):
        return default

    try:
        return int(n)
    except Exception:
        return default


def add_limited_range(rows, start_dt, end_dt, max_days, payload):
    """
    Dodaje zakres dat tylko jeśli długość jest realistyczna.
    Jeśli zakres jest podejrzanie długi, używa samego startu + max_days.
    """
    if pd.isna(start_dt):
        return

    start_d = start_dt.date()

    if pd.isna(end_dt):
        end_d = start_d + timedelta(days=max_days - 1)
    else:
        end_d = end_dt.date()

    duration = (end_d - start_d).days + 1

    if duration <= 0 or duration > max_days:
        end_d = start_d + timedelta(days=max_days - 1)

    for d in date_range(start_d, end_d):
        row = {"date": d}
        row.update(payload)
        rows.append(row)


def build_prediction_daily(
    prediction_df: pd.DataFrame,
    default_period_length: int = 5,
) -> pd.DataFrame:
    columns = [
        "date",
        "period_predicted",
        "predicted_period_start",
        "ovulation_predicted",
        "fertile_window_predicted",
    ]

    if prediction_df.empty:
        return pd.DataFrame(columns=columns)

    rows = []

    for _, row in prediction_df.iterrows():
        menstruation_start = parse_date_value(row.get("menstruation_start_date"))
        menstruation_end = parse_date_value(row.get("menstruation_end_date"))
        ovulation_date = parse_date_value(row.get("ovulation_date"))
        fertile_start = parse_date_value(row.get("fertile_window_start_date"))
        fertile_end = parse_date_value(row.get("fertile_window_end_date"))

        # Samsung ma kolumnę "period", która wygląda jak długość miesiączki.
        # Używamy jej zamiast ślepo ufać menstruation_end_date.
        period_length = safe_int(row.get("period"), default_period_length)
        period_length = max(1, min(period_length, 10))

        if not pd.isna(menstruation_start):
            start_d = menstruation_start.date()
            end_d = start_d + timedelta(days=period_length - 1)

            for d in date_range(start_d, end_d):
                rows.append({
                    "date": d,
                    "period_predicted": True,
                    "predicted_period_start": d == start_d,
                    "ovulation_predicted": False,
                    "fertile_window_predicted": False,
                })

        # Owulacja jako pojedynczy przewidywany dzień.
        if not pd.isna(ovulation_date):
            rows.append({
                "date": ovulation_date.date(),
                "period_predicted": False,
                "predicted_period_start": False,
                "ovulation_predicted": True,
                "fertile_window_predicted": False,
            })

        # Okno płodne: jeśli Samsung podaje sensowny zakres, używamy go,
        # ale tniemy do maksymalnie 6 dni. Jeśli zakres jest dziwny,
        # używamy owulacji jako kotwicy: -5 do dnia owulacji.
        if not pd.isna(fertile_start):
            add_limited_range(
                rows=rows,
                start_dt=fertile_start,
                end_dt=fertile_end,
                max_days=6,
                payload={
                    "period_predicted": False,
                    "predicted_period_start": False,
                    "ovulation_predicted": False,
                    "fertile_window_predicted": True,
                },
            )
        elif not pd.isna(ovulation_date):
            fallback_start = ovulation_date - pd.Timedelta(days=5)
            fallback_end = ovulation_date

            add_limited_range(
                rows=rows,
                start_dt=fallback_start,
                end_dt=fallback_end,
                max_days=6,
                payload={
                    "period_predicted": False,
                    "predicted_period_start": False,
                    "ovulation_predicted": False,
                    "fertile_window_predicted": True,
                },
            )

    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)

    daily = (
        df.groupby("date", as_index=False)
        .agg(
            period_predicted=("period_predicted", "max"),
            predicted_period_start=("predicted_period_start", "max"),
            ovulation_predicted=("ovulation_predicted", "max"),
            fertile_window_predicted=("fertile_window_predicted", "max"),
        )
    )

    return daily[columns]

def find_actual_period_starts(flow_daily: pd.DataFrame, last_start_date):
    starts = []

    if not flow_daily.empty and "period_actual" in flow_daily.columns:
        period_rows = flow_daily[flow_daily["period_actual"] == True].copy()

        if not period_rows.empty:
            period_dates = [
                normalize_date_only(d)
                for d in period_rows["date"].tolist()
            ]
            period_dates = sorted(d for d in period_dates if d is not None)

            previous_period_date = None

            for current_date in period_dates:
                if previous_period_date is None:
                    starts.append(current_date)
                else:
                    gap_days = (current_date - previous_period_date).days

                    if gap_days > 2:
                        starts.append(current_date)

                previous_period_date = current_date

    profile_start = normalize_date_only(last_start_date)

    if profile_start is not None:
        has_nearby_start = any(
            abs((profile_start - existing).days) <= 2
            for existing in starts
        )

        if not has_nearby_start:
            starts.append(profile_start)

    return sorted(set(starts))


def find_predicted_period_starts(prediction_daily: pd.DataFrame):
    if prediction_daily.empty or "predicted_period_start" not in prediction_daily.columns:
        return []

    rows = prediction_daily[prediction_daily["predicted_period_start"] == True]

    starts = [
        normalize_date_only(d)
        for d in rows["date"].tolist()
    ]

    return sorted(set(d for d in starts if d is not None))


def assign_cycle_day_and_source(
    d: date,
    actual_starts: list[date],
    predicted_starts: list[date],
):
    candidates = []

    for start in actual_starts:
        if start <= d:
            candidates.append((start, "actual_period_start"))

    for start in predicted_starts:
        if start <= d:
            candidates.append((start, "predicted_period_start"))

    if not candidates:
        return pd.NA, "unknown"

    selected_start, source = max(candidates, key=lambda x: x[0])
    return (d - selected_start).days + 1, source


def assign_phase_and_source(row, cycle_length: int):
    cycle_day = row.get("cycle_day")

    period_actual = bool(row.get("period_actual", False))
    period_predicted = bool(row.get("period_predicted", False))
    ovulation_predicted = bool(row.get("ovulation_predicted", False))
    fertile_window_predicted = bool(row.get("fertile_window_predicted", False))
    cycle_day_source = row.get("cycle_day_source", "unknown")

    if period_actual:
        return "menstruacyjna", "actual_period"

    if period_predicted and cycle_day_source == "predicted_period_start":
        return "menstruacyjna", "predicted_period"

    if ovulation_predicted:
        return "okołoowulacyjna", "predicted_ovulation"

    if fertile_window_predicted:
        return "okołoowulacyjna", "predicted_fertile_window"

    if pd.isna(cycle_day):
        return "unknown", "unknown"

    cycle_day = int(cycle_day)
    estimated_ovulation_day = max(1, cycle_length - 14)

    if abs(cycle_day - estimated_ovulation_day) <= 2:
        return "okołoowulacyjna", "heuristic_cycle_day"

    if cycle_day <= estimated_ovulation_day - 3:
        return "folikularna", "heuristic_cycle_day"

    return "lutealna", "heuristic_cycle_day"


def assign_cycle_data_type(row):
    if bool(row.get("period_actual", False)) or bool(row.get("spotting_actual", False)):
        return "actual_logged_event"

    if row.get("phase_source") in {
        "predicted_period",
        "predicted_ovulation",
        "predicted_fertile_window",
    }:
        return "samsung_prediction"

    if row.get("cycle_day_source") == "actual_period_start":
        return "inferred_from_actual_period"

    if row.get("cycle_day_source") == "predicted_period_start":
        return "inferred_from_samsung_prediction"

    return "unknown"


def build_cycle_daily(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    flow_df = tables.get("flow", pd.DataFrame())
    profile_df = tables.get("profile", pd.DataFrame())
    prediction_df = tables.get("prediction", pd.DataFrame())

    if not flow_df.empty:
        if "datauuid" in flow_df.columns:
            flow_df = merge_history(
                new_df=flow_df,
                filename="samsung_cycle_flow.csv",
                key_columns=["datauuid"],
                sort_columns=["start_time"],
            )
        else:
            flow_df = merge_history(
                new_df=flow_df,
                filename="samsung_cycle_flow.csv",
                key_columns=[
                    "start_time",
                    "amount",
                    "spotting",
                    "deviceuuid",
                ],
                sort_columns=["start_time"],
            )

    cycle_length, period_length, last_start_date = get_profile_values(profile_df)

    flow_daily = build_flow_daily(flow_df)
    prediction_daily = build_prediction_daily(prediction_df,default_period_length=period_length,)

    dates = set()

    if not flow_daily.empty:
        dates.update(flow_daily["date"].tolist())

    if not prediction_daily.empty:
        dates.update(prediction_daily["date"].tolist())

    if not pd.isna(last_start_date):
        dates.add(last_start_date.date())

    if not dates:
        raise RuntimeError("Nie udało się znaleźć żadnych dat cyklu.")

    start = min(dates) - timedelta(days=3)
    end = max(dates) + timedelta(days=3)

    base = pd.DataFrame({"date": list(date_range(start, end))})

    daily = base.merge(flow_daily, on="date", how="left")
    daily = daily.merge(prediction_daily, on="date", how="left")

    bool_cols = [
        "period_actual",
        "spotting_actual",
        "period_predicted",
        "predicted_period_start",
        "ovulation_predicted",
        "fertile_window_predicted",
    ]

    for col in bool_cols:
        if col not in daily.columns:
            daily[col] = False

        daily[col] = daily[col].fillna(False).astype(bool)

    if "flow_amount" not in daily.columns:
        daily["flow_amount"] = pd.NA

    actual_starts = find_actual_period_starts(flow_daily, last_start_date)
    predicted_starts = find_predicted_period_starts(prediction_daily)

    cycle_day_results = daily["date"].apply(
        lambda d: assign_cycle_day_and_source(
            d,
            actual_starts=actual_starts,
            predicted_starts=predicted_starts,
        )
    )

    daily["cycle_day"] = cycle_day_results.apply(lambda x: x[0])
    daily["cycle_day_source"] = cycle_day_results.apply(lambda x: x[1])

    phase_results = daily.apply(
        lambda row: assign_phase_and_source(row, cycle_length),
        axis=1,
    )

    daily["phase"] = phase_results.apply(lambda x: x[0])
    daily["phase_source"] = phase_results.apply(lambda x: x[1])

    daily["cycle_data_type"] = daily.apply(assign_cycle_data_type, axis=1)

    daily["cycle_length_from_profile"] = cycle_length
    daily["period_length_from_profile"] = period_length

    # Kolumny kompatybilności ze starymi raportami.
    daily["period"] = daily["period_actual"]
    daily["spotting"] = daily["spotting_actual"]
    daily["predicted_period"] = daily["period_predicted"]
    daily["predicted_ovulation"] = daily["ovulation_predicted"]
    daily["predicted_fertile_window"] = daily["fertile_window_predicted"]

    output_columns = [
        "date",
        "cycle_day",
        "cycle_day_source",
        "phase",
        "phase_source",
        "cycle_data_type",

        "period",
        "spotting",
        "predicted_period",
        "predicted_ovulation",
        "predicted_fertile_window",

        "period_actual",
        "spotting_actual",
        "period_predicted",
        "predicted_period_start",
        "ovulation_predicted",
        "fertile_window_predicted",

        "flow_amount",
        "cycle_length_from_profile",
        "period_length_from_profile",
    ]

    return daily[output_columns]


def main():
    print("Import Samsung Health cycle data — v2 actual vs predicted")
    print("=" * 80)
    print("SAMSUNG_RAW_ROOT:", RAW_ROOT)
    print("Katalog istnieje:", RAW_ROOT.exists())

    csv_files = [
        path
        for path in RAW_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() == ".csv"
    ]

    print("CSV widoczne dla importera:", len(csv_files))

    for path in csv_files[:20]:
        print(" -", path.relative_to(RAW_ROOT))

    tables = clean_all_files()

    cycle_daily = build_cycle_daily(tables)

    out_path = OUT_ROOT / "cycle_daily.csv"
    cycle_daily.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("\nZbudowano tabelę dzienną cyklu:")
    print(f"  zapisano: {out_path}")
    print(f"  liczba dni: {len(cycle_daily)}")
    print(f"  zakres: {cycle_daily['date'].min()} → {cycle_daily['date'].max()}")

    print("\nPodsumowanie actual vs predicted:")
    print("  dni z rzeczywistą miesiączką:", int(cycle_daily["period_actual"].sum()))
    print("  dni z rzeczywistym plamieniem:", int(cycle_daily["spotting_actual"].sum()))
    print("  dni z przewidywaną miesiączką:", int(cycle_daily["period_predicted"].sum()))
    print("  przewidywane początki miesiączki:", int(cycle_daily["predicted_period_start"].sum()))
    print("  dni z przewidywaną owulacją:", int(cycle_daily["ovulation_predicted"].sum()))
    print("  dni z przewidywanym oknem płodnym:", int(cycle_daily["fertile_window_predicted"].sum()))

    print("\nTyp danych cyklu:")
    print(cycle_daily["cycle_data_type"].value_counts().to_string())

    print("\nŹródło fazy:")
    print(cycle_daily["phase_source"].value_counts().to_string())

    print("\nGotowe.")


if __name__ == "__main__":
    main()