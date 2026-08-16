from kickbase_api.user import get_budget, get_username
from kickbase_api.league import (
    get_league_activities,
    get_league_overview,
    get_league_ranking
)
from kickbase_api.manager import (
    get_managers,
    get_manager_performance,
    get_manager_info,
)
from kickbase_api.others import get_achievement_reward, get_matchdays
import pandas as pd

# Kickbase rules
# - Every matchday point is paid out as 1.000 EUR of budget.
#   https://help.kickbase.com/help/rund-um-den-spieltag
# - The "33% rule": your balance may not drop below 33% of (squad value + current balance).
#   https://en.help.kickbase.com/en/help/how-far-can-i-go-into-the-negative-and-how-is-the-33-percent-rule-calculated
POINT_BONUS_PER_POINT = 1_000
MAX_NEGATIVE_RATIO = 0.33

def calc_manager_budgets(token, league_id, league_start_date=None, start_budget=None):
    """Calculate manager budgets based on activities, bonuses, and team performance.

    Args:
        league_start_date: Start of the league, or of its most recent reset. Activities before
                           this point belong to a previous season and are ignored. Defaults to
                           the value reported by the API, which is what you normally want.
        start_budget: Budget every manager starts with. Defaults to the league's configured
                      start budget from the API.
    """

    overview = get_league_overview(token, league_id)

    if league_start_date is None:
        league_start_date = overview["start_date"]
    if start_budget is None:
        start_budget = overview["start_budget"]

    if league_start_date is None or start_budget is None:
        raise RuntimeError(
            "Could not determine league start date / start budget from the API; "
            "pass them explicitly to calc_manager_budgets()."
        )

    print(f"\n{'='*60}")
    print(f"League start / last reset: {league_start_date}  (resets so far: {overview['reset_count']})")
    print(f"Start budget per manager:  {start_budget:,.0f}EUR")
    print(f"{'='*60}")

    try:
        activities, login_bonus, achievement_bonus = get_league_activities(token, league_id, league_start_date)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch activities: {e}")

    activities_df = pd.DataFrame(activities)
    print(f"\nDEBUG: Found {len(activities_df)} trade activities since the league start")

    # Bonuses
    total_login_bonus = sum(entry.get("data", {}).get("bn", 0) for entry in login_bonus)
    print(f"\n1. LOGIN BONUS: {total_login_bonus:,.0f}EUR (from {len(login_bonus)} login events)")

    total_achievement_bonus = 0
    print(f"\n2. ACHIEVEMENT BONUSES:")
    for item in achievement_bonus:
        try:
            a_id = item.get("data", {}).get("t")
            if a_id is None:
                continue
            amount, reward = get_achievement_reward(token, league_id, a_id)
            total_achievement_bonus += amount * reward
            print(f"   Achievement {a_id}: {amount} x {reward:,.0f}EUR = {amount * reward:,.0f}EUR")
        except Exception as e:
            print(f"Warning: Failed to process achievement bonus {item}: {e}")

    print(f"   TOTAL: {total_achievement_bonus:,.0f}EUR")

    # Matchday dates let us count only the points scored after a mid-season reset
    matchday_dates = {}
    try:
        competition_id = overview.get("competition_id") or 1
        matchday_dates = {md["day"]: md["date"] for md in get_matchdays(token, competition_id)}
    except Exception as e:
        print(f"Warning: Could not fetch matchday dates: {e}")

    # Current managers. Anyone who left the league is intentionally not part of this list, so
    # former members no longer show up as rows with a missing team value.
    try:
        managers = get_managers(token, league_id)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch managers: {e}")

    rows = []
    print(f"\n3. MANAGER PERFORMANCE (Point Bonuses):")
    for manager in managers:
        try:
            manager_name, manager_id = manager
            info = get_manager_info(token, league_id, manager_id)
            team_value = info.get("tv", 0) or 0

            perf = get_manager_performance(
                token, league_id, manager_id, manager_name,
                since=league_start_date, matchday_dates=matchday_dates,
            )
            points = perf.get("tp", 0) or 0
            bonus = points * POINT_BONUS_PER_POINT
            rows.append({
                "User": manager_name,
                "Team Value": team_value,
                "point_bonus": bonus,
            })
            print(f"   {manager_name}: {points} points -> {bonus:,.0f}EUR bonus (Team Value: {team_value:,.0f}EUR)")
        except Exception as e:
            print(f"Warning: Skipping manager {manager}: {e}")

    if not rows:
        raise RuntimeError("No managers could be loaded for this league.")

    budget_df = pd.DataFrame(rows)

    # Start every current manager at the league's start budget, then replay all trades.
    budgets = {name: float(start_budget) for name in budget_df["User"]}
    former_members = set()

    for _, row in activities_df.iterrows():
        byr, slr, trp = row.get("byr"), row.get("slr"), row.get("trp", 0) or 0

        # A trade partner who is no longer in the league still moved money out of / into a
        # current manager's account, so the trade is applied to whichever side still exists.
        for user in (byr, slr):
            if pd.notna(user) and user not in budgets:
                former_members.add(user)

        if pd.notna(byr) and byr in budgets:
            budgets[byr] -= trp
        if pd.notna(slr) and slr in budgets:
            budgets[slr] += trp

    if former_members:
        print(f"\nNote: ignoring {len(former_members)} former league member(s) in trades: {', '.join(sorted(former_members))}")

    budget_df["Budget"] = budget_df["User"].map(budgets).astype(float)

    # Point bonus for matchdays played since the league start
    budget_df["Budget"] += budget_df["point_bonus"].fillna(0)
    budget_df.drop(columns=["point_bonus"], inplace=True, errors="ignore")

    # The activity feed only exposes our own login bonus, so it is applied to everyone as an
    # estimate (assumes the other managers logged in just as often).
    budget_df["Budget"] += total_login_bonus

    # Achievement bonuses are also only visible for ourselves, so they are scaled by points
    ranking = get_league_ranking(token, league_id)
    own_username = get_username(token)
    for user in budget_df["User"]:
        bonus = calc_achievement_bonus_by_points(ranking, own_username, user, total_achievement_bonus)
        budget_df.loc[budget_df["User"] == user, "Budget"] += bonus

    # Sync with own actual budget, which is the one number we know exactly
    try:
        own_budget = get_budget(token, league_id)
        mask = budget_df["User"] == own_username
        if mask.any():
            estimated = budget_df.loc[mask, "Budget"].iloc[0]
            print(f"\nOwn budget check: estimated {estimated:,.0f}EUR vs actual {own_budget:,.0f}EUR "
                  f"(off by {estimated - own_budget:+,.0f}EUR)")
            budget_df.loc[mask, "Budget"] = own_budget
    except Exception as e:
        print(f"Warning: Could not sync own budget: {e}")

    # 33% rule: the balance may not drop below 33% of (team value + current balance).
    # Buying a player converts budget into team value, so total wealth stays constant and
    # the spendable amount is simply the balance plus that 33% allowance.
    budget_df["Total Wealth"] = budget_df["Team Value"].fillna(0) + budget_df["Budget"]
    budget_df["Max Negative"] = budget_df["Total Wealth"] * -MAX_NEGATIVE_RATIO
    budget_df["Available Budget"] = budget_df["Budget"] - budget_df["Max Negative"]

    # Sort by total wealth descending
    budget_df.sort_values("Total Wealth", ascending=False, inplace=True, ignore_index=True)

    # Final summary
    total_wealth = budget_df["Total Wealth"]
    print(f"\nFINAL RESULTS:")
    print(f"{'='*60}")
    print(f"   Managers: {len(budget_df)}")
    print(f"   Total budget sum: {budget_df['Budget'].sum():,.0f}EUR")
    print(f"   Total team value: {budget_df['Team Value'].sum():,.0f}EUR")
    print(f"   Total wealth: {total_wealth.sum():,.0f}EUR")
    print(f"   Wealth per manager: min {total_wealth.min():,.0f} / mean {total_wealth.mean():,.0f} / max {total_wealth.max():,.0f}")
    print(f"   Spread max-min: {total_wealth.max() - total_wealth.min():,.0f}EUR")
    print(f"{'='*60}\n")

    return budget_df

