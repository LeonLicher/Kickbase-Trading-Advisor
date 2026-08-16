from datetime import datetime, timezone
import requests

BASE_URL = "https://api.kickbase.com/v4"

def get_json_with_token(url, token):
    """Fetch JSON data from a given URL using token for authorization."""

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def parse_api_datetime(value):
    """Parse a Kickbase timestamp into a timezone-aware UTC datetime.

    The API mixes 'Z'-suffixed and naive ISO timestamps, so comparing them as raw
    strings is unreliable. Naive values are assumed to be UTC. Returns None if the
    value cannot be parsed.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)