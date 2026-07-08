from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INBOX_DIRS = [
    PROJECT_ROOT / "data_raw" / "glooko",
    PROJECT_ROOT / "data_raw" / "samsung_health",
    Path.home() / "Downloads" / "Phone Link",
]

ARCHIVE_ROOT = PROJECT_ROOT / "data_archive" / "processed_zips"
MANIFEST_PATH = PROJECT_ROOT / "data_processed" / "zip_manifest.json"

# Dostępne tryby:
# archive – przenieś przetworzony ZIP do archiwum
# delete  – usuń ZIP po udanym imporcie
# keep    – pozostaw ZIP w folderze wejściowym
RETENTION_MODE = os.getenv("ZIP_RETENTION_MODE", "archive").lower()

IMPORTERS = {
    "samsung_health": PROJECT_ROOT / "src" / "import_samsung_cycle.py",
    "glooko": PROJECT_ROOT / "src" / "import_glooko.py",
}


def ensure_directories() -> None:
    (PROJECT_ROOT / "data_inbox").mkdir(parents=True, exist_ok=True)
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"processed": {}}

    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed": {}}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def classify_zip(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                info.filename.lower()
                for info in archive.infolist()
                if not info.is_dir()
            ]
    except zipfile.BadZipFile:
        return None

    joined = "\n".join(names)

    glooko_markers = [
        "cgm_data",
        "bg_data",
        "bolus_data",
        "basal_data",
        "insulin_data",
    ]

    samsung_markers = [
        "com.samsung.health.cycle",
        "com.samsung.shealth.cycle",
        "samsunghealth",
    ]

    if any(marker in joined for marker in glooko_markers):
        return "glooko"

    if any(marker in joined for marker in samsung_markers):
        return "samsung_health"

    return None


def safe_extract(archive_path: Path, destination: Path) -> None:
    """
    Bezpieczne rozpakowanie ZIP-a, chroniące przed ścieżkami
    wychodzącymi poza folder tymczasowy.
    """
    destination = destination.resolve()

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = (destination / member.filename).resolve()

            try:
                member_path.relative_to(destination)
            except ValueError as exc:
                raise RuntimeError(
                    f"Niebezpieczna ścieżka w ZIP: {member.filename}"
                ) from exc

        archive.extractall(destination)


def run_importer(source_type: str, extracted_root: Path) -> None:
    importer = IMPORTERS[source_type]

    environment = os.environ.copy()

    if source_type == "glooko":
        environment["GLOOKO_RAW_ROOT"] = str(extracted_root.resolve())

    elif source_type == "samsung_health":
        environment["SAMSUNG_RAW_ROOT"] = str(extracted_root.resolve())

    print("Uruchamiam importer:", importer)
    print("Tymczasowy katalog danych:", extracted_root.resolve())

    subprocess.run(
        [sys.executable, str(importer)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )

def archive_or_delete_zip(path: Path, source_type: str, digest: str) -> str:
    if RETENTION_MODE == "keep":
        return str(path)

    if RETENTION_MODE == "delete":
        path.unlink()
        return "deleted"

    if RETENTION_MODE != "archive":
        raise ValueError(
            f"Nieznany ZIP_RETENTION_MODE: {RETENTION_MODE}"
        )

    target_dir = ARCHIVE_ROOT / source_type
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / path.name

    if target.exists():
        target = target_dir / f"{path.stem}_{digest[:8]}{path.suffix}"

    shutil.move(str(path), str(target))
    return str(target)


def find_zip_candidates() -> list[Path]:
    candidates: list[Path] = []

    for directory in INBOX_DIRS:
        if not directory.exists():
            continue

        candidates.extend(
            path
            for path in directory.rglob("*.zip")
            if path.is_file()
        )

    return list(dict.fromkeys(candidates))


def rebuild_daily_features() -> None:
    """
    Odświeża połączenie gotowych danych Glooko z aktualną tabelą cyklu.
    Jest potrzebne także wtedy, gdy pojawił się tylko nowy ZIP Samsunga.
    """
    glooko_path = (
        PROJECT_ROOT / "data_processed" / "daily_glooko_features.csv"
    )
    cycle_path = PROJECT_ROOT / "data_processed" / "cycle_daily.csv"
    output_path = PROJECT_ROOT / "data_processed" / "daily_features.csv"

    if not glooko_path.exists() or not cycle_path.exists():
        print("Pomijam przebudowanie daily_features – brakuje danych.")
        return

    glooko = pd.read_csv(glooko_path)
    cycle = pd.read_csv(cycle_path)

    glooko["date"] = pd.to_datetime(
        glooko["date"], errors="coerce"
    ).dt.date

    cycle["date"] = pd.to_datetime(
        cycle["date"], errors="coerce"
    ).dt.date

    merged = glooko.merge(
        cycle,
        on="date",
        how="left",
        validate="one_to_one",
    )

    merged.to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        f"Przebudowano {output_path}: "
        f"{len(merged)} dni."
    )


