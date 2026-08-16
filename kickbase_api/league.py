from kickbase_api.config import BASE_URL, get_json_with_token, parse_api_datetime

# All functions related to league data

# Activity feed types we care about
ACTIVITY_TRADE = 15
ACTIVITY_LOGIN_BONUS = 22
ACTIVITY_ACHIEVEMENT = 26

# Number of activities we request; the API caps the feed, so we detect when we hit it
ACTIVITY_FEED_MAX = 5000

def get_league_id(token, league_name):
    """Get the league ID based on the league name."""

    league_infos = get_leagues_infos(token)

    if not league_infos:
        print("Warning: You are not part of any league.")
        return None

    # Try to find leagues matching the given name
    selected_league = [league for league in league_infos if league["name"] == league_name]

    # If no exact match found, fall back to the first available league
    if not selected_league:
        fallback_league = league_infos[0]
        print(
            f"Warning: No league found with name '{league_name}'. "
            f"Falling back to the first available league: '{fallback_league['name']}'"
        )
        return fallback_league["id"]

    return selected_league[0]["id"]

def get_leagues_infos(token):
    """Get information about all leagues the user is part of."""

    url = f"{BASE_URL}/leagues/selection"
    data = get_json_with_token(url, token)

    result = []

    for item in data.get("it", []):
        result.append({
            "id": item.get("i"),
            "name": item.get("n")
        })

    return result

def get_league_overview(token, league_id):
    """Get league metadata, including when the league last started//reset and its start budget.

    'dt' is the timestamp of the league creation or, if the league has been reset, of the
    most recent reset. Deriving it from the API keeps budget calculations correct after a
    reset without anyone having to update a hardcoded date.
    """

    url = f"{BASE_URL}/leagues/{league_id}/overview"
    data = get_json_with_token(url, token)

    return {
        "name": data.get("lnm"),
        "start_date": parse_api_datetime(data.get("dt")),
        "start_budget": data.get("b"),
        "was_reset": bool(data.get("isr", False)),
        "reset_count": data.get("rsn", 0),
        "competition_id": data.get("cpi"),
    }

def get_league_activities(token, league_id, league_start_date):
    """Get league activities such as trades, logins, and achievements since the league start date.

    league_start_date may be a datetime or an ISO string; entries before it belong to a
    previous season/reset and must not be counted.
    """

    url = f"{BASE_URL}/leagues/{league_id}/activitiesFeed?max={ACTIVITY_FEED_MAX}"
    data = get_json_with_token(url, token)

    all_activities = data.get("af", [])
    if len(all_activities) >= ACTIVITY_FEED_MAX:
        print(
            f"Warning: activity feed returned {len(all_activities)} entries and may be truncated; "
            "older trades could be missing from the budget calculation."
        )

    # Filter out entries from before the league start / last reset
    start = parse_api_datetime(league_start_date)
    filtered_activities = []
    for entry in all_activities:
        entry_date = parse_api_datetime(entry.get("dt"))
        if entry_date is None or start is None or entry_date >= start:
            filtered_activities.append(entry)

    login = [entry for entry in filtered_activities if entry.get("t") == ACTIVITY_LOGIN_BONUS]
    achievements = [entry for entry in filtered_activities if entry.get("t") == ACTIVITY_ACHIEVEMENT]
    trading = [
        {k: entry["data"].get(k) for k in ["byr", "slr", "pi", "pn", "tid", "trp"]}
        for entry in filtered_activities
        if entry.get("t") == ACTIVITY_TRADE
    ]

    return trading, login, achievements

def get_league_players_on_market(token, league_id):
    """Get all players currently available on the market in the league."""

    url = f"{BASE_URL}/leagues/{league_id}/market"
    data = get_json_with_token(url, token)

    result = []

    for player in data.get('it', []):
        result.append({
            'id': player.get('i'),
            'prob': player.get('prob'),
            "exp": player.get("exs"),
        })

    return result

def get_league_ranking(token, league_id):
    """Get the overall league ranking."""
    
    url = f"{BASE_URL}/leagues/{league_id}/ranking"
    data = get_json_with_token(url, token)

    players = [(user["n"], user["sp"]) for user in data["us"]]

    # Sort by score (descending)
    ranked = sorted(players, key=lambda x: x[1], reverse=True)

    return ranked