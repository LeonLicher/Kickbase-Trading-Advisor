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
import logging

logger = logging.getLogger(__name__)

def calc_manager_budgets(token, league_id, league_start_date, start_budget):
    """Calculate manager budgets based on activities, bonuses, and team performance."""

    try:
        activities, login_bonus, achievement_bonus = get_league_activities(token, league_id, league_start_date)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch activities: {e}")

    activities_df = pd.DataFrame(activities)

    # Bonuses
    total_login_bonus = sum(entry.get("data", {}).get("bn", 0) for entry in login_bonus)
    logger.info(f"[ACHIEVEMENTS] Total login bonus entries: {len(login_bonus)}, Total login bonus: {total_login_bonus:,.0f}")

    # Count achievements by ID (each entry in achievement_bonus = 1 occurrence)
    achievement_counts = {}
    logger.info(f"[ACHIEVEMENTS] Total achievement bonus entries: {len(achievement_bonus)}")
    
    for idx, item in enumerate(achievement_bonus):
        try:
            a_id = item.get("data", {}).get("t")
            if a_id is None:
                logger.info(f"[ACHIEVEMENTS] Entry {idx}: No achievement ID found, skipping")
                continue
            
            # Count this achievement occurrence
            achievement_counts[a_id] = achievement_counts.get(a_id, 0) + 1
            logger.info(f"[ACHIEVEMENTS] Entry {idx}: achievement_id={a_id}")
        except Exception as e:
            print(f"Warning: Failed to process achievement bonus {item}: {e}")
    
    # Calculate total achievement bonus based on counted occurrences
    total_achievement_bonus = 0
    logger.info(f"[ACHIEVEMENTS] Unique achievements earned: {len(achievement_counts)}")
    
    for a_id, count in achievement_counts.items():
        try:
            # Get the reward value (ignore the all-time amount from API)
            _, reward = get_achievement_reward(token, league_id, a_id)
            bonus_value = count * reward
            total_achievement_bonus += bonus_value
            logger.info(f"[ACHIEVEMENTS] achievement_id={a_id}: earned {count} times this season, reward={reward:,.0f}, total_bonus={bonus_value:,.0f}")
        except Exception as e:
            print(f"Warning: Failed to get reward for achievement {a_id}: {e}")
    
    logger.info(f"[ACHIEVEMENTS] Total achievement bonus calculated: {total_achievement_bonus:,.0f}")

    # Manager performances
    try:
        managers = get_managers(token, league_id)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch managers: {e}")

    performances = []
    for manager in managers:
        try:
            manager_name, manager_id = manager
            info = get_manager_info(token, league_id, manager_id)
            team_value = info.get("tv", 0)

            perf = get_manager_performance(token, league_id, manager_id, manager_name)
            perf["Team Value"] = team_value
            performances.append(perf)
        except Exception as e:
            print(f"Warning: Skipping manager {manager}: {e}")

    perf_df = pd.DataFrame(performances)
    if not perf_df.empty:
        perf_df["point_bonus"] = perf_df["tp"].fillna(0) * 1000
        for _, row in perf_df.iterrows():
            if row['name'] == "LeonLMessi":
                logger.info(f"[{row['name']}] Total points: {row['tp']}, Point bonus: {row['point_bonus']:,.0f}")
    else:
        perf_df["name"] = []
        perf_df["point_bonus"] = []
        perf_df["Team Value"] = []

    # Initial budgets from activities
    budgets = {user: start_budget for user in set(activities_df["byr"].dropna().unique())
                                          .union(set(activities_df["slr"].dropna().unique()))}

    # Track trading activity per user
    trading_spent = {user: 0 for user in budgets}
    trading_earned = {user: 0 for user in budgets}

    for _, row in activities_df.iterrows():
        byr, slr, trp = row.get("byr"), row.get("slr"), row.get("trp", 0)
        try:
            if pd.isna(byr) and pd.notna(slr):
                budgets[slr] += trp
                trading_earned[slr] += trp
            elif pd.isna(slr) and pd.notna(byr):
                budgets[byr] -= trp
                trading_spent[byr] += trp
            elif pd.notna(byr) and pd.notna(slr):
                budgets[byr] -= trp
                budgets[slr] += trp
                trading_spent[byr] += trp
                trading_earned[slr] += trp
        except KeyError as e:
            print(f"Warning: Skipping invalid activity row {row}: {e}")

    # Log trading activity for each user
    for user in budgets:
        if user == "LeonLMessi":
            spent = trading_spent.get(user, 0)
            earned = trading_earned.get(user, 0)
            net = earned - spent
            logger.info(f"[{user}] Trading: spent={spent:,.0f}, earned={earned:,.0f}, net={net:,.0f}")
            logger.info(f"[{user}] Budget after trading: {budgets[user]:,.0f}")

    budget_df = pd.DataFrame(list(budgets.items()), columns=["User", "Budget"])

    # Merge performance bonuses
    budget_df = budget_df.merge(
        perf_df[["name", "point_bonus", "Team Value"]],
        left_on="User",
        right_on="name",
        how="left"
    ).drop(columns=["name"], errors="ignore")

    # Log point bonus before applying
    for _, row in budget_df.iterrows():
        if row['User'] == "LeonLMessi" and pd.notna(row.get("point_bonus")):
            logger.info(f"[{row['User']}] Point bonus: {row['point_bonus']:,.0f}")

    budget_df["Budget"] = budget_df["Budget"] + budget_df["point_bonus"].fillna(0)
    budget_df.drop(columns=["point_bonus"], inplace=True, errors="ignore")

    # add total login bonus equally to everyone (100% estimation, if the user logged in every day)
    for user in budget_df["User"]:
        if user == "LeonLMessi":
            logger.info(f"[{user}] Login bonus: {total_login_bonus:,.0f}")
    budget_df["Budget"] += total_login_bonus

    # Ensure consistent float format
    budget_df["Budget"] = budget_df["Budget"].astype(float)

    # add total achievement bonus based on anchor value and current ranking (estimation approach)
    for user in budget_df["User"]:
        achievement_bonus = calc_achievement_bonus_by_points(token, league_id, user, total_achievement_bonus)
        budget_df.loc[budget_df["User"] == user, "Budget"] += achievement_bonus

    # Log calculated budgets for all users
    for _, row in budget_df.iterrows():
        if row['User'] == "LeonLMessi":
            logger.info(f"[{row['User']}] Calculated budget: {row['Budget']:,.1f}")

    # Sync with own actual budget
    try:
        own_budget = get_budget(token, league_id)
        own_username = get_username(token)
        mask = budget_df["User"] == own_username
        if not budget_df.loc[mask, "Budget"].eq(own_budget).all():
            calculated_budget = budget_df.loc[mask, "Budget"].values[0]
            difference = own_budget - calculated_budget
            logger.info(f"[{own_username}] Budget mismatch - calculated: {calculated_budget:,.1f}, actual: {own_budget:,.1f}, difference: {difference:,.1f}")
            budget_df.loc[mask, "Budget"] = own_budget
    except Exception as e:
        print(f"Warning: Could not sync own budget: {e}")

    # TODO check if this also applies if the user has positiv budget, currently only tested with negative budget
    budget_df["Max Negative"] = (budget_df["Team Value"].fillna(0) + budget_df["Budget"]) * -0.33

    # Calculate available budget
    budget_df["Available Budget"] = (budget_df["Max Negative"].fillna(0) - budget_df["Budget"]) * -1

    # Sort by available budget ascending
    budget_df.sort_values("Available Budget", ascending=False, inplace=True, ignore_index=True)

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
        if username == "LeonLMessi":
            logger.info(f"[{username}] Achievement bonus calculation: anchor user with {anchor_points} points, bonus={anchor_achievement_bonus:,.1f}")
            logger.info(f"[{username}] Achievement bonus: {anchor_achievement_bonus:,.1f}")
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
    if username == "LeonLMessi":
        logger.info(f"[{username}] Achievement bonus calculation: {user_points} points (anchor: {anchor_points}), scale={scale:.4f}, bonus={estimated_bonus:,.1f}")
        logger.info(f"[{username}] Achievement bonus: {estimated_bonus:,.1f}")
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