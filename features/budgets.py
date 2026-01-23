from kickbase_api.user import get_budget, get_username
from kickbase_api.league import (
    get_league_activities,
    get_league_ranking
)
from kickbase_api.manager import (
    get_managers,
    get_manager_performance,
    get_manager_info,
)
from kickbase_api.others import get_achievement_reward
import pandas as pd

def calc_manager_budgets(token, league_id, league_start_date, start_budget, reset_baseline_points=None):
    """Calculate manager budgets based on activities, bonuses, and team performance.
    
    Args:
        reset_baseline_points: Dict of {username: points} at reset time. If provided, only points 
                               earned since reset will be counted. Use {} to ignore all point bonuses.
    """
    
    if reset_baseline_points is None:
        reset_baseline_points = {}

    try:
        activities, login_bonus, achievement_bonus = get_league_activities(token, league_id, league_start_date)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch activities: {e}")

    activities_df = pd.DataFrame(activities)
    print(f"\n{'='*60}")
    print(f"DEBUG: Found {len(activities_df)} activities since {league_start_date}")
    print(f"{'='*60}")

    # Bonuses
    total_login_bonus = sum(entry.get("data", {}).get("bn", 0) for entry in login_bonus)
    print(f"\n1️⃣ LOGIN BONUS: {total_login_bonus:,.2f}€ (from {len(login_bonus)} login events)")
    if len(login_bonus) > 0:
        print(f"   First login: {login_bonus[0].get('dt', 'N/A')}")
        print(f"   Last login: {login_bonus[-1].get('dt', 'N/A')}")

    total_achievement_bonus = 0
    print(f"\n2️⃣ ACHIEVEMENT BONUSES:")
    for item in achievement_bonus:
        try:
            a_id = item.get("data", {}).get("t")
            if a_id is None:
                continue
            amount, reward = get_achievement_reward(token, league_id, a_id)
            total_achievement_bonus += amount * reward
            print(f"   Achievement {a_id}: {amount} x {reward:,.0f}€ = {amount * reward:,.2f}€")
        except Exception as e:
            print(f"Warning: Failed to process achievement bonus {item}: {e}")
    
    print(f"   TOTAL: {total_achievement_bonus:,.2f}€")

    # Manager performances
    try:
        managers = get_managers(token, league_id)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch managers: {e}")

    performances = []
    print(f"\n3️⃣ MANAGER PERFORMANCE (Point Bonuses):")
    for manager in managers:
        try:
            manager_name, manager_id = manager
            info = get_manager_info(token, league_id, manager_id)
            team_value = info.get("tv", 0)

            perf = get_manager_performance(token, league_id, manager_id, manager_name)
            perf["Team Value"] = team_value
            performances.append(perf)
            points = perf.get('tp', 0)
            bonus = points * 1000
            print(f"   {manager_name}: {points} points → {bonus:,.0f}€ bonus (Team Value: {team_value:,.0f}€)")
        except Exception as e:
            print(f"Warning: Skipping manager {manager}: {e}")

    perf_df = pd.DataFrame(performances)
    if not perf_df.empty:
        # Calculate points earned since reset (baseline points subtracted)
        print(f"\n⚠️  Using baseline points from reset - calculating points since reset:")
        perf_df["baseline_points"] = perf_df["name"].map(reset_baseline_points).fillna(0)
        perf_df["points_since_reset"] = perf_df["tp"].fillna(0) - perf_df["baseline_points"]
        perf_df["point_bonus"] = perf_df["points_since_reset"] * 1000
        
        for _, row in perf_df.iterrows():
            print(f"   {row['name']}: {row['tp']:.0f} - {row['baseline_points']:.0f} = {row['points_since_reset']:.0f} points → {row['point_bonus']:,.0f}€")
    else:
        perf_df["name"] = []
        perf_df["point_bonus"] = []
        perf_df["Team Value"] = []

    # Initial budgets from activities
    budgets = {user: start_budget for user in set(activities_df["byr"].dropna().unique())
                                          .union(set(activities_df["slr"].dropna().unique()))}

    for _, row in activities_df.iterrows():
        byr, slr, trp = row.get("byr"), row.get("slr"), row.get("trp", 0)
        try:
            if pd.isna(byr) and pd.notna(slr):
                budgets[slr] += trp
            elif pd.isna(slr) and pd.notna(byr):
                budgets[byr] -= trp
            elif pd.notna(byr) and pd.notna(slr):
                budgets[byr] -= trp
                budgets[slr] += trp
        except KeyError as e:
            print(f"Warning: Skipping invalid activity row {row}: {e}")

    budget_df = pd.DataFrame(list(budgets.items()), columns=["User", "Budget"])

    # Merge performance bonuses
    budget_df = budget_df.merge(
        perf_df[["name", "point_bonus", "Team Value"]],
        left_on="User",
        right_on="name",
        how="left"
    ).drop(columns=["name"], errors="ignore")

    budget_df["Budget"] = budget_df["Budget"] + budget_df["point_bonus"].fillna(0)
    budget_df.drop(columns=["point_bonus"], inplace=True, errors="ignore")

    # add total login bonus equally to everyone (100% estimation, if the user logged in every day)
    budget_df["Budget"] += total_login_bonus

    # Ensure consistent float format
    budget_df["Budget"] = budget_df["Budget"].astype(float)

    # add total achievement bonus based on anchor value and current ranking (estimation approach)
    for user in budget_df["User"]:
        achievement_bonus = calc_achievement_bonus_by_points(token, league_id, user, total_achievement_bonus)
        budget_df.loc[budget_df["User"] == user, "Budget"] += achievement_bonus

    # Sync with own actual budget
    try:
        own_budget = get_budget(token, league_id)
        own_username = get_username(token)
        mask = budget_df["User"] == own_username
        if not budget_df.loc[mask, "Budget"].eq(own_budget).all():
            budget_df.loc[mask, "Budget"] = own_budget
    except Exception as e:
        print(f"Warning: Could not sync own budget: {e}")

    # TODO check if this also applies if the user has positiv budget, currently only tested with negative budget
    budget_df["Total Wealth"] = budget_df["Team Value"].fillna(0) + budget_df["Budget"]
    budget_df["Max Negative"] = budget_df["Total Wealth"] * -0.33

    # Calculate available budget
    budget_df["Available Budget"] = (budget_df["Max Negative"].fillna(0) - budget_df["Budget"]) * -1

    # Sort by total wealth descending
    budget_df.sort_values("Total Wealth", ascending=False, inplace=True, ignore_index=True)

    # Final summary
    total_budget_sum = budget_df["Budget"].sum()
    total_team_value = budget_df["Team Value"].sum()
    total_available = budget_df["Available Budget"].sum()
    total_wealth = budget_df["Total Wealth"].sum()
    
    print(f"\n🎯 FINAL RESULTS:")
    print(f"{'='*60}")
    print(f"   Total budget sum: {total_budget_sum:,.2f}€")
    print(f"   Total team value: {total_team_value:,.2f}€")
    print(f"   Total wealth (Budget + Team Value): {total_wealth:,.2f}€")
    print(f"   Expected for {len(budget_df)} managers @ 150M each: {len(budget_df) * 150_000_000:,.2f}€")
    print(f"   Difference: {total_wealth - (len(budget_df) * 150_000_000):,.2f}€")
    print(f"   Total available budget: {total_available:,.2f}€")
    print(f"{'='*60}\n")

    return budget_df