def calc_achievement_bonus_by_points(ranking, anchor_user, username, anchor_achievement_bonus):
    """Estimate achievement bonus for a user based on their total points compared to anchor user."""

    ranking_df = pd.DataFrame(ranking, columns=["Name", "Total Points"])

    if ranking_df.empty:
        return 0

    # If the user is the anchor, return exactly the anchor achievement bonus
    if username == anchor_user:
        return anchor_achievement_bonus

    anchor_row = ranking_df[ranking_df["Name"] == anchor_user]
    if anchor_row.empty:
        return 0
    anchor_points = anchor_row["Total Points"].values[0]

    # Get target user's points
    user_row = ranking_df[ranking_df["Name"] == username]
    if user_row.empty:
        return 0
    user_points = user_row["Total Points"].values[0]

    # Calculate bonus scaling based on points ratio
    if anchor_points == 0:
        scale = 1.0
    else:
        scale = user_points / anchor_points

    estimated_bonus = anchor_achievement_bonus * scale
    return estimated_bonus

def calc_achievement_bonus_by_rank(ranking, anchor_user, username, anchor_achievement_bonus):
    """Estimate achievement bonus for a user based on their ranking."""
    """Currently not used, kept for reference."""

    ranking_df = pd.DataFrame(ranking, columns=["Name", "Total Points"])

    if ranking_df.empty:
        return 0

    # If the user is the anchor, return exactly the anchor achievement bonus
    if username == anchor_user:
        return anchor_achievement_bonus

    anchor_row = ranking_df[ranking_df["Name"] == anchor_user]
    if anchor_row.empty:
        return 0
    anchor_rank = anchor_row.index[0] + 1

    # Get target user's rank
    user_row = ranking_df[ranking_df["Name"] == username]
    if user_row.empty:
        return 0
    user_rank = user_row.index[0] + 1

    # Calculate bonus scaling based on rank difference
    # If user is ranked lower (higher number): scale down
    # If user is ranked higher (lower number): scale up
    rank_diff = anchor_rank - user_rank
    scale = 1.0 + (rank_diff * 0.1)

    # Calculate estimated achievement bonus
    estimated_bonus = anchor_achievement_bonus * scale
    return estimated_bonus
