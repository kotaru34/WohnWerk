from app.database import SessionLocal
from app.postal_codes import fetch_rtr_postal_codes, upsert_postal_codes


def main() -> None:
    records = fetch_rtr_postal_codes()

    with SessionLocal() as session:
        imported = upsert_postal_codes(session, records)

    print(f"Imported {imported} addressable Austrian postal codes from RTR.")


if __name__ == "__main__":
    main()
