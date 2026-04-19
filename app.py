from flask import Flask, render_template, jsonify, request
import threading
from database import get_db, init_db
from config import LEAGUE_NAME, START_YEAR, CURRENT_YEAR
import espn_import

app = Flask(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────

def _has_data():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
    conn.close()
    return count > 0


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    conn = get_db()

    seasons = conn.execute(
        "SELECT * FROM seasons ORDER BY year DESC"
    ).fetchall()

    current_standings = conn.execute("""
        SELECT * FROM teams WHERE year = ?
        ORDER BY wins DESC, points_for DESC
    """, (CURRENT_YEAR,)).fetchall()

    all_time = conn.execute("""
        SELECT owner,
               SUM(wins)   AS total_wins,
               SUM(losses) AS total_losses,
               SUM(points_for) AS total_points,
               COUNT(DISTINCT year) AS seasons_played
        FROM teams
        GROUP BY owner
        ORDER BY total_wins DESC, total_points DESC
    """).fetchall()

    champ_counts = conn.execute("""
        SELECT champion_owner, COUNT(*) AS titles
        FROM seasons
        WHERE champion_owner IS NOT NULL
        GROUP BY champion_owner
        ORDER BY titles DESC
    """).fetchall()

    conn.close()
    return render_template("index.html",
        league_name=LEAGUE_NAME,
        seasons=seasons,
        current_standings=current_standings,
        current_year=CURRENT_YEAR,
        all_time=all_time,
        champ_counts=champ_counts,
        has_data=_has_data(),
    )


@app.route("/history")
def history():
    conn = get_db()
    seasons = conn.execute("SELECT * FROM seasons ORDER BY year DESC").fetchall()
    season_data = []
    for s in seasons:
        teams = conn.execute("""
            SELECT * FROM teams WHERE year = ?
            ORDER BY final_standing ASC
        """, (s["year"],)).fetchall()
        season_data.append({"season": s, "teams": teams})
    conn.close()
    return render_template("history.html",
        league_name=LEAGUE_NAME,
        season_data=season_data,
        has_data=_has_data(),
    )


@app.route("/records")
def records():
    conn = get_db()

    most_points_season = conn.execute("""
        SELECT owner, team_name, year, points_for FROM teams
        ORDER BY points_for DESC LIMIT 10
    """).fetchall()

    fewest_points_season = conn.execute("""
        SELECT owner, team_name, year, points_for FROM teams
        WHERE points_for > 0
        ORDER BY points_for ASC LIMIT 10
    """).fetchall()

    best_record = conn.execute("""
        SELECT owner, team_name, year, wins, losses, points_for FROM teams
        ORDER BY wins DESC, points_for DESC LIMIT 10
    """).fetchall()

    worst_record = conn.execute("""
        SELECT owner, team_name, year, wins, losses, points_for FROM teams
        ORDER BY wins ASC, points_for ASC LIMIT 10
    """).fetchall()

    highest_game = conn.execute("""
        SELECT year, week, home_owner, home_team, home_score,
               away_owner, away_team, away_score,
               MAX(home_score, away_score) AS top_score
        FROM matchups WHERE home_score > 0 AND away_score > 0
        ORDER BY top_score DESC LIMIT 10
    """).fetchall()

    biggest_blowout = conn.execute("""
        SELECT year, week, home_owner, home_team, home_score,
               away_owner, away_team, away_score,
               ABS(home_score - away_score) AS margin
        FROM matchups WHERE home_score > 0 AND away_score > 0
        ORDER BY margin DESC LIMIT 10
    """).fetchall()

    closest_games = conn.execute("""
        SELECT year, week, home_owner, home_team, home_score,
               away_owner, away_team, away_score,
               ABS(home_score - away_score) AS margin
        FROM matchups WHERE home_score > 0 AND away_score > 0
        ORDER BY margin ASC LIMIT 10
    """).fetchall()

    most_titles = conn.execute("""
        SELECT champion_owner, COUNT(*) AS titles,
               GROUP_CONCAT(year, ', ') AS years
        FROM seasons WHERE champion_owner IS NOT NULL
        GROUP BY champion_owner ORDER BY titles DESC
    """).fetchall()

    alltime_pct = conn.execute("""
        SELECT owner,
               SUM(wins)   AS w,
               SUM(losses) AS l,
               ROUND(CAST(SUM(wins) AS REAL) / NULLIF(SUM(wins)+SUM(losses),0) * 100, 1) AS pct,
               ROUND(SUM(points_for), 1) AS pf,
               ROUND(SUM(points_for) / NULLIF(COUNT(*), 0), 1) AS ppg
        FROM teams
        GROUP BY owner
        ORDER BY pct DESC
    """).fetchall()

    # Most points in a loss (unlucky)
    most_pts_loss = conn.execute("""
        SELECT year, week,
               CASE WHEN home_score < away_score THEN home_owner ELSE away_owner END AS owner,
               CASE WHEN home_score < away_score THEN home_team  ELSE away_team  END AS team,
               CASE WHEN home_score < away_score THEN home_score ELSE away_score END AS losing_score,
               CASE WHEN home_score < away_score THEN away_score ELSE home_score END AS winning_score
        FROM matchups WHERE home_score > 0 AND away_score > 0
        ORDER BY losing_score DESC LIMIT 10
    """).fetchall()

    # Fewest points in a win (lucky)
    fewest_pts_win = conn.execute("""
        SELECT year, week,
               CASE WHEN home_score > away_score THEN home_owner ELSE away_owner END AS owner,
               CASE WHEN home_score > away_score THEN home_team  ELSE away_team  END AS team,
               CASE WHEN home_score > away_score THEN home_score ELSE away_score END AS winning_score,
               CASE WHEN home_score > away_score THEN away_score ELSE home_score END AS losing_score
        FROM matchups WHERE home_score > 0 AND away_score > 0
        ORDER BY winning_score ASC LIMIT 10
    """).fetchall()

    conn.close()
    return render_template("records.html",
        league_name=LEAGUE_NAME,
        most_points_season=most_points_season,
        fewest_points_season=fewest_points_season,
        best_record=best_record,
        worst_record=worst_record,
        highest_game=highest_game,
        biggest_blowout=biggest_blowout,
        closest_games=closest_games,
        most_titles=most_titles,
        alltime_pct=alltime_pct,
        most_pts_loss=most_pts_loss,
        fewest_pts_win=fewest_pts_win,
        has_data=_has_data(),
    )


@app.route("/h2h")
def h2h():
    conn = get_db()

    owners = [r["owner"] for r in conn.execute(
        "SELECT DISTINCT owner FROM teams ORDER BY owner"
    ).fetchall()]

    h2h_data = {}
    for owner in owners:
        h2h_data[owner] = {}
        for opp in owners:
            if owner == opp:
                h2h_data[owner][opp] = None
                continue
            wins = conn.execute("""
                SELECT COUNT(*) FROM matchups
                WHERE (home_owner=? AND away_owner=? AND home_score > away_score)
                   OR (away_owner=? AND home_owner=? AND away_score > home_score)
            """, (owner, opp, owner, opp)).fetchone()[0]
            losses = conn.execute("""
                SELECT COUNT(*) FROM matchups
                WHERE (home_owner=? AND away_owner=? AND home_score < away_score)
                   OR (away_owner=? AND home_owner=? AND away_score < home_score)
            """, (owner, opp, owner, opp)).fetchone()[0]
            h2h_data[owner][opp] = {"wins": wins, "losses": losses}

    # Pre-compute top rivalries (most games played between any pair)
    rivalries = []
    seen_pairs = set()
    for owner in owners:
        for opp in owners:
            if owner == opp:
                continue
            pair_key = tuple(sorted([owner, opp]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            rec  = h2h_data[owner][opp]
            rec2 = h2h_data[opp][owner]
            if rec and rec2:
                total = rec["wins"] + rec["losses"]
                if total >= 2:
                    rivalries.append({
                        "total": total,
                        "p1": owner, "p2": opp,
                        "w1": rec["wins"], "l1": rec["losses"],
                    })
    rivalries.sort(key=lambda x: x["total"], reverse=True)
    rivalries = rivalries[:6]

    conn.close()
    return render_template("h2h.html",
        league_name=LEAGUE_NAME,
        owners=owners,
        h2h_data=h2h_data,
        rivalries=rivalries,
        has_data=_has_data(),
    )


@app.route("/import", methods=["GET", "POST"])
def import_view():
    if request.method == "POST":
        if not espn_import.import_status["running"]:
            t = threading.Thread(target=espn_import.run_full_import, daemon=True)
            t.start()
        return jsonify({"status": "started"})

    conn = get_db()
    imported = [r["year"] for r in conn.execute(
        "SELECT year FROM seasons ORDER BY year"
    ).fetchall()]
    conn.close()
    return render_template("import.html",
        league_name=LEAGUE_NAME,
        imported_years=imported,
        start_year=START_YEAR,
        current_year=CURRENT_YEAR,
    )


@app.route("/api/import-status")
def api_import_status():
    return jsonify(espn_import.import_status)


@app.route("/api/test-connection")
def api_test_connection():
    from config import LEAGUE_ID, CURRENT_YEAR, ESPN_S2, SWID
    import requests as req
    cookies = {}
    if ESPN_S2 and SWID:
        cookies = {"espn_s2": ESPN_S2, "SWID": SWID}
    url = (f"https://fantasy.espn.com/apis/v3/games/ffl"
           f"/seasons/{CURRENT_YEAR}/segments/0/leagues/{LEAGUE_ID}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.espn.com/fantasy/football/",
    }
    try:
        r = req.get(url, params={"view": "mSettings"}, cookies=cookies,
                    headers=headers, timeout=15)
        if r.headers.get("content-type", "").startswith("application/json"):
            d = r.json()
            name = d.get("settings", {}).get("name", "Unknown League")
            return jsonify({"ok": True, "message": f'Connected! League: "{name}"'})
        else:
            if not ESPN_S2 or not SWID:
                return jsonify({"ok": False,
                    "message": "ESPN returned HTML — league is private. Add ESPN_S2 and SWID to config.py."})
            return jsonify({"ok": False,
                "message": "ESPN returned HTML even with cookies — double-check ESPN_S2 and SWID values."})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})


@app.route("/api/chart/points-by-season")
def chart_points_by_season():
    conn = get_db()
    rows = conn.execute(
        "SELECT year, owner, points_for FROM teams ORDER BY year, points_for DESC"
    ).fetchall()
    conn.close()

    years  = sorted({r["year"]  for r in rows})
    owners = sorted({r["owner"] for r in rows})

    lookup = {(r["year"], r["owner"]): r["points_for"] for r in rows}

    palette = [
        "#FF6384","#36A2EB","#FFCE56","#4BC0C0","#9966FF",
        "#FF9F40","#C9CBCF","#7BC8A4","#EA80FC","#82B1FF",
        "#FF80AB","#CCFF90",
    ]
    datasets = []
    for i, owner in enumerate(owners):
        datasets.append({
            "label": owner,
            "data": [lookup.get((y, owner), None) for y in years],
            "borderColor": palette[i % len(palette)],
            "backgroundColor": palette[i % len(palette)] + "44",
            "tension": 0.3,
            "fill": False,
        })

    return jsonify({"labels": years, "datasets": datasets})


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    # use_reloader=False prevents Werkzeug from killing background import threads
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
