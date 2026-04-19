# =============================================================
#  RyanFFB League Configuration — edit these values first!
# =============================================================

# Your ESPN league ID (the number in the URL when viewing your league)
# e.g. fantasy.espn.com/football/league?leagueId=123456
LEAGUE_ID = 764891

# First season of your league
START_YEAR = 2014

# Most recent completed season (update each year)
CURRENT_YEAR = 2025

# Display name for the site
LEAGUE_NAME = "RyanFFB Fantasy Football"

# -----------------------------------------------------------
# Private league credentials (leave as None for public leagues)
# -----------------------------------------------------------
# To find these cookies:
#   1. Log into ESPN on your browser
#   2. Open DevTools (F12) → Application → Cookies → espn.com
#   3. Copy the values for 'espn_s2' and 'SWID'
ESPN_S2 = None   # e.g. "AEB3Xxxxxx..."
SWID    = None   # e.g. "{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}"

# -----------------------------------------------------------
# Internal settings — no need to change these
# -----------------------------------------------------------
DATABASE_PATH = "data/league.db"
