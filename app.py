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


@app.route("/sacko")
def sacko():
    conn = get_db()

    # Sacko = last-place finisher each year (highest final_standing)
    sacko_history = conn.execute("""
        SELECT t.year, t.owner, t.team_name, t.wins, t.losses, t.ties,
               t.points_for, t.points_against, t.final_standing
        FROM teams t
        WHERE t.final_standing = (
            SELECT MAX(final_standing) FROM teams t2 WHERE t2.year = t.year
        )
        ORDER BY t.year DESC
    """).fetchall()

    # All-time Sacko count per owner
    sacko_counts = conn.execute("""
        SELECT t.owner, COUNT(*) AS sacko_count,
               GROUP_CONCAT(t.year, ', ') AS years
        FROM teams t
        WHERE t.final_standing = (
            SELECT MAX(final_standing) FROM teams t2 WHERE t2.year = t.year
        )
        GROUP BY t.owner
        ORDER BY sacko_count DESC
    """).fetchall()

    # Worst single-season record among Sacko teams
    worst_record = conn.execute("""
        SELECT t.owner, t.team_name, t.year, t.wins, t.losses, t.points_for
        FROM teams t
        WHERE t.final_standing = (
            SELECT MAX(final_standing) FROM teams t2 WHERE t2.year = t.year
        )
        ORDER BY t.wins ASC, t.points_for ASC
        LIMIT 5
    """).fetchall()

    # Fewest points in a season by a Sacko team
    fewest_points = conn.execute("""
        SELECT t.owner, t.team_name, t.year, t.points_for, t.wins, t.losses
        FROM teams t
        WHERE t.final_standing = (
            SELECT MAX(final_standing) FROM teams t2 WHERE t2.year = t.year
        )
        ORDER BY t.points_for ASC
        LIMIT 5
    """).fetchall()

    # Lowest single-game score by a Sacko team (reg season only)
    worst_game = conn.execute("""
        SELECT m.year, m.week, m.home_owner, m.home_score, m.away_owner, m.away_score,
               MIN(m.home_score, m.away_score) AS low_score,
               CASE WHEN m.home_score < m.away_score THEN m.home_owner ELSE m.away_owner END AS loser_owner
        FROM matchups m
        WHERE m.is_playoff = 0
          AND (
            (m.home_owner = (SELECT t.owner FROM teams t WHERE t.year=m.year
                             AND t.final_standing=(SELECT MAX(final_standing) FROM teams t2 WHERE t2.year=t.year)
                             LIMIT 1)
             AND m.home_score < m.away_score)
            OR
            (m.away_owner = (SELECT t.owner FROM teams t WHERE t.year=m.year
                             AND t.final_standing=(SELECT MAX(final_standing) FROM teams t2 WHERE t2.year=t.year)
                             LIMIT 1)
             AND m.away_score < m.home_score)
          )
        ORDER BY low_score ASC
        LIMIT 5
    """).fetchall()

    # Biggest blowout loss by a Sacko team
    biggest_loss = conn.execute("""
        SELECT m.year, m.week,
               CASE WHEN m.home_score < m.away_score THEN m.home_owner ELSE m.away_owner END AS sacko_owner,
               CASE WHEN m.home_score < m.away_score THEN m.home_score ELSE m.away_score END AS sacko_score,
               CASE WHEN m.home_score > m.away_score THEN m.home_owner ELSE m.away_owner END AS opp_owner,
               CASE WHEN m.home_score > m.away_score THEN m.home_score ELSE m.away_score END AS opp_score,
               ABS(m.home_score - m.away_score) AS margin
        FROM matchups m
        WHERE (
            m.home_owner IN (SELECT t.owner FROM teams t WHERE t.year=m.year
                             AND t.final_standing=(SELECT MAX(final_standing) FROM teams t2 WHERE t2.year=t.year))
            OR
            m.away_owner IN (SELECT t.owner FROM teams t WHERE t.year=m.year
                             AND t.final_standing=(SELECT MAX(final_standing) FROM teams t2 WHERE t2.year=t.year))
        )
        ORDER BY margin DESC
        LIMIT 5
    """).fetchall()

    conn.close()
    return render_template("sacko.html",
        league_name=LEAGUE_NAME,
        sacko_history=sacko_history,
        sacko_counts=sacko_counts,
        worst_record=worst_record,
        fewest_points=fewest_points,
        worst_game=worst_game,
        biggest_loss=biggest_loss,
        has_data=_has_data(),
    )

