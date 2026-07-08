from pathlib import Path
import pandas as pd
import numpy as np


DATA_ROOT = Path("data_processed")
REPORTS_ROOT = Path("reports")

DAILY_PATH = DATA_ROOT / "daily_features.csv"
BOLUS_PATH = DATA_ROOT / "bolus_events.csv"

OUT_DAILY = DATA_ROOT / "sensitivity_daily.csv"
OUT_PHASE = REPORTS_ROOT / "sensitivity_by_phase.csv"

REPORTS_ROOT.mkdir(parents=True, exist_ok=True)


def to_numeric(df, cols):
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def robust_z(series: pd.Series) -> pd.Series:
    """
    Prosty z-score, ale odporny na puste/stałe kolumny.
    Dla braków zwraca 0, czyli neutralny wpływ.
    """
    s = pd.to_numeric(series, errors="coerce")
    mean = s.mean()
    std = s.std()

    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=s.index)

    z = (s - mean) / std
    return z.fillna(0.0)


def classify_bolus_events(bolus: pd.DataFrame) -> pd.DataFrame:
    if bolus.empty:
        return pd.DataFrame(columns=[
            "date",
            "correction_like_count",
            "correction_like_units",
            "meal_bolus_count",
            "meal_bolus_units",
            "mixed_bolus_count",
            "mixed_bolus_units",
        ])

    df = bolus.copy()

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["date"] = df["timestamp"].dt.date

    numeric_cols = [
        "units",
        "entered_glucose_mg_dl",
        "carbs_g",
    ]
    df = to_numeric(df, numeric_cols)

    df["units"] = df["units"].fillna(0.0)
    df["carbs_g"] = df["carbs_g"].fillna(0.0)
    df["entered_glucose_mg_dl"] = df["entered_glucose_mg_dl"].fillna(0.0)

    df = df[df["units"] > 0].copy()

    # Uproszczona klasyfikacja:
    # - carbs == 0 i units > 0: bolus korekcyjny lub korekcyjno-algorytmiczny
    # - carbs > 0 i entered_glucose > 0: mieszany, posiłek + korekta
    # - carbs > 0: posiłkowy
    df["correction_like"] = (df["carbs_g"] <= 0) & (df["units"] > 0)
    df["mixed_bolus"] = (df["carbs_g"] > 0) & (df["entered_glucose_mg_dl"] > 0)
    df["meal_bolus"] = (df["carbs_g"] > 0) & (df["units"] > 0)

    daily = (
        df.groupby("date", as_index=False)
        .agg(
            correction_like_count=("correction_like", "sum"),
            correction_like_units=(
                "units",
                lambda x: x[df.loc[x.index, "correction_like"]].sum()
            ),
            meal_bolus_count=("meal_bolus", "sum"),
            meal_bolus_units=(
                "units",
                lambda x: x[df.loc[x.index, "meal_bolus"]].sum()
            ),
            mixed_bolus_count=("mixed_bolus", "sum"),
            mixed_bolus_units=(
                "units",
                lambda x: x[df.loc[x.index, "mixed_bolus"]].sum()
            ),
        )
    )

    return daily


