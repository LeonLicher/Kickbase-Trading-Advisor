from kickbase_api.config import BASE_URL, get_json_with_token
from kickbase_api.others import get_all_teams
from datetime import datetime, timedelta

# All functions related to player data

def get_player_id(token, competition_id, name):
    """Search for a player by name and return their player ID."""

    url = f"{BASE_URL}/competitions/{competition_id}/players/search?query={name}"
    data = get_json_with_token(url, token)

    player_id = data["it"][0]["pi"]  # Gets first player's ID directly, assuming the search returns only one result

    return player_id

def get_player_market_value(token, competition_id, player_id, last_mv_values):
    """Get the market value history of a player."""

    timeframe = 365  # amount of last values to retrieve, min 92, max 365
    url = f"{BASE_URL}/competitions/{competition_id}/players/{player_id}/marketvalue/{timeframe}"
    data = get_json_with_token(url, token)

    # get last last_mv_values market values
    market_values = [(item['dt'], item['mv']) for item in data['it'][-last_mv_values:]]

    # convert Unix epoch days to ISO date and wrap in dict
    epoch = datetime(1970, 1, 1)  # Unix epoch
    market_values = [
        {
            "mv": value,
            "date": (epoch + timedelta(days=days)).date().isoformat()
        }
        for days, value in market_values
    ]

    return market_values

def get_player_info(token, competition_id, player_id):
    """Get basic information about a player."""

    url = f"{BASE_URL}/competitions/{competition_id}/players/{player_id}"
    data = get_json_with_token(url, token)

    player_info = {
        "player_id": data.get("i"),     
        "team_id": data.get("tid"),     
        "team_name": data.get("tn"),    
        "first_name": data.get("fn"),   
        "last_name": data.get("ln"),    
        "position": data.get("pos")     
    }

    return player_info

def get_all_players(token, competition_id):
    """Get all players in a competition by iterating through all teams."""

    all_players = []  # Initialize an empty list to store all players

    team_ids = [team["team_id"] for team in get_all_teams(token, competition_id)]

    for team_id in team_ids:
        url = f"{BASE_URL}/competitions/{competition_id}/teams/{team_id}/teamprofile"
        data = get_json_with_token(url, token)

        # Extract player IDs and names
        players = [(player["i"]) for player in data['it']]

        # Append the players to the main list
        all_players.extend(players)

    return all_players  # Return the combined list at the end

def get_player_performance(token, competition_id, player_id, last_pfm_values, player_team):
    """Get the performance history of a player, including different metrics."""

    url = f"{BASE_URL}/competitions/{competition_id}/players/{player_id}/performance"
    data = get_json_with_token(url, token)

    # Gather all performance entries
    all_ph = [
        m
        for item in data["it"]
        for m in item["ph"]
    ]

    # TODO: This makes problems rn, as one row of data will be added for each matchday
    # Since they are not on the same days this makes problems if we are on the day of a matchday
    # Only include performances up to the current date or the next md
    current_date = datetime.now().date()

    future_dates = [
        datetime.fromisoformat(m["md"].replace("Z", "+00:00")).date()
        for m in all_ph
        if datetime.fromisoformat(m["md"].replace("Z", "+00:00")).date() > current_date
    ]
    next_md = min(future_dates) if future_dates else current_date

    # Keep performances up to next_md
    all_ph = [
        m for m in all_ph
        if datetime.fromisoformat(m["md"].replace("Z", "+00:00")).date() <= next_md
    ]
    
    # Last n performance values
    performance_values = all_ph[-last_pfm_values:]

    result = []
    for m in performance_values:
        # Extract minutes played, handling possible formats and missing values
        mp_str = m.get("mp", "0'")
        try:
            minutes_played = int(mp_str.replace("'", "")) if mp_str else 0
        except ValueError:
            minutes_played = 0

        # Points
        points = m.get("p", None)

        # Points per Minute
        ppm = points / minutes_played if points is not None and minutes_played > 0 else None

        # Determine match result for player's team
        t1 = m.get("t1")
        t2 = m.get("t2")
        t1g = m.get("t1g")
        t2g = m.get("t2g")
        won = None
        if t1g is not None and t2g is not None:
            if player_team == t1:
                if t1g > t2g:
                    won = 1
                elif t1g < t2g:
                    won = 0
                else:
                    won = None
            elif player_team == t2:
                if t2g > t1g:
                    won = 1
                elif t2g < t1g:
                    won = 0
                else:
                    won = None

        result.append({
            "md": datetime.fromisoformat(m["md"].replace("Z", "+00:00")).date().isoformat(),
            "date": datetime.fromisoformat(m["md"].replace("Z", "+00:00")).date().isoformat(),
            "p": points,
            "mp": minutes_played,
            "ppm": ppm,
            "t1": t1,
            "t2": t2,
            "t1g": t1g,
            "t2g": t2g,
            "won": won,
            "k": m.get("k")
        })

    return result