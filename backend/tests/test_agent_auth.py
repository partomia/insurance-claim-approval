from dependencies import get_password_hash
from models.policy_agent import PolicyAgent


def test_agent_signup_requires_invite_code(client, db_session):
    response = client.post(
        "/agent/auth/signup",
        json={
            "email": "bad-invite@cloudera.com",
            "full_name": "Bad Invite",
            "password": "password123",
            "invite_code": "WRONG",
        },
    )
    assert response.status_code == 403


def test_agent_signup_and_me(client, db_session):
    signup = client.post(
        "/agent/auth/signup",
        json={
            "email": "agent@test.com",
            "full_name": "Test Agent",
            "password": "password123",
            "invite_code": "CLOUDERA2026",
            "department": "Review",
        },
    )
    assert signup.status_code == 200
    assert signup.json()["email"] == "agent@test.com"

    tokens = client.post(
        "/agent/auth/verify-otp",
        json={"email": "agent@test.com", "otp": "112233"},
    )
    assert tokens.status_code == 200
    headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}

    me = client.get("/agent/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["full_name"] == "Test Agent"
    assert me.json()["department"] == "Review"


def test_agent_login_flow(client, db_session):
    agent = PolicyAgent(
        email="login-agent@test.com",
        full_name="Login Agent",
        hashed_password=get_password_hash("pass123"),
    )
    db_session.add(agent)
    db_session.commit()

    login = client.post(
        "/agent/auth/login",
        json={"email": "login-agent@test.com", "password": "pass123"},
    )
    assert login.status_code == 200

    tokens = client.post(
        "/agent/auth/verify-otp",
        json={"email": "login-agent@test.com", "otp": "112233"},
    )
    assert tokens.status_code == 200
    assert "access_token" in tokens.json()


def test_customer_token_rejected_on_agent_routes(client, db_session):
    from models.customer import Customer

    customer = Customer(
        email="cust-agent-block@test.com",
        full_name="Customer",
        hashed_password=get_password_hash("pass"),
    )
    db_session.add(customer)
    db_session.commit()

    login = client.post(
        "/auth/verify-otp",
        json={"email": "cust-agent-block@test.com", "otp": "112233"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    stats = client.get("/api/agent/dashboard/stats", headers=headers)
    assert stats.status_code == 403