def add_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pewność dotyczy jakości wskaźnika, nie pewności medycznej.
    Przy krótkiej historii limitujemy confidence.
    """
    result = df.copy()

    result["confidence"] = 0.0

    if "cgm_readings_count" in result.columns:
        result.loc[result["cgm_readings_count"] >= 200, "confidence"] += 0.35
        result.loc[
            (result["cgm_readings_count"] >= 100) & (result["cgm_readings_count"] < 200),
            "confidence"
        ] += 0.20

    if "total_insulin_units" in result.columns:
        result.loc[result["total_insulin_units"].notna(), "confidence"] += 0.20

    if "bolus_units" in result.columns:
        result.loc[result["bolus_units"].notna(), "confidence"] += 0.15

    if "carbs_g" in result.columns:
        result.loc[result["carbs_g"].notna(), "confidence"] += 0.10

    if "correction_like_count" in result.columns:
        result.loc[result["correction_like_count"].notna(), "confidence"] += 0.10

    if "phase" in result.columns:
        result.loc[result["phase"].notna(), "confidence"] += 0.10

    # Przy 22 dniach danych nie chcemy udawać wysokiej pewności.
    history_days = len(result)
    if history_days < 45:
        max_confidence = 0.55
    elif history_days < 90:
        max_confidence = 0.70
    else:
        max_confidence = 0.90

    result["confidence"] = result["confidence"].clip(0, max_confidence)

    return result


def build_index(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()

    numeric_cols = [
        "avg_glucose",
        "time_in_range_pct",
        "time_below_range_pct",
        "time_above_range_pct",
        "hypo_readings_count",
        "hyper_readings_count",
        "bolus_units",
        "basal_units_estimated",
        "total_insulin_units",
        "carbs_g",
        "bolus_count",
        "carb_events_count",
        "correction_like_count",
        "correction_like_units",
        "meal_bolus_count",
        "meal_bolus_units",
        "mixed_bolus_count",
        "mixed_bolus_units",
    ]

    result = to_numeric(result, numeric_cols)

    for col in [
        "correction_like_count",
        "correction_like_units",
        "meal_bolus_count",
        "meal_bolus_units",
        "mixed_bolus_count",
        "mixed_bolus_units",
    ]:
        if col not in result.columns:
            result[col] = 0.0
        result[col] = result[col].fillna(0.0)

    # Wskaźnik ilości bolusa na 10 g węglowodanów.
    # Liczymy tylko dla dni, gdzie wpisano sensowną ilość węgli.
    result["bolus_u_per_10g_carbs"] = np.where(
        result["carbs_g"] >= 10,
        result["bolus_units"] / (result["carbs_g"] / 10.0),
        np.nan,
    )

    # Neutralizujemy skrajne wartości z bardzo małych ilości węgli.
    result["bolus_u_per_10g_carbs"] = pd.to_numeric(
        result["bolus_u_per_10g_carbs"],
        errors="coerce",
    ).clip(lower=0, upper=5)

    # Składniki "niższej wrażliwości":
    # - wyższa średnia glukoza
    # - więcej czasu powyżej zakresu
    # - więcej korekt / bolusów bez węgli
    # - większy bolus na 10 g węgli
    #
    # Składnik "wyższej wrażliwości":
    # - więcej czasu poniżej zakresu obniża resistance_score,
    #   czyli zwiększa sensitivity_index.
    z_avg_glucose = robust_z(result["avg_glucose"])
    z_above = robust_z(result["time_above_range_pct"])
    z_correction_units = robust_z(result["correction_like_units"])
    z_correction_count = robust_z(result["correction_like_count"])
    z_bolus_per_carbs = robust_z(result["bolus_u_per_10g_carbs"])
    z_below = robust_z(result["time_below_range_pct"])

    result["resistance_proxy_score"] = (
        0.35 * z_avg_glucose
        + 0.25 * z_above
        + 0.15 * z_correction_units
        + 0.10 * z_correction_count
        + 0.15 * z_bolus_per_carbs
        - 0.15 * z_below
    )

    result["sensitivity_index"] = (-result["resistance_proxy_score"]).clip(-2, 2)

    def label(value):
        if pd.isna(value):
            return "brak danych"
        if value <= -0.75:
            return "prawdopodobnie niższa"
        if value >= 0.75:
            return "prawdopodobnie wyższa"
        return "typowa / niejednoznaczna"

    result["sensitivity_label"] = result["sensitivity_index"].apply(label)

    # Flagi pomocnicze do wyjaśnień.
    result["flag_high_glucose"] = z_avg_glucose >= 1.0
    result["flag_high_above_range"] = z_above >= 1.0
    result["flag_many_corrections"] = z_correction_count >= 1.0
    result["flag_high_correction_units"] = z_correction_units >= 1.0
    result["flag_more_hypo"] = z_below >= 1.0

    result = add_confidence(result)

    return result


def explain_day(row) -> str:
    reasons = []

    if row.get("flag_high_glucose", False):
        reasons.append("wyższa średnia glukoza")

    if row.get("flag_high_above_range", False):
        reasons.append("więcej czasu powyżej zakresu")

    if row.get("flag_many_corrections", False):
        reasons.append("więcej bolusów korekcyjnych/podobnych")

    if row.get("flag_high_correction_units", False):
        reasons.append("więcej jednostek w bolusach korekcyjnych/podobnych")

    if row.get("flag_more_hypo", False):
        reasons.append("więcej czasu poniżej zakresu")

    if not reasons:
        return "brak silnego pojedynczego czynnika"

    return "; ".join(reasons)


def main():
    if not DAILY_PATH.exists():
        raise FileNotFoundError(f"Nie znaleziono: {DAILY_PATH}")

    daily = pd.read_csv(DAILY_PATH)
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.date

    if BOLUS_PATH.exists():
        bolus = pd.read_csv(BOLUS_PATH)
        bolus_daily = classify_bolus_events(bolus)
    else:
        bolus_daily = pd.DataFrame(columns=[
            "date",
            "correction_like_count",
            "correction_like_units",
            "meal_bolus_count",
            "meal_bolus_units",
            "mixed_bolus_count",
            "mixed_bolus_units",
        ])

    if not bolus_daily.empty:
        daily = daily.merge(bolus_daily, on="date", how="left")

    result = build_index(daily)

    result["explanation_short"] = result.apply(explain_day, axis=1)

    output_cols = [
        "date",
        "phase",
        "phase_source",
        "cycle_data_type",
        "cycle_day",
        "cycle_day_source",
        "avg_glucose",
        "time_in_range_pct",
        "time_below_range_pct",
        "time_above_range_pct",
        "total_insulin_units",
        "bolus_units",
        "basal_units_estimated",
        "carbs_g",
        "correction_like_count",
        "correction_like_units",
        "bolus_u_per_10g_carbs",
        "sensitivity_index",
        "sensitivity_label",
        "confidence",
        "explanation_short",
    ]

    output_cols = [c for c in output_cols if c in result.columns]

    result[output_cols].to_csv(OUT_DAILY, index=False, encoding="utf-8-sig")

    if "phase" in result.columns:
        phase_summary = (
            result.groupby("phase", dropna=False)
            .agg(
                days=("date", "count"),
                avg_sensitivity_index=("sensitivity_index", "mean"),
                avg_confidence=("confidence", "mean"),
                avg_glucose=("avg_glucose", "mean"),
                avg_time_above_range_pct=("time_above_range_pct", "mean"),
                avg_total_insulin_units=("total_insulin_units", "mean"),
                avg_correction_like_count=("correction_like_count", "mean"),
                lower_sensitivity_days=(
                    "sensitivity_label",
                    lambda x: (x == "prawdopodobnie niższa").sum()
                ),
                higher_sensitivity_days=(
                    "sensitivity_label",
                    lambda x: (x == "prawdopodobnie wyższa").sum()
                ),
            )
            .reset_index()
            .sort_values("phase")
        )

        phase_summary.to_csv(OUT_PHASE, index=False, encoding="utf-8-sig")

    print("Zbudowano pierwszy indeks insulinowrażliwości")
    print("=" * 80)
    print(f"Zapisano: {OUT_DAILY}")
    print(f"Liczba dni: {len(result)}")
    print(f"Zakres: {min(result['date'])} → {max(result['date'])}")

    print("\nRozkład etykiet:")
    print(result["sensitivity_label"].value_counts().to_string())

    print("\nDni z prawdopodobnie niższą wrażliwością:")
    lower = result[result["sensitivity_label"] == "prawdopodobnie niższa"].copy()

    if lower.empty:
        print(" brak")
    else:
        cols = [
            "date",
            "phase",
            "cycle_day",
            "avg_glucose",
            "time_above_range_pct",
            "total_insulin_units",
            "carbs_g",
            "correction_like_count",
            "sensitivity_index",
            "confidence",
            "explanation_short",
        ]
        cols = [c for c in cols if c in lower.columns]
        print(lower[cols].to_string(index=False))

    if "phase" in result.columns:
        print("\nPodsumowanie według fazy cyklu:")
        print(phase_summary.to_string(index=False))
        print(f"\nZapisano: {OUT_PHASE}")

    print("\nUwaga:")
    print("- To jest względny wskaźnik opisowy, nie medyczna rekomendacja.")
    print("- Nie używamy go do wyliczania dawek insuliny.")
    print("- Przy 22 dniach danych traktujemy wynik jako test techniczny i hipotezę do obserwacji.")


if __name__ == "__main__":
    main()