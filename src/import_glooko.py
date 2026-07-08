from pathlib import Path
import pandas as pd
from history_store import merge_history
import os

RAW_ROOT = Path(
    os.environ.get("GLOOKO_RAW_ROOT", "data_raw/glooko")
).resolve()
OUT_ROOT = Path("data_processed")
CLEAN_ROOT = OUT_ROOT / "glooko_clean"

OUT_ROOT.mkdir(parents=True, exist_ok=True)
CLEAN_ROOT.mkdir(parents=True, exist_ok=True)


FILES = {
    "bg": "bg_data",
    "cgm": "cgm_data",
    "cgm_carbs": "cgm_carbs_data",
    "basal": "basal_data",
    "bolus": "bolus_data",
    "insulin_summary": "insulin_data",
    "food": "food_data",
    "manual_insulin": "manual_insulin_data",
}

def find_file(pattern: str) -> Path | None:
    pattern = pattern.lower()

    matches = [
        path
        for path in RAW_ROOT.rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() == ".csv"
            and path.stem.lower().startswith(pattern)
        )
    ]

    if not matches:
        return None

    return max(matches, key=lambda path: path.stat().st_mtime)

def read_glooko_csv(path: Path) -> pd.DataFrame:
    """
    Format eksportu Glooko:
    - linia 1: metadane, np. imię i zakres dat
    - linia 2: właściwy nagłówek
    - linia 3+: dane
    """
    try:
        df = pd.read_csv(
            path,
            skiprows=1,
            sep=",",
            encoding="utf-8-sig",
            dtype=str,
        )
    except UnicodeDecodeError:
        df = pd.read_csv(
            path,
            skiprows=1,
            sep=",",
            encoding="latin1",
            dtype=str,
        )

    # Usuwamy całkowicie puste wiersze.
    df = df.dropna(how="all")

    # Usuwamy puste kolumny, jeśli Glooko je doda.
    df = df.dropna(axis=1, how="all")

    return df


def load_all_glooko_files() -> dict[str, pd.DataFrame]:
    tables = {}

    for logical_name, pattern in FILES.items():
        path = find_file(pattern)

        if path is None:
            print(f"Nie znaleziono pliku: {pattern}")
            tables[logical_name] = pd.DataFrame()
            continue

        df = read_glooko_csv(path)
        tables[logical_name] = df

        out_path = CLEAN_ROOT / f"{logical_name}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")

        print(f"Oczyszczono {logical_name}:")
        print(f"  źródło: {path}")
        print(f"  wiersze: {len(df)}")
        print(f"  kolumny: {list(df.columns)}")
        print(f"  zapisano: {out_path}")

    return tables


def parse_datetime(value):
    if pd.isna(value):
        return pd.NaT

    v = str(value).strip()

    if v == "":
        return pd.NaT

    # Glooko PL: 31.05.2026 20:47
    parsed = pd.to_datetime(v, format="%d.%m.%Y %H:%M", errors="coerce")

    if not pd.isna(parsed):
        return parsed

    # Awaryjnie inne formaty.
    return pd.to_datetime(v, errors="coerce", dayfirst=True)


def parse_number(value):
    """
    Obsługuje polski przecinek dziesiętny:
    0,3 → 0.3
    """
    if pd.isna(value):
        return pd.NA

    v = str(value).strip()

    if v == "":
        return pd.NA

    v = v.replace(" ", "")
    v = v.replace(",", ".")

    return pd.to_numeric(v, errors="coerce")


def normalize_cgm(cgm_df: pd.DataFrame) -> pd.DataFrame:
    if cgm_df.empty:
        return pd.DataFrame(columns=[
            "timestamp",
            "date",
            "glucose_mg_dl",
            "source",
            "serial_number",
        ])

    df = cgm_df.copy()

    df["timestamp"] = df["Znacznik czasu"].apply(parse_datetime)
    df["glucose_mg_dl"] = df["Wartość glukozy CGM (mg/dl)"].apply(parse_number)
    df["source"] = "cgm"
    df["serial_number"] = df.get("Numer seryjny", "")

    df = df.dropna(subset=["timestamp", "glucose_mg_dl"])
    df["date"] = df["timestamp"].dt.date

    return df[[
        "timestamp",
        "date",
        "glucose_mg_dl",
        "source",
        "serial_number",
    ]]