@app.route("/draft")
def draft():
    conn = get_db()

    # Position averages per year — used to normalize across positions
    # so QBs (who naturally score more) don't dominate the value lists.
    # value_score = player's points minus the avg for their position that year.
    best_value = conn.execute("""
        WITH pos_avg AS (
            SELECT r.year, d.position, AVG(r.total_points) AS avg_pts
            FROM draft_picks d
            JOIN roster_players r ON d.player_id = r.player_id AND d.year = r.year
            WHERE r.total_points > 0
            GROUP BY r.year, d.position
        )
        SELECT d.overall_pick, d.round, d.round_pick, d.player_name,
               d.position, d.nfl_team, d.team_owner, d.year, r.total_points,
               ROUND(r.total_points - pa.avg_pts, 1) AS value_score
        FROM draft_picks d
        JOIN roster_players r ON d.player_id = r.player_id AND d.year = r.year
        JOIN pos_avg pa ON pa.year = d.year AND pa.position = d.position
        WHERE d.round >= 5 AND r.total_points > 0
        ORDER BY value_score DESC
        LIMIT 20
    """).fetchall()

    # Biggest busts: drafted in rounds 1-2 but scored well below their position avg
    busts = conn.execute("""
        WITH pos_avg AS (
            SELECT r.year, d.position, AVG(r.total_points) AS avg_pts
            FROM draft_picks d
            JOIN roster_players r ON d.player_id = r.player_id AND d.year = r.year
            WHERE r.total_points > 0
            GROUP BY r.year, d.position
        )
        SELECT d.overall_pick, d.round, d.round_pick, d.player_name,
               d.position, d.nfl_team, d.team_owner, d.year, r.total_points,
               ROUND(r.total_points - pa.avg_pts, 1) AS value_score
        FROM draft_picks d
        JOIN roster_players r ON d.player_id = r.player_id AND d.year = r.year
        JOIN pos_avg pa ON pa.year = d.year AND pa.position = d.position
        WHERE d.round <= 2 AND r.total_points > 0
        ORDER BY value_score ASC
        LIMIT 20
    """).fetchall()

    # Per-round average points (for the chart reference line)
    round_avgs = conn.execute("""
        SELECT d.round, ROUND(AVG(r.total_points), 1) AS avg_pts, COUNT(*) AS picks
        FROM draft_picks d
        JOIN roster_players r ON d.player_id = r.player_id AND d.year = r.year
        WHERE d.round > 0 AND r.total_points > 0
        GROUP BY d.round
        ORDER BY d.round
    """).fetchall()

    # Average final standings position for each round-1 pick slot
    pick1_finish = conn.execute("""
        SELECT d.round_pick,
               ROUND(AVG(t.final_standing), 2) AS avg_finish,
               COUNT(*) AS seasons
        FROM draft_picks d
        JOIN teams t ON t.year = d.year AND t.owner = d.team_owner
        WHERE d.round = 1 AND t.final_standing > 0
        GROUP BY d.round_pick
        ORDER BY d.round_pick
    """).fetchall()

    conn.close()
    return render_template("draft.html",
        league_name=LEAGUE_NAME,
        best_value=best_value,
        busts=busts,
        round_avgs=round_avgs,
        pick1_finish=[dict(r) for r in pick1_finish],
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


@app.route("/api/chart/draft-value")
def chart_draft_value():
    conn = get_db()
    rows = conn.execute("""
        SELECT d.overall_pick, d.player_name, d.position, d.team_owner,
               d.year, d.round, r.total_points
        FROM draft_picks d
        JOIN roster_players r ON d.player_id = r.player_id AND d.year = r.year
        WHERE d.overall_pick > 0 AND r.total_points > 0
        ORDER BY d.overall_pick
    """).fetchall()
    conn.close()

    pos_colors = {
        "QB":  "rgba(54,  162, 235, 0.75)",
        "RB":  "rgba(75,  192, 100, 0.75)",
        "WR":  "rgba(255, 206,  86, 0.75)",
        "TE":  "rgba(255, 100,  64, 0.75)",
        "K":   "rgba(153, 102, 255, 0.75)",
        "DST": "rgba(201, 203, 207, 0.75)",
    }

    # Group points by position for separate scatter datasets
    by_pos = {}
    for r in rows:
        pos = r["position"] if r["position"] in pos_colors else "UNK"
        by_pos.setdefault(pos, []).append({
            "x":      r["overall_pick"],
            "y":      round(r["total_points"], 1),
            # Extra fields surfaced in tooltip via custom plugin
            "player": r["player_name"],
            "owner":  r["team_owner"],
            "year":   r["year"],
            "round":  r["round"],
        })

    datasets = []
    for pos, color in pos_colors.items():
        if pos not in by_pos:
            continue
        datasets.append({
            "label":           pos,
            "data":            by_pos[pos],
            "backgroundColor": color,
            "pointRadius":     5,
            "pointHoverRadius": 8,
        })

    return jsonify({"datasets": datasets})


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    # use_reloader=False prevents Werkzeug from killing background import threads
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)
