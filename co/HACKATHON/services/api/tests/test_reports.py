import pytest

@pytest.mark.asyncio
async def test_upload_url_invalid_extension(async_client):
    response = await async_client.get("/reports/upload-url?filename=virus.exe")
    assert response.status_code == 422