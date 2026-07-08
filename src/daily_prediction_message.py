from pathlib import Path
from datetime import date
import os
import requests
import pandas as pd
import smtplib
from email.message import EmailMessage


DATA_ROOT = Path("data_processed")
REPORTS_ROOT = Path("reports")
REPORTS_ROOT.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def safe_float(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def label_from_index(value):
    if value is None:
        return "brak danych"

    if value <= -0.75:
        return "prawdopodobnie niższa"
    if value >= 0.75:
        return "prawdopodobnie wyższa"

    return "typowa / niejednoznaczna"


def get_today_cycle_info(today: date):
    cycle = load_csv(DATA_ROOT / "cycle_daily.csv")

    if cycle.empty:
        return {}

    cycle["date"] = pd.to_datetime(cycle["date"], errors="coerce").dt.date
    row = cycle[cycle["date"] == today]

    if row.empty:
        return {}

    r = row.iloc[0].to_dict()

    return {
        "date": str(today),
        "cycle_day": r.get("cycle_day"),
        "cycle_day_source": r.get("cycle_day_source"),
        "phase": r.get("phase"),
        "phase_source": r.get("phase_source"),
        "cycle_data_type": r.get("cycle_data_type"),
        "period_actual": r.get("period_actual"),
        "period_predicted": r.get("period_predicted"),
        "ovulation_predicted": r.get("ovulation_predicted"),
        "fertile_window_predicted": r.get("fertile_window_predicted"),
    }


def build_forecast():
    today = date.today()

    sensitivity = load_csv(DATA_ROOT / "sensitivity_daily.csv")
    daily = load_csv(DATA_ROOT / "daily_features.csv")
    today_cycle = get_today_cycle_info(today)

    if sensitivity.empty:
        return {
            "today": str(today),
            "forecast_index": None,
            "forecast_label": "brak danych",
            "confidence": 0.0,
            "reason": "Brak pliku sensitivity_daily.csv.",
            "context": "",
        }

    sensitivity["date"] = pd.to_datetime(sensitivity["date"], errors="coerce").dt.date
    sensitivity = sensitivity.sort_values("date")

    numeric_cols = [
        "sensitivity_index",
        "avg_glucose",
        "time_above_range_pct",
        "time_in_range_pct",
        "total_insulin_units",
        "carbs_g",
        "correction_like_count",
        "cycle_day",
    ]

    for col in numeric_cols:
        if col in sensitivity.columns:
            sensitivity[col] = pd.to_numeric(sensitivity[col], errors="coerce")

    last_data_date = sensitivity["date"].max()
    staleness_days = (today - last_data_date).days

    recent = sensitivity.tail(3)
    recent_index = recent["sensitivity_index"].mean()

    components = []
    weights = []

    if not pd.isna(recent_index):
        components.append(float(recent_index))
        weights.append(0.45)

    today_phase = today_cycle.get("phase")
    phase_source = today_cycle.get("phase_source")
    cycle_data_type = today_cycle.get("cycle_data_type")

    phase_index = None
    phase_count = 0

    if today_phase and "phase" in sensitivity.columns:
        same_phase = sensitivity[sensitivity["phase"] == today_phase]
        phase_count = len(same_phase)

        if phase_count >= 2:
            phase_index = same_phase["sensitivity_index"].mean()
            if not pd.isna(phase_index):
                components.append(float(phase_index))
                weights.append(0.30)

    cycle_day_index = None
    cycle_day_count = 0

    today_cycle_day = safe_float(today_cycle.get("cycle_day"))

    if today_cycle_day is not None and "cycle_day" in sensitivity.columns:
        nearby = sensitivity[
            sensitivity["cycle_day"].between(today_cycle_day - 2, today_cycle_day + 2)
        ]
        cycle_day_count = len(nearby)

        if cycle_day_count >= 2:
            cycle_day_index = nearby["sensitivity_index"].mean()
            if not pd.isna(cycle_day_index):
                components.append(float(cycle_day_index))
                weights.append(0.25)

    if components:
        forecast_index = sum(c * w for c, w in zip(components, weights)) / sum(weights)
    else:
        forecast_index = None

    if forecast_index is not None:
        forecast_index = max(-2.0, min(2.0, forecast_index))

    label = label_from_index(forecast_index)

    history_days = len(sensitivity)

    confidence = 0.25

    if history_days >= 45:
        confidence += 0.15
    if history_days >= 90:
        confidence += 0.15

    if phase_count >= 2:
        confidence += 0.10

    if cycle_day_count >= 2:
        confidence += 0.10

    if staleness_days <= 1:
        confidence += 0.10
    elif staleness_days >= 3:
        confidence -= 0.15

    if cycle_data_type in {"samsung_prediction", "inferred_from_samsung_prediction"}:
        confidence -= 0.10

    if history_days < 45:
        confidence = min(confidence, 0.55)

    confidence = max(0.0, min(0.90, confidence))

    last_row = sensitivity.iloc[-1].to_dict()

    context = f"""
Dzisiaj: {today}

Ostatni dzień danych Glooko: {last_data_date}
Ile dni od ostatnich danych: {staleness_days}
Liczba dni historii: {history_days}

Dzisiejszy cykl:
- faza: {today_cycle.get("phase", "brak")}
- źródło fazy: {today_cycle.get("phase_source", "brak")}
- typ danych cyklu: {today_cycle.get("cycle_data_type", "brak")}
- dzień cyklu: {today_cycle.get("cycle_day", "brak")}
- źródło dnia cyklu: {today_cycle.get("cycle_day_source", "brak")}
- rzeczywista miesiączka: {today_cycle.get("period_actual", "brak")}
- przewidywana miesiączka: {today_cycle.get("period_predicted", "brak")}
- przewidywana owulacja: {today_cycle.get("ovulation_predicted", "brak")}
- przewidywane okno płodne: {today_cycle.get("fertile_window_predicted", "brak")}

Ostatni znany dzień:
- data: {last_row.get("date")}
- faza: {last_row.get("phase")}
- dzień cyklu: {last_row.get("cycle_day")}
- średnia glukoza: {last_row.get("avg_glucose")}
- time above range: {last_row.get("time_above_range_pct")}
- insulina całkowita: {last_row.get("total_insulin_units")}
- węglowodany: {last_row.get("carbs_g")}
- bolusy korekcyjne/podobne: {last_row.get("correction_like_count")}
- indeks insulinowrażliwości: {last_row.get("sensitivity_index")}
- etykieta: {last_row.get("sensitivity_label")}
- wyjaśnienie: {last_row.get("explanation_short")}

Predykcja robocza na dziś:
- forecast_index: {forecast_index}
- forecast_label: {label}
- confidence: {confidence}
- recent_index_3d: {recent_index}
- phase_index: {phase_index}
- phase_count: {phase_count}
- cycle_day_index: {cycle_day_index}
- cycle_day_count: {cycle_day_count}
"""

    return {
        "today": str(today),
        "last_data_date": str(last_data_date),
        "staleness_days": staleness_days,
        "forecast_index": forecast_index,
        "forecast_label": label,
        "confidence": confidence,
        "context": context.strip(),
    }


def ask_ollama_for_message(forecast: dict) -> str:
    system_prompt = """
Jesteś lokalnym agentem analitycznym dla osoby z cukrzycą.
Tworzysz krótką poranną wiadomość po polsku.

Zasady:
- Nie podawaj dawek insuliny.
- Nie sugeruj samodzielnych zmian terapii.
- Mów o ryzyku/wzorcu, nie o pewnej diagnozie.
- Jeżeli dane są stare, jasno to zaznacz.
- Jeśli faza cyklu pochodzi z predykcji Samsung Health, zaznacz to.
- Wiadomość ma być krótka, praktyczna i ostrożna.
- Maksymalnie 6 krótkich punktów.
"""

    user_prompt = f"""
Na podstawie poniższego kontekstu napisz poranną wiadomość.

KONTEKST:
{forecast["context"]}

Format:
Dzień dobry 🌤️
Predykcja insulinowrażliwości na dziś: ...
Pewność: ...
Dlaczego: ...
Uwaga: ...
"""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt.strip()},
        ],
        "stream": False,
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=120)
    response.raise_for_status()

    return response.json()["message"]["content"].strip()


