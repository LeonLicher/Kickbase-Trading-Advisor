from kickbase_api.config import BASE_URL, get_json_with_token, parse_api_datetime

# All functions related to manager data

def _season_sort_key(season):
    """Sort key for a season entry; season ids grow over time (e.g. 25 -> 34 -> 42)."""

    sid = season.get("sid")
    try:
        return (1, int(sid))
    except (TypeError, ValueError):
        # Unknown/non-numeric ids sort first so a numeric id always wins
        return (0, 0)

def get_managers(token, league_id):
    """Get a list of all managers in the league with their IDs and names."""

    url = f"{BASE_URL}/leagues/{league_id}/ranking"
    data = get_json_with_token(url, token)

    user_info = [(user["n"], user["i"]) for user in data["us"]]

    return user_info

def get_manager_info(token, league_id, manager_id):
    """Get detailed information about a specific manager in the league."""

    url = f"{BASE_URL}/leagues/{league_id}/managers/{manager_id}/dashboard"
    data = get_json_with_token(url, token)

    return data

def get_manager_performance(token, league_id, manager_id, manager_name, since=None, matchday_dates=None):
    """Get performance points for a manager in the *current* season.

    The current season is picked dynamically (highest season id) so the calculation keeps
    working when a new season starts, instead of relying on a hardcoded season id.

    If `since` is given, only matchdays played at or after that time are counted. This makes
    a mid-season league reset work correctly: points scored before the reset are not paid out
    again. `matchday_dates` is an optional {day: date} mapping used when the season entry
    itself carries no per-matchday dates.
    """

    url = f"{BASE_URL}/leagues/{league_id}/managers/{manager_id}/performance"
    data = get_json_with_token(url, token)

    seasons = data.get("it") or []
    if not seasons:
        print(f"Warning: No season data for {manager_name}, assuming 0 points")
        return {"name": manager_name, "tp": 0, "sid": None}

    season = max(seasons, key=_season_sort_key)
    total_points = season.get("tp") or 0

    if since is None:
        return {"name": manager_name, "tp": total_points, "sid": season.get("sid")}

    # Sum only the matchdays that were played after the league start / reset
    start = parse_api_datetime(since)
    matchday_dates = matchday_dates or {}
    points_since = 0
    dated_matchdays = 0

    for matchday in season.get("it") or []:
        matchday_date = parse_api_datetime(matchday.get("md") or matchday_dates.get(matchday.get("day")))
        if matchday_date is None:
            continue
        dated_matchdays += 1
        if start is None or matchday_date >= start:
            points_since += matchday.get("mdp") or 0

    # Without any dated matchday we cannot tell what happened after the reset, so rather than
    # silently reporting zero we fall back to the season total.
    if dated_matchdays == 0:
        print(f"Warning: No matchday dates for {manager_name}, using season total points")
        points_since = total_points

    return {"name": manager_name, "tp": points_since, "sid": season.get("sid")}