from pathlib import Path
import pandas as pd


DATA_PATH = Path("data_processed/daily_features.csv")
OUT_ROOT = Path("reports")
OUT_ROOT.mkdir(parents=True, exist_ok=True)


def format_float(value, digits=1):
    if pd.isna(value):
        return "brak"
    return f"{value:.{digits}f}"


def main():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Nie znaleziono pliku: {DATA_PATH}")

    df = pd.read_csv(DATA_PATH)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date")

    numeric_cols = [
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
        "bolus_units",
        "basal_units_estimated",
        "total_insulin_units",
        "carbs_g",
        "bolus_count",
        "carb_events_count",
        "cycle_day",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print("Raport: cykl vs glikemia")
    print("=" * 80)

    print("\nZakres danych:")
    print(" od:", df["date"].min().date())
    print(" do:", df["date"].max().date())
    print(" dni:", len(df))

    print("\nDostępność danych:")
    print(" dni z CGM:", int(df["avg_glucose"].notna().sum()))
    print(" dni z insuliną:", int(df["total_insulin_units"].notna().sum()))
    print(" dni z węglowodanami:", int(df["carbs_g"].notna().sum()))

    if "phase" in df.columns:
        print("\nLiczba dni według fazy cyklu:")
        print(df["phase"].fillna("brak").value_counts().to_string())

    print("\nOgólne średnie:")
    print(" średnia glukoza:", format_float(df["avg_glucose"].mean()), "mg/dL")
    print(" time in range:", format_float(df["time_in_range_pct"].mean()), "%")
    print(" time below range:", format_float(df["time_below_range_pct"].mean()), "%")
    print(" time above range:", format_float(df["time_above_range_pct"].mean()), "%")
    print(" insulina całkowita:", format_float(df["total_insulin_units"].mean()), "U/dzień")
    print(" bolus:", format_float(df["bolus_units"].mean()), "U/dzień")
    print(" baza:", format_float(df["basal_units_estimated"].mean()), "U/dzień")
    print(" węglowodany:", format_float(df["carbs_g"].mean()), "g/dzień")

    if "phase" in df.columns:
        phase_summary = (
            df.groupby("phase", dropna=False)
            .agg(
                days=("date", "count"),
                avg_glucose=("avg_glucose", "mean"),
                time_in_range_pct=("time_in_range_pct", "mean"),
                time_below_range_pct=("time_below_range_pct", "mean"),
                time_above_range_pct=("time_above_range_pct", "mean"),
                total_insulin_units=("total_insulin_units", "mean"),
                bolus_units=("bolus_units", "mean"),
                basal_units_estimated=("basal_units_estimated", "mean"),
                carbs_g=("carbs_g", "mean"),
                bolus_count=("bolus_count", "mean"),
            )
            .reset_index()
            .sort_values("phase")
        )

        out_csv = OUT_ROOT / "cycle_phase_summary.csv"
        phase_summary.to_csv(out_csv, index=False, encoding="utf-8-sig")

        print("\nŚrednie według fazy cyklu:")
        print(phase_summary.to_string(index=False))

        print("\nZapisano podsumowanie:")
        print(" ", out_csv)

    # Dni potencjalnie nietypowe — tylko heurystyka, nie diagnoza.
    avg = df["avg_glucose"].mean()
    std = df["avg_glucose"].std()

    if not pd.isna(avg) and not pd.isna(std) and std > 0:
        df["avg_glucose_zscore"] = (df["avg_glucose"] - avg) / std

        unusual = df[
            df["avg_glucose_zscore"].abs() >= 1.0
        ].copy()

        unusual_out = OUT_ROOT / "unusual_glucose_days.csv"
        unusual.to_csv(unusual_out, index=False, encoding="utf-8-sig")

        print("\nDni z glikemią wyraźnie różną od średniej osobistej w tym eksporcie:")
        if unusual.empty:
            print(" brak")
        else:
            cols = [
                "date",
                "phase",
                "cycle_day",
                "avg_glucose",
                "time_in_range_pct",
                "time_above_range_pct",
                "total_insulin_units",
                "carbs_g",
                "avg_glucose_zscore",
            ]
            cols = [c for c in cols if c in unusual.columns]
            print(unusual[cols].to_string(index=False))

        print("\nZapisano dni nietypowe:")
        print(" ", unusual_out)

    print("\nInterpretacja:")
    print("- To jest analiza opisowa, nie rekomendacja zmiany dawek insuliny.")
    print("- 22 dni to za mało, żeby wiarygodnie ocenić wpływ cyklu.")
    print("- Ten raport służy głównie do sprawdzenia, czy import i łączenie danych działają poprawnie.")


if __name__ == "__main__":
    main()