def fallback_message(forecast: dict) -> str:
    return f"""Dzień dobry 🌤️

Predykcja insulinowrażliwości na dziś: {forecast["forecast_label"]}
Indeks roboczy: {forecast["forecast_index"]}
Pewność: {forecast["confidence"]:.2f}

Ostatnie dane Glooko: {forecast.get("last_data_date")}
Dni od ostatnich danych: {forecast.get("staleness_days")}

Uwaga: to jest analiza wzorców, nie rekomendacja zmiany dawek insuliny.
"""


def save_message(message: str, today: str):
    out_path = REPORTS_ROOT / f"daily_prediction_{today}.txt"
    out_path.write_text(message, encoding="utf-8")
    return out_path

def send_email_if_configured(message: str, today: str):
    email_from = os.getenv("AGENT_EMAIL_FROM")
    email_to = os.getenv("AGENT_EMAIL_TO")
    app_password = os.getenv("AGENT_EMAIL_APP_PASSWORD")

    if not email_from or not email_to or not app_password:
        return False

    subject = f"Agent Cukierek — predykcja insulinowrażliwości {today}"

    email = EmailMessage()
    email["From"] = email_from
    email["To"] = email_to
    email["Subject"] = subject
    email.set_content(message)

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(email_from, app_password)
        smtp.send_message(email)

    return True

def show_windows_notification_if_possible(message: str):
    try:
        from winotify import Notification

        toast = Notification(
            app_id="Agent Cukierek",
            title="Poranna predykcja insulinowrażliwości",
            msg=message[:250],
            duration="long",
        )
        toast.show()
        return True
    except Exception:
        return False


def main():
    forecast = build_forecast()

    try:
        message = ask_ollama_for_message(forecast)
    except Exception as e:
        message = fallback_message(forecast)
        message += f"\nOllama nie odpowiedziała, użyto wiadomości awaryjnej. Błąd: {e}"

    out_path = save_message(message, forecast["today"])

    email_sent = False
    notification_sent = False

    try:
        email_sent = send_email_if_configured(message, forecast["today"])
    except Exception as e:
        message += f"\n\nNie udało się wysłać e-maila: {e}"

    notification_sent = show_windows_notification_if_possible(message)

    print(message)
    print()
    print(f"Zapisano wiadomość: {out_path}")
    print(f"E-mail wysłany: {email_sent}")
    print(f"Powiadomienie Windows: {notification_sent}")

if __name__ == "__main__":
    main()