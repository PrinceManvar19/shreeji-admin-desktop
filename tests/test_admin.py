def test_admin_login_success_redirects_to_admin_dashboard(client):
    response = client.post("/login", data={"identifier": "ADMIN001"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/admin")


def test_admin_dashboard_access_after_login(client, admin_login):
    admin_login()

    response = client.get("/admin")

    assert response.status_code == 200
    assert b"Admin" in response.data or b"Dashboard" in response.data


def test_admin_dashboard_unauthorized_access_blocked(client):
    response = client.get("/admin")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
