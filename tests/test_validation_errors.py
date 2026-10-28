import pytest

SECRET = "Super-Secret-Value-123!"


@pytest.mark.asyncio
async def test_validation_errors_do_not_echo_submitted_values(auth_client):
    response = await auth_client.post(
        "/api/v1/auth/staff/login",
        json={"phone": "+919876543210", "password": SECRET, "role": "ADMIN"},
    )

    assert response.status_code == 422
    assert SECRET not in response.text
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}


@pytest.mark.asyncio
async def test_validation_error_shape_is_still_a_list_with_locations(
    auth_client,
):
    response = await auth_client.post(
        "/api/v1/auth/citizen/request-otp", json={"phone": "not-a-phone"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert detail[0]["loc"][0] == "body"
