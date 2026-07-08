from pathlib import Path
import pandas as pd


HISTORY_ROOT = Path("data_history")
HISTORY_ROOT.mkdir(parents=True, exist_ok=True)


def merge_history(
    new_df: pd.DataFrame,
    filename: str,
    key_columns: list[str],
    sort_columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Łączy nową porcję danych z trwałą historią i usuwa duplikaty.

    key_columns określają tożsamość zdarzenia, np.:
    timestamp + wartość + urządzenie.
    """
    path = HISTORY_ROOT / filename

    frames = []

    if path.exists():
        existing = pd.read_csv(path, dtype=str)
        frames.append(existing)

    if new_df is not None and not new_df.empty:
        frames.append(new_df.copy())

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True, sort=False)

    for column in key_columns:
        if column not in combined.columns:
            combined[column] = pd.NA

    # Tworzymy pomocniczy, znormalizowany klucz.
    key_frame = combined[key_columns].copy()

    for column in key_columns:
        values = key_frame[column]

        if column in {"timestamp", "date", "start_time", "update_time", "create_time"}:
            parsed = pd.to_datetime(values, errors="coerce", dayfirst=True)

            key_frame[column] = parsed.dt.strftime(
                "%Y-%m-%d %H:%M:%S"
            ).fillna(values.astype("string").fillna(""))
        else:
            key_frame[column] = (
                values.astype("string")
                .fillna("")
                .str.strip()
                .str.replace(",", ".", regex=False)
            )

    combined["_record_key"] = key_frame.astype(str).agg(
        "¦".join,
        axis=1,
    )

    before = len(combined)

    # keep="last" pozwala zachować nowszą wersję rekordu,
    # jeżeli eksport zawiera poprawioną kopię.
    combined = combined.drop_duplicates(
        subset=["_record_key"],
        keep="last",
    )

    removed = before - len(combined)
    combined = combined.drop(columns=["_record_key"])

    if sort_columns:
        existing_sort_columns = [
            column
            for column in sort_columns
            if column in combined.columns
        ]

        temporary_sort_columns = []

        for index, column in enumerate(existing_sort_columns):
            temporary_column = f"_sort_key_{index}"
            column_name = column.lower()

            if (
                "timestamp" in column_name
                or "date" in column_name
                or "time" in column_name
            ):
                combined[temporary_column] = pd.to_datetime(
                    combined[column],
                    errors="coerce",
                )
            else:
                numeric_values = pd.to_numeric(
                    combined[column],
                    errors="coerce",
                )

                if numeric_values.notna().any():
                    combined[temporary_column] = numeric_values
                else:
                    combined[temporary_column] = (
                        combined[column]
                        .astype("string")
                        .fillna("")
                    )

            temporary_sort_columns.append(temporary_column)

        if temporary_sort_columns:
            combined = combined.sort_values(
                temporary_sort_columns,
                kind="stable",
                na_position="last",
            )

            combined = combined.drop(
                columns=temporary_sort_columns,
            )

    combined.to_csv(path, index=False, encoding="utf-8-sig")

    print(
        f"Historia {filename}: "
        f"{len(combined)} rekordów, "
        f"usunięto duplikatów w tym przebiegu: {removed}"
    )

    return combined