def normalize_bg(bg_df: pd.DataFrame) -> pd.DataFrame:
    if bg_df.empty:
        return pd.DataFrame(columns=[
            "timestamp",
            "date",
            "glucose_mg_dl",
            "source",
            "serial_number",
        ])

    required = ["Znacznik czasu", "Wartość glukozy (mg/dl)"]

    if not all(col in bg_df.columns for col in required):
        return pd.DataFrame(columns=[
            "timestamp",
            "date",
            "glucose_mg_dl",
            "source",
            "serial_number",
        ])

    df = bg_df.copy()

    df["timestamp"] = df["Znacznik czasu"].apply(parse_datetime)
    df["glucose_mg_dl"] = df["Wartość glukozy (mg/dl)"].apply(parse_number)
    df["source"] = "manual_bg"
    df["serial_number"] = df.get("Numer seryjny", "")

    df = df.dropna(subset=["timestamp", "glucose_mg_dl"])
    df["date"] = df["timestamp"].dt.date

    return df[[
        "timestamp",
        "date",
        "glucose_mg_dl",
        "source",
        "serial_number",
    ]]


def normalize_bolus(bolus_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    insulin_columns = [
        "timestamp",
        "date",
        "event_type",
        "insulin_kind",
        "units",
        "entered_glucose_mg_dl",
        "carbs_g",
        "serial_number",
    ]

    carb_columns = [
        "timestamp",
        "date",
        "carbs_g",
        "source",
        "serial_number",
    ]

    if bolus_df.empty:
        return pd.DataFrame(columns=insulin_columns), pd.DataFrame(columns=carb_columns)

    df = bolus_df.copy()

    df["timestamp"] = df["Znacznik czasu"].apply(parse_datetime)
    df["date"] = df["timestamp"].dt.date

    df["units"] = df["Podana insulina (U)"].apply(parse_number)
    df["carbs_g"] = df["Spożyte węglowodany (g)"].apply(parse_number)
    df["entered_glucose_mg_dl"] = df["Wprowadzony poziom glukozy we krwi (mg/dl)"].apply(parse_number)

    df["event_type"] = "bolus"
    df["insulin_kind"] = df.get("Rodzaj insuliny", "")
    df["serial_number"] = df.get("Numer seryjny", "")

    insulin_events = df.dropna(subset=["timestamp", "units"]).copy()
    insulin_events = insulin_events[insulin_events["units"].fillna(0) > 0]

    insulin_events = insulin_events[insulin_columns]

    carb_events = df.dropna(subset=["timestamp", "carbs_g"]).copy()
    carb_events = carb_events[carb_events["carbs_g"].fillna(0) > 0]
    carb_events["source"] = "bolus_carbs"
    carb_events = carb_events[carb_columns]

    return insulin_events, carb_events


def normalize_basal(basal_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "timestamp",
        "date",
        "event_type",
        "insulin_kind",
        "duration_min",
        "rate_u_per_h",
        "units_estimated",
        "serial_number",
    ]

    if basal_df.empty:
        return pd.DataFrame(columns=columns)

    df = basal_df.copy()

    df["timestamp"] = df["Znacznik czasu"].apply(parse_datetime)
    df["date"] = df["timestamp"].dt.date
    df["duration_min"] = df["Czas trwania (min)"].apply(parse_number)
    df["rate_u_per_h"] = df["Prędkość"].apply(parse_number)

    # Jeśli kolumna "Podana insulina (U)" jest pusta, szacujemy z prędkości i czasu.
    if "Podana insulina (U)" in df.columns:
        df["units_reported"] = df["Podana insulina (U)"].apply(parse_number)
    else:
        df["units_reported"] = pd.NA

    df["units_estimated"] = df["units_reported"]

    missing_units = df["units_estimated"].isna()
    df.loc[missing_units, "units_estimated"] = (
        df.loc[missing_units, "rate_u_per_h"].astype("float") *
        df.loc[missing_units, "duration_min"].astype("float") / 60.0
    )

    df["event_type"] = "basal"
    df["insulin_kind"] = df.get("Rodzaj insuliny", "")
    df["serial_number"] = df.get("Numer seryjny", "")

    df = df.dropna(subset=["timestamp"])
    df = df[columns]

    return df


def normalize_insulin_summary(insulin_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "timestamp",
        "date",
        "bolus_total_u",
        "insulin_total_u",
        "basal_total_u",
        "serial_number",
    ]

    if insulin_df.empty:
        return pd.DataFrame(columns=columns)

    df = insulin_df.copy()

    df["timestamp"] = df["Znacznik czasu"].apply(parse_datetime)
    df["date"] = df["timestamp"].dt.date

    df["bolus_total_u"] = df["Bolus łącznie (U)"].apply(parse_number)
    df["insulin_total_u"] = df["Insulina łącznie (U)"].apply(parse_number)
    df["basal_total_u"] = df["Podstawowa łącznie (U)"].apply(parse_number)
    df["serial_number"] = df.get("Numer seryjny", "")

    df = df.dropna(subset=["timestamp"])
    df = df[columns]

    return df

def restore_history_types(
    glucose_readings: pd.DataFrame,
    bolus_events: pd.DataFrame,
    basal_events: pd.DataFrame,
    insulin_summary: pd.DataFrame,
    carb_events: pd.DataFrame,
):
    """
    Przywraca typy dat i liczb po połączeniu danych
    z historią zapisaną w plikach CSV.
    """

    def restore_timestamp_and_date(
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        df = df.copy()

        if df.empty:
            return df

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(
                df["timestamp"],
                errors="coerce",
            )

            df = df.dropna(
                subset=["timestamp"]
            ).copy()

            df["date"] = df["timestamp"].dt.date

        elif "date" in df.columns:
            parsed_date = pd.to_datetime(
                df["date"],
                errors="coerce",
            )

            df["date"] = parsed_date.dt.date

        return df

    def restore_numeric_columns(
        df: pd.DataFrame,
        columns: list[str],
    ) -> pd.DataFrame:
        df = df.copy()

        for column in columns:
            if column not in df.columns:
                continue

            values = (
                df[column]
                .astype("string")
                .str.strip()
                .str.replace(",", ".", regex=False)
            )

            df[column] = pd.to_numeric(
                values,
                errors="coerce",
            )

        return df

    glucose_readings = restore_timestamp_and_date(
        glucose_readings
    )
    glucose_readings = restore_numeric_columns(
        glucose_readings,
        [
            "glucose_mg_dl",
        ],
    )

    bolus_events = restore_timestamp_and_date(
        bolus_events
    )
    bolus_events = restore_numeric_columns(
        bolus_events,
        [
            "units",
            "entered_glucose_mg_dl",
            "carbs_g",
        ],
    )

    basal_events = restore_timestamp_and_date(
        basal_events
    )
    basal_events = restore_numeric_columns(
        basal_events,
        [
            "duration_min",
            "rate_u_per_h",
            "units_estimated",
        ],
    )

    insulin_summary = restore_timestamp_and_date(
        insulin_summary
    )
    insulin_summary = restore_numeric_columns(
        insulin_summary,
        [
            "bolus_total_u",
            "insulin_total_u",
            "basal_total_u",
        ],
    )

    carb_events = restore_timestamp_and_date(
        carb_events
    )
    carb_events = restore_numeric_columns(
        carb_events,
        [
            "carbs_g",
        ],
    )

    return (
        glucose_readings,
        bolus_events,
        basal_events,
        insulin_summary,
        carb_events,
    )

def build_daily_glucose_features(
    glucose_readings: pd.DataFrame,
) -> pd.DataFrame:
    output_columns = [
        "date",
        "cgm_readings_count",
        "avg_glucose",
        "median_glucose",
        "min_glucose",
        "max_glucose",
        "glucose_std",
        "time_in_range_pct",
        "time_below_range_pct",
        "time_above_range_pct",
        "hypo_readings_count",
        "hyper_readings_count",
    ]

    if glucose_readings is None or glucose_readings.empty:
        return pd.DataFrame(columns=output_columns)

    if "source" not in glucose_readings.columns:
        print(
            "Brak kolumny 'source' w glucose_readings — "
            "nie można wybrać danych CGM."
        )
        return pd.DataFrame(columns=output_columns)

    cgm = glucose_readings[
        glucose_readings["source"].astype(str).str.lower() == "cgm"
    ].copy()

    if cgm.empty:
        print("Brak odczytów ze źródłem 'cgm'.")
        return pd.DataFrame(columns=output_columns)

    if "glucose_mg_dl" not in cgm.columns:
        print("Brak kolumny 'glucose_mg_dl'.")
        return pd.DataFrame(columns=output_columns)

    # Historia może zostać wczytana z CSV jako tekst.
    # Przed porównywaniem z progami 70 i 180 przywracamy typ liczbowy.
    cgm["glucose_mg_dl"] = pd.to_numeric(
        cgm["glucose_mg_dl"],
        errors="coerce",
    )

    # Przywracamy timestamp, jeżeli historia została wczytana jako tekst.
    if "timestamp" in cgm.columns:
        cgm["timestamp"] = pd.to_datetime(
            cgm["timestamp"],
            errors="coerce",
        )

    # Jeśli nie ma poprawnej kolumny date, tworzymy ją z timestamp.
    if "date" not in cgm.columns:
        if "timestamp" not in cgm.columns:
            print("Brak kolumn 'date' i 'timestamp'.")
            return pd.DataFrame(columns=output_columns)

        cgm["date"] = cgm["timestamp"].dt.date

    else:
        parsed_date = pd.to_datetime(
            cgm["date"],
            errors="coerce",
        )

        # Brakujące daty uzupełniamy na podstawie timestamp.
        if "timestamp" in cgm.columns:
            missing_date = parsed_date.isna()

            parsed_date.loc[missing_date] = (
                cgm.loc[missing_date, "timestamp"]
                .dt.normalize()
            )

        cgm["date"] = parsed_date.dt.date

    # Usuwamy rekordy, których nie da się wykorzystać w analizie.
    before_cleanup = len(cgm)

    cgm = cgm.dropna(
        subset=[
            "date",
            "glucose_mg_dl",
        ]
    ).copy()

    removed = before_cleanup - len(cgm)

    if removed > 0:
        print(
            f"Pominięto nieprawidłowych odczytów CGM: {removed}"
        )

    if cgm.empty:
        print("Po oczyszczeniu nie pozostały żadne odczyty CGM.")
        return pd.DataFrame(columns=output_columns)

    # Flagi zakresów glikemii.
    cgm["in_range"] = cgm["glucose_mg_dl"].between(
        70,
        180,
        inclusive="both",
    )

    cgm["below_range"] = cgm["glucose_mg_dl"] < 70
    cgm["above_range"] = cgm["glucose_mg_dl"] > 180

    daily = (
        cgm.groupby("date", as_index=False)
        .agg(
            cgm_readings_count=(
                "glucose_mg_dl",
                "count",
            ),
            avg_glucose=(
                "glucose_mg_dl",
                "mean",
            ),
            median_glucose=(
                "glucose_mg_dl",
                "median",
            ),
            min_glucose=(
                "glucose_mg_dl",
                "min",
            ),
            max_glucose=(
                "glucose_mg_dl",
                "max",
            ),
            glucose_std=(
                "glucose_mg_dl",
                "std",
            ),
            time_in_range_pct=(
                "in_range",
                "mean",
            ),
            time_below_range_pct=(
                "below_range",
                "mean",
            ),
            time_above_range_pct=(
                "above_range",
                "mean",
            ),
            hypo_readings_count=(
                "below_range",
                "sum",
            ),
            hyper_readings_count=(
                "above_range",
                "sum",
            ),
        )
    )

    percentage_columns = [
        "time_in_range_pct",
        "time_below_range_pct",
        "time_above_range_pct",
    ]

    for column in percentage_columns:
        daily[column] = (
            pd.to_numeric(
                daily[column],
                errors="coerce",
            )
            * 100.0
        )

    # Zaokrąglenie dotyczy jedynie wyników dziennych.
    decimal_columns = [
        "avg_glucose",
        "median_glucose",
        "min_glucose",
        "max_glucose",
        "glucose_std",
        "time_in_range_pct",
        "time_below_range_pct",
        "time_above_range_pct",
    ]

    for column in decimal_columns:
        daily[column] = pd.to_numeric(
            daily[column],
            errors="coerce",
        ).round(3)

    daily = daily.sort_values(
        "date",
        kind="stable",
    ).reset_index(drop=True)

    return daily[output_columns]


def build_daily_insulin_features(
    bolus_events: pd.DataFrame,
    basal_events: pd.DataFrame,
    insulin_summary: pd.DataFrame,
    carb_events: pd.DataFrame,
) -> pd.DataFrame:
    output_columns = [
        "date",
        "bolus_units",
        "basal_units_estimated",
        "total_insulin_units",
        "carbs_g",
        "bolus_count",
        "carb_events_count",
    ]

    dates = set()

    for df in [bolus_events, basal_events, insulin_summary, carb_events]:
        if not df.empty and "date" in df.columns:
            dates.update(df["date"].dropna().tolist())

    if not dates:
        return pd.DataFrame(columns=output_columns)

    daily = pd.DataFrame({"date": sorted(dates)})

    if not bolus_events.empty:
        bolus_daily = (
            bolus_events.groupby("date", as_index=False)
            .agg(
                bolus_units=("units", "sum"),
                bolus_count=("units", "count"),
            )
        )
        daily = daily.merge(bolus_daily, on="date", how="left")

    if not basal_events.empty:
        basal_daily = (
            basal_events.groupby("date", as_index=False)
            .agg(
                basal_units_estimated=("units_estimated", "sum"),
            )
        )
        daily = daily.merge(basal_daily, on="date", how="left")

    if not insulin_summary.empty:
        summary_daily = (
            insulin_summary.groupby("date", as_index=False)
            .agg(
                bolus_total_from_summary=("bolus_total_u", "sum"),
                basal_total_from_summary=("basal_total_u", "sum"),
                insulin_total_from_summary=("insulin_total_u", "sum"),
            )
        )
        daily = daily.merge(summary_daily, on="date", how="left")

    if not carb_events.empty:
        carbs_daily = (
            carb_events.groupby("date", as_index=False)
            .agg(
                carbs_g=("carbs_g", "sum"),
                carb_events_count=("carbs_g", "count"),
            )
        )
        daily = daily.merge(carbs_daily, on="date", how="left")

    numeric_cols = [
        "bolus_units",
        "basal_units_estimated",
        "bolus_total_from_summary",
        "basal_total_from_summary",
        "insulin_total_from_summary",
        "carbs_g",
        "bolus_count",
        "carb_events_count",
    ]

    for col in numeric_cols:
        if col not in daily.columns:
            daily[col] = 0.0

        daily[col] = pd.to_numeric(daily[col], errors="coerce").fillna(0.0)

    # Bezpieczniejsze liczenie bez przypisań daily.loc[...] = Series,
    # bo w nowszych wersjach Pandas potrafi to wywołać błąd dtype.
    reconstructed_total = daily["bolus_units"] + daily["basal_units_estimated"]

    daily["total_insulin_units"] = daily["insulin_total_from_summary"].where(
        daily["insulin_total_from_summary"] > 0,
        reconstructed_total,
    )

    daily["bolus_units"] = daily["bolus_units"].where(
        daily["bolus_units"] > 0,
        daily["bolus_total_from_summary"],
    )

    daily["basal_units_estimated"] = daily["basal_units_estimated"].where(
        daily["basal_units_estimated"] > 0,
        daily["basal_total_from_summary"],
    )

    for col in [
        "bolus_units",
        "basal_units_estimated",
        "total_insulin_units",
        "carbs_g",
        "bolus_count",
        "carb_events_count",
    ]:
        daily[col] = pd.to_numeric(daily[col], errors="coerce").fillna(0.0)

    return daily[output_columns]

def merge_daily_features(
    daily_glucose: pd.DataFrame,
    daily_insulin: pd.DataFrame,
) -> pd.DataFrame:
    dates = set()

    if not daily_glucose.empty:
        dates.update(daily_glucose["date"].tolist())

    if not daily_insulin.empty:
        dates.update(daily_insulin["date"].tolist())

    if not dates:
        return pd.DataFrame()

    daily = pd.DataFrame({"date": sorted(dates)})

    daily = daily.merge(daily_glucose, on="date", how="left")
    daily = daily.merge(daily_insulin, on="date", how="left")

    return daily


def merge_with_cycle(daily_glooko: pd.DataFrame) -> pd.DataFrame:
    cycle_path = OUT_ROOT / "cycle_daily.csv"

    if not cycle_path.exists():
        print("Nie znaleziono cycle_daily.csv — pomijam łączenie z cyklem.")
        return daily_glooko

    cycle = pd.read_csv(cycle_path)

    cycle["date"] = pd.to_datetime(cycle["date"], errors="coerce").dt.date

    merged = daily_glooko.merge(cycle, on="date", how="left")

    return merged


def save_outputs(
    glucose_readings,
    bolus_events,
    basal_events,
    insulin_summary,
    carb_events,
    daily_glucose,
    daily_insulin,
    daily_glooko,
    daily_features,
):
    outputs = {
        "glucose_readings.csv": glucose_readings,
        "bolus_events.csv": bolus_events,
        "basal_events.csv": basal_events,
        "insulin_summary.csv": insulin_summary,
        "carb_events.csv": carb_events,
        "daily_glucose_features.csv": daily_glucose,
        "daily_insulin_features.csv": daily_insulin,
        "daily_glooko_features.csv": daily_glooko,
        "daily_features.csv": daily_features,
    }

    for filename, df in outputs.items():
        path = OUT_ROOT / filename
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"Zapisano: {path} ({len(df)} wierszy)")


def main():
    print("Import Glooko")
    print("=" * 80)
    print("GLOOKO_RAW_ROOT:", RAW_ROOT)
    print("Katalog istnieje:", RAW_ROOT.exists())

    csv_files = [
        path
        for path in RAW_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() == ".csv"
    ]

    print("CSV widoczne dla importera:", len(csv_files))

    for path in csv_files[:20]:
        print(" -", path.relative_to(RAW_ROOT))
    tables = load_all_glooko_files()

    cgm_readings = normalize_cgm(tables["cgm"])
    bg_readings = normalize_bg(tables["bg"])

    glucose_readings = pd.concat(
        [cgm_readings, bg_readings],
        ignore_index=True,
    ).sort_values("timestamp")

    bolus_events, carb_events_from_bolus = normalize_bolus(tables["bolus"])
    basal_events = normalize_basal(tables["basal"])
    insulin_summary = normalize_insulin_summary(tables["insulin_summary"])

    # Na razie główne węglowodany bierzemy z bolus_data,
    # bo food_data wygląda na puste.
    carb_events = carb_events_from_bolus.copy()

    glucose_readings = merge_history(
        new_df=glucose_readings,
        filename="glucose_readings.csv",
        key_columns=[
            "timestamp",
            "glucose_mg_dl",
            "source",
            "serial_number",
        ],
        sort_columns=["timestamp"],
    )

    bolus_events = merge_history(
        new_df=bolus_events,
        filename="bolus_events.csv",
        key_columns=[
            "timestamp",
            "units",
            "entered_glucose_mg_dl",
            "carbs_g",
            "insulin_kind",
            "serial_number",
        ],
        sort_columns=["timestamp"],
    )

    basal_events = merge_history(
        new_df=basal_events,
        filename="basal_events.csv",
        key_columns=[
            "timestamp",
            "duration_min",
            "rate_u_per_h",
            "units_estimated",
            "insulin_kind",
            "serial_number",
        ],
        sort_columns=["timestamp"],
    )

    insulin_summary = merge_history(
        new_df=insulin_summary,
        filename="insulin_summary.csv",
        key_columns=[
            "date",
            "serial_number",
        ],
        sort_columns=["timestamp"],
    )

    carb_events = merge_history(
        new_df=carb_events,
        filename="carb_events.csv",
        key_columns=[
            "timestamp",
            "carbs_g",
            "source",
            "serial_number",
        ],
        sort_columns=["timestamp"],
    )

    (
        glucose_readings,
        bolus_events,
        basal_events,
        insulin_summary,
        carb_events,
    ) = restore_history_types(
        glucose_readings=glucose_readings,
        bolus_events=bolus_events,
        basal_events=basal_events,
        insulin_summary=insulin_summary,
        carb_events=carb_events,
    )

    daily_glucose = build_daily_glucose_features(glucose_readings)
    daily_insulin = build_daily_insulin_features(
        bolus_events=bolus_events,
        basal_events=basal_events,
        insulin_summary=insulin_summary,
        carb_events=carb_events,
    )

    daily_glooko = merge_daily_features(daily_glucose, daily_insulin)
    daily_features = merge_with_cycle(daily_glooko)

    save_outputs(
        glucose_readings=glucose_readings,
        bolus_events=bolus_events,
        basal_events=basal_events,
        insulin_summary=insulin_summary,
        carb_events=carb_events,
        daily_glucose=daily_glucose,
        daily_insulin=daily_insulin,
        daily_glooko=daily_glooko,
        daily_features=daily_features,
    )

    print("\nPodsumowanie:")
    print("  odczyty glukozy:", len(glucose_readings))
    print("  zdarzenia bolusów:", len(bolus_events))
    print("  zdarzenia bazalu:", len(basal_events))
    print("  zdarzenia węglowodanów:", len(carb_events))
    print("  dni z CGM:", len(daily_glucose))
    print("  dni z insuliną/węglowodanami:", len(daily_insulin))
    print("  dni połączone Glooko + cykl:", len(daily_features))

    if not daily_features.empty:
        print(
            "  zakres daily_features:",
            daily_features["date"].min(),
            "→",
            daily_features["date"].max(),
        )

    print("\nGotowe.")


if __name__ == "__main__":
    main()