def process_zip(
    path: Path,
    source_type: str,
    digest: str,
    manifest: dict,
) -> bool:
    print("\n" + "=" * 80)
    print("Przetwarzam:", path)
    print("Typ:", source_type)
    print("Hash:", digest[:12])

    try:
        with TemporaryDirectory(prefix="agent_cukierek_") as temp_dir:
            extracted_root = Path(temp_dir)

            safe_extract(path, extracted_root)
            csv_files = [
                file
                for file in extracted_root.rglob("*")
                if file.is_file() and file.suffix.lower() == ".csv"
            ]

            print("CSV znalezione po rozpakowaniu:", len(csv_files))

            for file in csv_files[:20]:
                print(" -", file.relative_to(extracted_root))

            if not csv_files:
                raise RuntimeError(
                    "Po rozpakowaniu nie znaleziono plików CSV."
                )
            run_importer(source_type, extracted_root)

        final_location = archive_or_delete_zip(
            path=path,
            source_type=source_type,
            digest=digest,
        )

        manifest["processed"][digest] = {
            "original_path": str(path),
            "source_type": source_type,
            "status": "success",
            "final_location": final_location,
        }

        save_manifest(manifest)

        print("Import zakończony powodzeniem.")
        print("ZIP:", final_location)
        return True

    except Exception as exc:
        manifest["processed"][digest] = {
            "original_path": str(path),
            "source_type": source_type,
            "status": "failed",
            "error": str(exc),
        }

        save_manifest(manifest)

        print("BŁĄD importu:", exc)
        print("ZIP nie został usunięty ani przeniesiony.")
        return False


def main() -> None:
    ensure_directories()
    manifest = load_manifest()

    candidates = find_zip_candidates()

    print("Procesor eksportów ZIP")
    print("=" * 80)
    print("Tryb przechowywania ZIP:", RETENTION_MODE)
    print("Znaleziono ZIP-ów:", len(candidates))

    pending: dict[str, list[tuple[Path, str]]] = {
        "samsung_health": [],
        "glooko": [],
    }

    for path in candidates:
        digest = sha256_file(path)
        previous = manifest["processed"].get(digest)

        if previous and previous.get("status") == "success":
            print("Pomijam wcześniej przetworzony ZIP:", path)
            continue

        source_type = classify_zip(path)

        if source_type is None:
            print("Nie rozpoznano typu ZIP:", path)
            continue

        pending[source_type].append((path, digest))

    # Najpierw Samsung, później Glooko.
    # Dzięki temu Glooko połączy się z najnowszą tabelą cyklu.
    success_count = 0

    for source_type in ["samsung_health", "glooko"]:
        items = sorted(
            pending[source_type],
            key=lambda item: item[0].stat().st_mtime,
        )

        for path, digest in items:
            if process_zip(
                path=path,
                source_type=source_type,
                digest=digest,
                manifest=manifest,
            ):
                success_count += 1

    if success_count > 0:
        rebuild_daily_features()
    else:
        print(
            "Brak udanych importów — "
            "nie przebudowuję daily_features.csv."
        )

    print("\n" + "=" * 80)
    print("Nowe poprawnie przetworzone ZIP-y:", success_count)
    print("Manifest:", MANIFEST_PATH)


if __name__ == "__main__":
    main()