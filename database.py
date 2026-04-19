import sqlite3
import os
from config import DATABASE_PATH


def get_db():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS seasons (
            year               INTEGER PRIMARY KEY,
            champion_owner     TEXT,
            champion_team      TEXT,
            champion_wins      INTEGER,
            champion_losses    INTEGER,
            champion_points    REAL,
            runner_up_owner    TEXT,
            runner_up_team     TEXT,
            third_place_owner  TEXT,
            reg_season_weeks   INTEGER
        );

        CREATE TABLE IF NOT EXISTS teams (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            year            INTEGER,
            owner           TEXT,
            team_name       TEXT,
            wins            INTEGER,
            losses          INTEGER,
            ties            INTEGER,
            points_for      REAL,
            points_against  REAL,
            final_standing  INTEGER,
            UNIQUE(year, owner)
        );

        CREATE TABLE IF NOT EXISTS matchups (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            year        INTEGER,
            week        INTEGER,
            home_owner  TEXT,
            home_team   TEXT,
            away_owner  TEXT,
            away_team   TEXT,
            home_score  REAL,
            away_score  REAL,
            is_playoff  INTEGER DEFAULT 0
        );

        -- =================================================================
        -- PLAYER DATABASE STRUCTURE
        -- =================================================================
        --
        -- TABLE: draft_picks
        --   One row per drafted player per season.
        --
        --   year            INTEGER  - Season year (e.g. 2024)
        --   overall_pick    INTEGER  - Pick number across the whole draft (1, 2, 3...)
        --   round           INTEGER  - Draft round (1-based)
        --   round_pick      INTEGER  - Pick number within the round (1-based)
        --   team_owner      TEXT     - Fantasy owner who made the pick
        --   team_name       TEXT     - Their team name at draft time
        --   player_id       INTEGER  - ESPN's internal player ID (stable across years)
        --   player_name     TEXT     - Player full name
        --   position        TEXT     - QB | RB | WR | TE | K | DST
        --   nfl_team        TEXT     - NFL team abbreviation (e.g. KC, SF, NYG)
        --   bid_amount      REAL     - Auction price; 0 for snake drafts
        --   is_keeper       INTEGER  - 1 if kept from prior year, 0 if newly drafted
        --
        --   Useful queries:
        --     -- All picks for one owner in one year
        --     SELECT * FROM draft_picks WHERE year=2024 AND team_owner='Ryan Daly' ORDER BY overall_pick;
        --
        --     -- Best value picks: drafted late (high pick#) but scored a lot
        --     SELECT d.player_name, d.overall_pick, d.position, r.total_points
        --     FROM draft_picks d
        --     JOIN roster_players r ON r.player_id=d.player_id AND r.year=d.year
        --     ORDER BY r.total_points DESC;
        --
        --     -- How many times each position was taken in round 1
        --     SELECT position, COUNT(*) FROM draft_picks WHERE round=1 GROUP BY position;
        --
        CREATE TABLE IF NOT EXISTS draft_picks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            year         INTEGER,
            overall_pick INTEGER,
            round        INTEGER,
            round_pick   INTEGER,
            team_owner   TEXT,
            team_name    TEXT,
            player_id    INTEGER,
            player_name  TEXT,
            position     TEXT,
            nfl_team     TEXT,
            bid_amount   REAL    DEFAULT 0,
            is_keeper    INTEGER DEFAULT 0
        );

        -- =================================================================
        -- TABLE: roster_players
        --   One row per player per team per season (end-of-season snapshot).
        --   Covers everyone on a roster at season end, regardless of how
        --   they were acquired (draft, waiver, trade, free agent).
        --
        --   year             INTEGER  - Season year
        --   team_owner       TEXT     - Fantasy owner
        --   team_name        TEXT     - Fantasy team name
        --   player_id        INTEGER  - ESPN player ID (join to draft_picks)
        --   player_name      TEXT     - Player full name
        --   position         TEXT     - QB | RB | WR | TE | K | DST
        --   nfl_team         TEXT     - NFL team abbreviation
        --   acquisition_type TEXT     - How they arrived: DRAFT | WAIVER | TRADE | FREE_AGENT
        --   total_points     REAL     - Season fantasy points actually scored
        --   avg_points       REAL     - Average fantasy points per game
        --
        --   Useful queries:
        --     -- Top scorers league-wide in 2024
        --     SELECT player_name, position, team_owner, total_points
        --     FROM roster_players WHERE year=2024 ORDER BY total_points DESC LIMIT 20;
        --
        --     -- One owner's full roster across all years
        --     SELECT year, player_name, position, total_points
        --     FROM roster_players WHERE team_owner='Ryan Daly' ORDER BY year, total_points DESC;
        --
        --     -- Average points by position across all years
        --     SELECT year, position, AVG(total_points), COUNT(*)
        --     FROM roster_players GROUP BY year, position ORDER BY year, position;
        --
        --     -- Players who appeared on rosters in multiple years (multi-season
        --     SELECT player_name, COUNT(DISTINCT year) as seasons, SUM(total_points) as career_pts
        --     FROM roster_players GROUP BY player_id HAVING seasons > 1 ORDER BY career_pts DESC;
        --
        --     -- Draft pick value: compare pick slot to actual points scored
        --     SELECT d.overall_pick, d.player_name, d.position, r.total_points
        --     FROM draft_picks d
        --     JOIN roster_players r ON d.player_id=r.player_id AND d.year=r.year
        --     ORDER BY d.overall_pick;
        --
        CREATE TABLE IF NOT EXISTS roster_players (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            year             INTEGER,
            team_owner       TEXT,
            team_name        TEXT,
            player_id        INTEGER,
            player_name      TEXT,
            position         TEXT,
            nfl_team         TEXT,
            acquisition_type TEXT,
            total_points     REAL    DEFAULT 0,
            avg_points       REAL    DEFAULT 0,
            UNIQUE(year, player_id, team_owner)
        );
        -- =================================================================
    """)
    conn.commit()
    conn.close()
