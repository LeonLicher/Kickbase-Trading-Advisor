from kickbase_api.config import BASE_URL, get_json_with_token
import requests

# All functions related to the user itself

def login(username, password):
    """Logs in to Kickbase and returns the authentication token."""

    url = f"{BASE_URL}/user/login"
    payload = {
        "em": username,
        "pass": password,
        "loy": False,
        "rep": {}
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("tkn")

    return token

def get_username(token):
    """Gets the username of the logged-in user."""

    url = f"{BASE_URL}/user/settings"
    data = get_json_with_token(url, token)

    username = data["u"]["unm"]

    return username

def get_players_in_squad(token, league_id):
    """Gets the players in the user's squad for a given league."""

    url = f"{BASE_URL}/leagues/{league_id}/squad"
    data = get_json_with_token(url, token)

    return data

def get_budget(token, league_id):
    """Gets the user's budget for a given league."""

    url = f"{BASE_URL}/leagues/{league_id}/me/budget"
    data = get_json_with_token(url, token)

    data = data["b"]

    return data

def get_stats(token, league_id):
    """Gets the user's stats for a given league."""

    url = f"{BASE_URL}/leagues/{league_id}/me"
    data = get_json_with_token(url, token)

    return data