"""
Import ESPN fantasy football data directly via the ESPN API.
One HTTP request per season — explicit 30s timeout, no library loops.

Run directly:  python espn_import.py
Or trigger via the web UI at /import
"""
import requests
from database import get_db, init_db
from config import LEAGUE_ID, START_YEAR, CURRENT_YEAR, ESPN_S2, SWID

import_status = {"running": False, "log": [], "done": False}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.espn.com/fantasy/football/",
    "Accept": "application/json",
}
_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"


def _log(msg):
    print(msg, flush=True)
    import_status["log"].append(msg)


def _fetch(year):
    """Single HTTP GET for one season. Returns dict, or raises ValueError if ESPN
    returns an error payload (HTTP 200 with a 'Not Found' messages body)."""
    cookies = {}
    if ESPN_S2 and SWID:
        cookies = {"espn_s2": ESPN_S2, "SWID": SWID}

    if year >= 2018:
        url    = f"{_BASE}/seasons/{year}/segments/0/leagues/{LEAGUE_ID}"
        params = {"view": ["mTeam", "mMatchupScore", "mSettings", "mStandings"]}
    else:
        url    = f"{_BASE}/leagueHistory/{LEAGUE_ID}"
        params = {"view": ["mTeam", "mMatchupScore", "mSettings", "mStandings"],
                  "seasonId": year}

    resp = requests.get(url, params=params, cookies=cookies,
                        headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        raise ValueError(f"Non-JSON response for {year}: {resp.text[:200]}")

    if isinstance(data, list):
        data = data[0]

    # ESPN returns HTTP 200 with an error body for seasons that don't exist
    if "messages" in data and "teams" not in data:
        msgs = data.get("messages", [])
        raise ValueError(f"ESPN has no data for {year}: {msgs}")

    return data


def import_season(year):
    _log(f"Fetching {year}...")
    try:
        data = _fetch(year)
    except ValueError as exc:
        _log(f"  Skipping {year}: {exc}")
        return False
    except requests.HTTPError as exc:
        _log(f"  HTTP error for {year}: {exc}")
        return False
    except Exception as exc:
        _log(f"  Error fetching {year}: {exc}")
        return False

    # ── Members: id → "First Last" ────────────────────────────────────────
    member_map = {}
    for m in data.get("members", []):
        name = f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
        member_map[m["id"]] = name or f"Member {m['id'][:6]}"

    # ── Settings ──────────────────────────────────────────────────────────
    sched_cfg = data.get("settings", {}).get("scheduleSettings", {})
    # matchupPeriodCount = total periods including playoffs;
    # playoffTeamCount tells us how many playoff rounds to subtract
    total_periods  = sched_cfg.get("matchupPeriodCount") or 14
    playoff_teams  = sched_cfg.get("playoffTeamCount") or 4
    # Derive regular-season weeks: subtract playoff rounds (log2 of playoff teams)
    import math
    playoff_rounds = math.ceil(math.log2(max(playoff_teams, 2)))
    reg_weeks      = int(total_periods) - playoff_rounds
    if reg_weeks < 1:
        reg_weeks = int(total_periods)  # fallback

    # ── Teams ─────────────────────────────────────────────────────────────
    team_map = {}
    for t in data.get("teams", []):
        tid       = t["id"]
        owner_ids = t.get("owners", [])
        owner     = (member_map.get(owner_ids[0], f"Owner {tid}")
                     if owner_ids else f"Owner {tid}")
        team_name = t.get("name", f"Team {tid}")

        rec    = t.get("record", {}).get("overall", {})
        wins   = rec.get("wins", 0)
        losses = rec.get("losses", 0)
        ties   = rec.get("ties", 0)
        pf     = rec.get("pointsFor", 0.0)
        pa     = rec.get("pointsAgainst", 0.0)
        standing = t.get("rankCalculatedFinal") or t.get("playoffSeed") or 0

        team_map[tid] = dict(owner=owner, team_name=team_name,
                             wins=wins, losses=losses, ties=ties,
                             points_for=pf, points_against=pa,
                             final_standing=standing)

    if not team_map:
        _log(f"  Skipping {year}: no team data returned")
        return False

    sorted_teams = sorted(team_map.values(),
                          key=lambda t: t["final_standing"] if t["final_standing"] > 0 else 999)

    # ── Persist ───────────────────────────────────────────────────────────
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

    def _val(lst, idx, key, default=None):
        return lst[idx].get(key, default) if len(lst) > idx else default

    conn.execute("""
        INSERT OR REPLACE INTO seasons
          (year, champion_owner, champion_team, champion_wins, champion_losses,
           champion_points, runner_up_owner, runner_up_team, third_place_owner,
           reg_season_weeks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        year,
        _val(sorted_teams, 0, "owner"),   _val(sorted_teams, 0, "team_name"),
        _val(sorted_teams, 0, "wins"),     _val(sorted_teams, 0, "losses"),
        _val(sorted_teams, 0, "points_for"),
        _val(sorted_teams, 1, "owner"),    _val(sorted_teams, 1, "team_name"),
        _val(sorted_teams, 2, "owner"),
        reg_weeks,
    ))

    matchup_count = 0
    for m in data.get("schedule", []):
        week    = m.get("matchupPeriodId") or 0
        home    = m.get("home") or {}
        away    = m.get("away") or {}
        home_id = home.get("teamId")
        away_id = away.get("teamId")

        if not week or not home_id or not away_id:
            continue
        if home_id not in team_map or away_id not in team_map:
            continue

        home_score = home.get("totalPoints") or 0.0
        away_score = away.get("totalPoints") or 0.0
        if home_score == 0 and away_score == 0:
            continue  # unplayed

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
    _log(f"  OK {year}: {len(team_map)} teams, "
         f"{reg_weeks} reg-season weeks, {matchup_count} matchups stored")
    return True


def run_full_import():
    import_status["running"] = True
    import_status["done"]    = False
    import_status["log"]     = []

    init_db()
    _log(f"Importing seasons {START_YEAR}-{CURRENT_YEAR}...")

    ok    = 0
    total = CURRENT_YEAR - START_YEAR + 1
    for year in range(START_YEAR, CURRENT_YEAR + 1):
        if import_season(year):
            ok += 1

    _log(f"\nDone - {ok}/{total} seasons imported successfully.")
    import_status["running"] = False
    import_status["done"]    = True


if __name__ == "__main__":
    run_full_import()
