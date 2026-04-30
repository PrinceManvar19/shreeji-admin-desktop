def test_create_booking(client, customer_login, booking_payload):
    customer_login()

    response = client.post(
        "/book",
        data=booking_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["booking_id"].startswith("BOOK")
    assert data["status"] == "pending"


def test_duplicate_booking_prevention(client, customer_login, booking_payload):
    customer_login()
    client.post(
        "/book",
        data=booking_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    response = client.post(
        "/book",
        data=booking_payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    data = response.get_json()

    assert response.status_code == 400
    assert data["success"] is False
    assert "Booking already exists" in data["message"]


def test_booking_missing_fields_validation(client, customer_login, booking_payload):
    customer_login()
    payload = booking_payload.copy()
    payload["vehicle_number"] = ""

    response = client.post(
        "/book",
        data=payload,
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    data = response.get_json()

    assert response.status_code == 400
    assert data["success"] is False
    assert "Vehicle number is required" in data["message"]
