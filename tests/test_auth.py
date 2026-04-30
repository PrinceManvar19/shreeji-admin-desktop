def test_valid_customer_login_redirects_to_dashboard(client):
    response = client.post("/login", data={"identifier": "CUST9001"})

    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_invalid_login_shows_error_without_redirect(client):
    response = client.post("/login", data={"identifier": "UNKNOWN"}, follow_redirects=False)

    assert response.status_code == 200
    assert b"Invalid credentials" in response.data


def test_login_bad_input_does_not_crash(client):
    response = client.post("/login", data={"identifier": "' OR 1=1 --"})

    assert response.status_code == 200
    assert b"Invalid credentials" in response.data
