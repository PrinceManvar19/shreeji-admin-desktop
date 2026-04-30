def test_fetch_vehicles_api(client):
    response = client.get("/api/vehicles/CUST9001")
    data = response.get_json()

    assert response.status_code == 200
    assert data["vehicles"][0]["plate_number"] == "GJ05QA9001"


def test_add_vehicle_api(client, customer_login):
    customer_login()

    response = client.post(
        "/api/vehicles/add",
        json={"plate_number": "GJ05QA9010", "brand": "Yamaha", "model": "RayZR"},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["success"] is True
    assert data["vehicle"]["plate_number"] == "GJ05QA9010"


def test_duplicate_vehicle_owned_by_another_customer_is_rejected(client, customer_login):
    customer_login()

    response = client.post(
        "/api/vehicles/add",
        json={"plate_number": "GJ05QA9002", "brand": "TVS", "model": "Jupiter"},
    )
    data = response.get_json()

    assert response.status_code == 400
    assert data["success"] is False
    assert "already linked" in data["message"]
