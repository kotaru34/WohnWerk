from app.database import SessionLocal
from app.postal_codes_de import fetch_geonames_de_postal_codes, upsert_german_postal_codes


def main() -> None:
    records = fetch_geonames_de_postal_codes()
    with SessionLocal() as session:
        updated = upsert_german_postal_codes(session, records)
    print(f"Imported {updated} German postal-code centroids from GeoNames")


if __name__ == "__main__":
    main()
