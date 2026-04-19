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
    """)
    conn.commit()
    conn.close()
