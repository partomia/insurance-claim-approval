from dependencies import get_password_hash
from models.customer import Customer


def test_get_and_update_me(client, db_session):
    customer = Customer(
        email="profile@test.com",
        full_name="Original Name",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    login = client.post("/auth/verify-otp", json={"email": "profile@test.com", "otp": "112233"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "profile@test.com"
    assert me.json()["full_name"] == "Original Name"

    updated = client.patch("/auth/me", headers=headers, json={"full_name": "Updated Name"})
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Updated Name"

    me_again = client.get("/auth/me", headers=headers)
    assert me_again.json()["full_name"] == "Updated Name"
