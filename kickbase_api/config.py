import requests

BASE_URL = "https://api.kickbase.com/v4"

def get_json_with_token(url, token):
    """Fetch JSON data from a given URL using token for authorization."""

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()