def calc_achievement_bonus_by_points(token, league_id, username, anchor_achievement_bonus):
    """Estimate achievement bonus for a user based on their total points compared to anchor user."""

    ranking = get_league_ranking(token, league_id)
    ranking_df = pd.DataFrame(ranking, columns=["Name", "Total Points"])

    # Total number of users
    num_users = len(ranking_df)
    if num_users == 0:
        return 0

    # Get anchor user's name and points
    anchor_user = get_username(token)
    anchor_row = ranking_df[ranking_df["Name"] == anchor_user]
    if anchor_row.empty:
        return 0
    anchor_points = anchor_row["Total Points"].values[0]

    # If the user is the anchor, return exactly the anchor achievement bonus
    if username == anchor_user:
        return anchor_achievement_bonus

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

def calc_achievement_bonus_by_rank(token, league_id, username, anchor_achievement_bonus):
    """Estimate achievement bonus for a user based on their ranking."""
    """Currently not used, kept for reference."""

    ranking = get_league_ranking(token, league_id)
    ranking_df = pd.DataFrame(ranking, columns=["Name", "Total Points"])

    # Total number of users
    num_users = len(ranking_df)
    if num_users == 0:
        return 0

    # Get anchor user's name and rank
    anchor_user = get_username(token)
    anchor_row = ranking_df[ranking_df["Name"] == anchor_user]
    if anchor_row.empty:
        return 0
    anchor_rank = anchor_row.index[0] + 1

    # If the user is the anchor, return exactly the anchor achievement bonus
    if username == anchor_user:
        return anchor_achievement_bonus

    # Get target user's rank and points
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
