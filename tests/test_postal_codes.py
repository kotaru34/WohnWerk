from app.postal_codes import parse_rtr_postal_codes


def test_parse_rtr_postal_codes_keeps_only_addressable_rows() -> None:
    payload = {
        "data": [
            {"plz": 1010, "ort": "Wien", "adressierbar": "Ja"},
            {"plz": "4020", "ort": "Linz", "adressierbar": "Ja"},
            {"plz": 1005, "ort": "Postfach Wien", "adressierbar": "Nein"},
            {"plz": "bad", "ort": "Invalid", "adressierbar": "Ja"},
        ]
    }

    records = parse_rtr_postal_codes(payload)

    assert [(record.postal_code, record.name) for record in records] == [
        ("1010", "Wien"),
        ("4020", "Linz"),
    ]


def test_parse_rtr_postal_codes_deduplicates_by_code() -> None:
    payload = {
        "data": [
            {"plz": 8010, "ort": "Graz", "adressierbar": "Ja"},
            {"plz": 8010, "ort": "Graz", "adressierbar": "Ja"},
        ]
    }

    records = parse_rtr_postal_codes(payload)

    assert len(records) == 1
    assert records[0].postal_code == "8010"
