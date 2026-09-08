import pytest

@pytest.mark.asyncio
async def test_invalid_login(async_client):
    response = await async_client.post(
        "/auth/login",
        json={"email": "invalid@example.com", "password": "wrongpassword"}
    )
    assert response.status_code in [401, 500]