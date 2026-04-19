"""
Import ESPN fantasy football league data into the local SQLite database.

Run directly:  python espn_import.py
Or trigger via the web UI at /import
"""
import sys
from database import get_db, init_db
from config import LEAGUE_ID, START_YEAR, CURRENT_YEAR, ESPN_S2, SWID

# Shared progress state (used by the web UI)
import_status = {"running": False, "log": [], "done": False}


def _log(msg):
    print(msg, flush=True)
    import_status["log"].append(msg)


def import_season(year):
    _log(f"Fetching {year} season from ESPN...")
    try:
        from espn_api.football import League
    except ImportError:
        _log("ERROR: espn-api not installed. Run: pip install espn-api")
        return False

    kwargs = {"league_id": LEAGUE_ID, "year": year}
    if ESPN_S2 and SWID:
        kwargs["espn_s2"] = ESPN_S2
        kwargs["swid"] = SWID

    try:
        league = League(**kwargs)
    except Exception as exc:
        _log(f"  Could not fetch {year}: {exc}")
        return False

    reg_season_weeks = league.settings.reg_season_count

    conn = get_db()
    # Clear existing data for this year so we can re-import cleanly
    conn.execute("DELETE FROM teams   WHERE year = ?", (year,))
    conn.execute("DELETE FROM matchups WHERE year = ?", (year,))
    conn.execute("DELETE FROM seasons  WHERE year = ?", (year,))

    # Store each team's season record
    for team in league.teams:
        conn.execute("""
            INSERT OR REPLACE INTO teams
              (year, owner, team_name, wins, losses, ties, points_for, points_against, final_standing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            year,
            team.owner,
            team.team_name,
            team.wins,
            team.losses,
            getattr(team, "ties", 0),
            team.points_for,
            team.points_against,
            team.standing,
        ))

    # Standings sorted by final standing (1 = champion)
    try:
        standings = league.standings()
    except Exception:
        standings = sorted(league.teams, key=lambda t: t.standing)

    def _owner(idx):
        return standings[idx].owner if len(standings) > idx else None

    def _team(idx):
        return standings[idx].team_name if len(standings) > idx else None

    conn.execute("""
        INSERT OR REPLACE INTO seasons
          (year, champion_owner, champion_team, champion_wins, champion_losses,
           champion_points, runner_up_owner, runner_up_team, third_place_owner, reg_season_weeks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        year,
        _owner(0), _team(0),
        standings[0].wins   if standings else None,
        standings[0].losses if standings else None,
        standings[0].points_for if standings else None,
        _owner(1), _team(1),
        _owner(2),
        reg_season_weeks,
    ))

    # league.current_week is the true last week for historical seasons.
    # Requesting a week beyond it silently returns current-week data (no exception),
    # so we must use it as our ceiling rather than catching exceptions.
    max_weeks = getattr(league, "current_week", reg_season_weeks + 4)
    for week in range(1, max_weeks + 1):
        try:
            box_scores = league.box_scores(week=week)
        except Exception:
            break
        if not box_scores:
            break

        is_playoff = 1 if week > reg_season_weeks else 0
        for bs in box_scores:
            # Skip byes / empty slots
            if not hasattr(bs, "home_team") or bs.home_team == 0:
                continue
            if not hasattr(bs, "away_team") or bs.away_team == 0:
                continue
            try:
                conn.execute("""
                    INSERT INTO matchups
                      (year, week, home_owner, home_team, away_owner, away_team,
                       home_score, away_score, is_playoff)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    year, week,
                    bs.home_team.owner, bs.home_team.team_name,
                    bs.away_team.owner, bs.away_team.team_name,
                    bs.home_score, bs.away_score,
                    is_playoff,
                ))
            except Exception:
                continue

    conn.commit()
    conn.close()
    _log(f"  ✓ {year}: {len(league.teams)} teams, {reg_season_weeks} regular-season weeks")
    return True


def run_full_import():
    import_status["running"] = True
    import_status["done"]    = False
    import_status["log"]     = []

    init_db()
    _log(f"Starting import for seasons {START_YEAR}–{CURRENT_YEAR}…")
    ok = 0
    for year in range(START_YEAR, CURRENT_YEAR + 1):
        if import_season(year):
            ok += 1

    _log(f"\nImport complete — {ok}/{CURRENT_YEAR - START_YEAR + 1} seasons imported.")
    import_status["running"] = False
    import_status["done"]    = True


if __name__ == "__main__":
    run_full_import()
