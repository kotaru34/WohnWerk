from __future__ import annotations

from email.message import EmailMessage

from fastapi.testclient import TestClient

from app.admin import require_admin, require_csrf
from app.main import app


def sample_mail() -> bytes:
    message = EmailMessage()
    message["From"] = "mail@immowelt.de"
    message["To"] = "private@example.invalid"
    message["Subject"] = "Ihr Suchauftrag"
    message.set_content("Neue Immobilien gefunden")
    message.add_alternative(
        '<a href="https://www.immowelt.de/expose/12345678-1234-1234-1234-123456789abc">'
        "Kleines Haus &amp; Garten</a>"
        '<a href="https://attacker.invalid/bait">Unautorisierte externe URL</a>',
        subtype="html",
    )
    return message.as_bytes()


def test_admin_only_offline_email_preview_hides_mail_headers_and_external_urls() -> None:
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/immowelt-alerts")
            assert page.status_code == 200
            assert 'enctype="multipart/form-data"' in page.text

            response = client.post(
                "/admin/immowelt-alerts",
                files=[("emails", ("search.eml", sample_mail(), "message/rfc822"))],
            )
            assert response.status_code == 200
            assert "1 direkte Exposé-Links" in response.text
            assert "Kleines Haus &amp; Garten" in response.text
            assert "https://www.immowelt.de/expose/12345678-1234-1234-1234-123456789abc" in response.text
            assert "attacker.invalid" not in response.text
            assert "private@example.invalid" not in response.text
            assert response.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


def test_email_preview_rejects_large_or_non_eml_uploads() -> None:
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            for filename, content in (
                ("unknown.txt", sample_mail()),
                ("big.eml", b"x" * (2 * 1024 * 1024 + 5)),
            ):
                response = client.post(
                    "/admin/immowelt-alerts",
                    files=[("emails", (filename, content, "application/octet-stream"))],
                )
                assert response.status_code == 200
                assert "role=\"alert\"" in response.text
                assert "direkte Exposé-Links" not in response.text
    finally:
        app.dependency_overrides.clear()
