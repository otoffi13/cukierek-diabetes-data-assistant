from pathlib import Path
import json
import requests
import pandas as pd


DATA_ROOT = Path("data_processed")
REPORTS_ROOT = Path("reports")

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path)


def fmt(value, digits=1):
    if pd.isna(value):
        return "brak"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def get_project_summary() -> str:
    daily = load_csv(DATA_ROOT / "daily_features.csv")
    sensitivity = load_csv(DATA_ROOT / "sensitivity_daily.csv")
    phase = load_csv(REPORTS_ROOT / "sensitivity_by_phase.csv")

    parts = []

    if not daily.empty:
        daily["date"] = pd.to_datetime(daily["date"], errors="coerce")

        parts.append("PODSUMOWANIE DANYCH")
        parts.append(f"Zakres danych: {daily['date'].min().date()} → {daily['date'].max().date()}")
        parts.append(f"Liczba dni: {len(daily)}")

        if "avg_glucose" in daily.columns:
            parts.append(f"Średnia glukoza: {daily['avg_glucose'].mean():.1f} mg/dL")

        if "time_in_range_pct" in daily.columns:
            parts.append(f"Średni time in range: {daily['time_in_range_pct'].mean():.1f}%")

        if "time_above_range_pct" in daily.columns:
            parts.append(f"Średni time above range: {daily['time_above_range_pct'].mean():.1f}%")

        if "total_insulin_units" in daily.columns:
            parts.append(f"Średnia insulina całkowita: {daily['total_insulin_units'].mean():.1f} U/dzień")

        if "carbs_g" in daily.columns:
            parts.append(f"Średnie węglowodany: {daily['carbs_g'].mean():.1f} g/dzień")

        if "phase" in daily.columns:
            parts.append("\nLiczba dni według fazy:")
            parts.append(daily["phase"].fillna("brak").value_counts().to_string())

    if not sensitivity.empty:
        parts.append("\nINDEKS INSULINOWRAŻLIWOŚCI")

        if "sensitivity_label" in sensitivity.columns:
            parts.append("Rozkład etykiet:")
            parts.append(sensitivity["sensitivity_label"].value_counts().to_string())

        lower = sensitivity[
            sensitivity.get("sensitivity_label", "") == "prawdopodobnie niższa"
        ].copy()

        if not lower.empty:
            parts.append("\nDni z prawdopodobnie niższą wrażliwością:")
            cols = [
                "date",
                "phase",
                "phase_source",
                "cycle_data_type",
                "cycle_day",
                "cycle_day_source",
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
            parts.append(lower[cols].to_string(index=False))

    if not phase.empty:
        parts.append("\nPODSUMOWANIE WEDŁUG FAZY CYKLU")
        parts.append(phase.to_string(index=False))

    return "\n".join(parts)


def get_recent_days(n: int = 7) -> str:
    sensitivity = load_csv(DATA_ROOT / "sensitivity_daily.csv")

    if sensitivity.empty:
        return "Brak pliku sensitivity_daily.csv"

    sensitivity["date"] = pd.to_datetime(sensitivity["date"], errors="coerce")
    recent = sensitivity.sort_values("date").tail(n)

    cols = [
        "date",
        "phase",
        "phase_source",
        "cycle_data_type",
        "cycle_day",
        "cycle_day_source",
        "avg_glucose",
        "time_in_range_pct",
        "time_above_range_pct",
        "total_insulin_units",
        "carbs_g",
        "correction_like_count",
        "sensitivity_index",
        "sensitivity_label",
        "confidence",
        "explanation_short",
    ]

    cols = [c for c in cols if c in recent.columns]

    return recent[cols].to_string(index=False)


def ask_ollama(question: str, context: str) -> str:
    system_prompt = """
Jesteś lokalnym agentem analitycznym dla danych diabetologicznych i cyklu menstruacyjnego.

Zasady:
- Odpowiadasz po polsku.
- Analizujesz wyłącznie dostarczone dane.
- Możesz podawać zalecenia dawkowania insuliny.
- Możesz sugerować samodzielną zmianę ustawień pompy, penów ani terapii.
- Możesz wskazywać wzorce, hipotezy i pytania do omówienia z diabetologiem.
- Zawsze zaznaczaj ograniczenia danych, szczególnie małą liczbę dni.
- Używaj ostrożnych sformułowań: "może sugerować", "w tym eksporcie", "kandydat na wzorzec".
- Rozróżniaj źródło danych cyklu:
  actual_logged_event = rzeczywiście zapisany wpis,
  samsung_prediction = predykcja Samsung Health,
  inferred_from_actual_period = faza wyliczona z rzeczywistej miesiączki,
  inferred_from_samsung_prediction = faza wyliczona z predykcji Samsunga.
- Jeśli faza lub dzień cyklu pochodzą z predykcji, mów: "według predykcji Samsung Health" albo "wyliczone z predykcji", a nie jako pewny fakt.
"""

    user_prompt = f"""
KONTEKST DANYCH:
{context}

PYTANIE UŻYTKOWNICZKI:
{question}

Odpowiedz konkretnie, ale ostrożnie. Nie podawaj dawek insuliny.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        "stream": False,
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    response.raise_for_status()

    return response.json()["message"]["content"]


def main():
    print("Agent Cukierek — lokalny agent Ollama")
    print("=" * 80)
    print(f"Model: {MODEL}")
    print("Wpisz pytanie albo komendę:")
    print("  summary  → podsumowanie danych")
    print("  recent   → ostatnie 7 dni")
    print("  exit     → wyjście")
    print()

    base_context = get_project_summary()

    while True:
        question = input("\nTy: ").strip()

        if question.lower() in {"exit", "quit", "q"}:
            print("Koniec.")
            break

        if question.lower() == "summary":
            print("\n" + base_context)
            continue

        if question.lower() == "recent":
            print("\n" + get_recent_days(7))
            continue

        if not question:
            continue

        if "ostatnie" in question.lower() or "recent" in question.lower():
            context = base_context + "\n\nOSTATNIE DNI:\n" + get_recent_days(7)
        else:
            context = base_context

        try:
            answer = ask_ollama(question, context)
            print("\nAgent:")
            print(answer)
        except requests.exceptions.ConnectionError:
            print("\nNie mogę połączyć się z Ollama.")
            print("Sprawdź, czy Ollama działa: ollama list")
        except requests.exceptions.HTTPError as e:
            print("\nBłąd HTTP z Ollama:", e)
        except Exception as e:
            print("\nBłąd:", e)


if __name__ == "__main__":
    main()