"""
Import ESPN fantasy football data directly via the ESPN API.
One HTTP request per season — no library loops, explicit 30s timeout.

Run directly:  python espn_import.py
Or trigger via the web UI at /import
"""
import requests
from database import get_db, init_db
from config import LEAGUE_ID, START_YEAR, CURRENT_YEAR, ESPN_S2, SWID

import_status = {"running": False, "log": [], "done": False}


def _log(msg):
    print(msg, flush=True)
    import_status["log"].append(msg)


def _fetch(year):
    """
    Single HTTP GET to ESPN for one season.
    Returns parsed JSON dict or raises on error.
    """
    cookies = {}
    if ESPN_S2 and SWID:
        cookies = {"espn_s2": ESPN_S2, "SWID": SWID}

    views = ["mTeam", "mMatchupScore", "mSettings", "mStandings"]

    if year >= 2019:
        url = (f"https://fantasy.espn.com/apis/v3/games/ffl"
               f"/seasons/{year}/segments/0/leagues/{LEAGUE_ID}")
        params = {"view": views}
    else:
        url = (f"https://fantasy.espn.com/apis/v3/games/ffl"
               f"/leagueHistory/{LEAGUE_ID}")
        params = {"view": views, "seasonId": year}

    resp = requests.get(url, params=params, cookies=cookies, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # leagueHistory returns a list; grab the first element
    return data[0] if isinstance(data, list) else data


def import_season(year):
    _log(f"Fetching {year}...")
    try:
        data = _fetch(year)
    except Exception as exc:
        _log(f"  Error fetching {year}: {exc}")
        return False

    # ── Member map: member_id → "First Last" ──────────────────────────────
    member_map = {}
    for m in data.get("members", []):
        name = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
        member_map[m["id"]] = name or f"Unknown ({m['id'][:6]})"

    # ── Settings ──────────────────────────────────────────────────────────
    sched = data.get("settings", {}).get("scheduleSettings", {})
    reg_weeks = sched.get("regularSeasonMatchupPeriodCount",
                 sched.get("matchupPeriodCount", 13))

    # ── Teams ─────────────────────────────────────────────────────────────
    team_map = {}
    for t in data.get("teams", []):
        tid   = t["id"]
        owner_ids = t.get("owners", [])
        owner = member_map.get(owner_ids[0], f"Owner {tid}") if owner_ids else f"Owner {tid}"
        name  = t.get("name", f"Team {tid}")

        rec   = t.get("record", {}).get("overall", {})
        wins  = rec.get("wins", 0)
        losses= rec.get("losses", 0)
        ties  = rec.get("ties", 0)
        pf    = rec.get("pointsFor", 0.0)
        pa    = rec.get("pointsAgainst", 0.0)

        # rankCalculatedFinal = 1 for champion; falls back to playoffSeed
        standing = t.get("rankCalculatedFinal") or t.get("playoffSeed", 0)

        team_map[tid] = dict(owner=owner, team_name=name,
                             wins=wins, losses=losses, ties=ties,
                             points_for=pf, points_against=pa,
                             final_standing=standing)

    sorted_teams = sorted(team_map.values(),
                          key=lambda t: t["final_standing"] if t["final_standing"] > 0 else 999)

    # ── Write to DB ───────────────────────────────────────────────────────
    conn = get_db()
    conn.execute("DELETE FROM teams    WHERE year = ?", (year,))
    conn.execute("DELETE FROM matchups WHERE year = ?", (year,))
    conn.execute("DELETE FROM seasons  WHERE year = ?", (year,))

    for t in team_map.values():
        conn.execute("""
            INSERT OR REPLACE INTO teams
              (year, owner, team_name, wins, losses, ties,
               points_for, points_against, final_standing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (year, t["owner"], t["team_name"],
              t["wins"], t["losses"], t["ties"],
              t["points_for"], t["points_against"], t["final_standing"]))

    def _get(lst, idx, key, default=None):
        return lst[idx].get(key, default) if len(lst) > idx else default

    conn.execute("""
        INSERT OR REPLACE INTO seasons
          (year, champion_owner, champion_team, champion_wins, champion_losses,
           champion_points, runner_up_owner, runner_up_team, third_place_owner,
           reg_season_weeks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        year,
        _get(sorted_teams, 0, "owner"),
        _get(sorted_teams, 0, "team_name"),
        _get(sorted_teams, 0, "wins"),
        _get(sorted_teams, 0, "losses"),
        _get(sorted_teams, 0, "points_for"),
        _get(sorted_teams, 1, "owner"),
        _get(sorted_teams, 1, "team_name"),
        _get(sorted_teams, 2, "owner"),
        reg_weeks,
    ))

    # ── Matchups ──────────────────────────────────────────────────────────
    matchup_count = 0
    for m in data.get("schedule", []):
        week    = m.get("matchupPeriodId", 0)
        home    = m.get("home", {})
        away    = m.get("away", {})
        home_id = home.get("teamId")
        away_id = away.get("teamId")

        if not week or not home_id or not away_id:
            continue
        if home_id not in team_map or away_id not in team_map:
            continue

        home_score = home.get("totalPoints") or 0
        away_score = away.get("totalPoints") or 0
        if home_score == 0 and away_score == 0:
            continue  # unplayed week

        hi = team_map[home_id]
        ai = team_map[away_id]
        conn.execute("""
            INSERT INTO matchups
              (year, week, home_owner, home_team, away_owner, away_team,
               home_score, away_score, is_playoff)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (year, week,
              hi["owner"], hi["team_name"],
              ai["owner"], ai["team_name"],
              home_score, away_score,
              1 if week > reg_weeks else 0))
        matchup_count += 1

    conn.commit()
    conn.close()
    _log(f"  ✓ {year}: {len(team_map)} teams, {matchup_count} matchups stored")
    return True


def run_full_import():
    import_status["running"] = True
    import_status["done"]    = False
    import_status["log"]     = []

    init_db()
    _log(f"Importing {START_YEAR}–{CURRENT_YEAR}…")
    ok = 0
    for year in range(START_YEAR, CURRENT_YEAR + 1):
        if import_season(year):
            ok += 1

    total = CURRENT_YEAR - START_YEAR + 1
    _log(f"\nDone — {ok}/{total} seasons imported.")
    import_status["running"] = False
    import_status["done"]    = True


if __name__ == "__main__":
    run_full_import()
