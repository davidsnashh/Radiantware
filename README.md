# Radiantware Valorant-TRN-MCP

An MCP server that gives LLM reasoning access to structured Valorant statistics, scraped from
[tracker.gg](https://tracker.gg/valorant).


>All statistics belong to **Tracker Network (TRN)**, who get full credit for them.

## Quick start

From a Mac with nothing set up to asking Claude about your matches. It has
only been tested on macOS.

1. Install [uv](https://docs.astral.sh/uv/). It brings Python with it, and
   Claude Desktop uses it to install what the server needs:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Install [Google Chrome](https://www.google.com/chrome/) and
   [Claude Desktop](https://claude.ai/download), then open Claude Desktop and
   sign in.

3. Download the project and go into its folder:

   ```bash
   git clone https://github.com/davidsnashh/Radiantware.git
   cd Radiantware
   ```

   Without git, choose **Code**, then **Download ZIP** on the GitHub page,
   unzip it and open a terminal in the unzipped folder.

4. Pack the server into one file. Claude Desktop installs an extension from a
   single `.mcpb` file, which is a zip of the server's code plus
   `manifest.json`, the file that tells Claude Desktop how to start it. Make
   that file by running these two lines in the project folder:

   ```bash
   rm -f valorant-trn-stats.mcpb
   zip -rXD valorant-trn-stats.mcpb manifest.json pyproject.toml uv.lock README.md *.py cache scraper -x '*/__pycache__/*' '*.DS_Store'
   ```

   - The first line deletes an older `valorant-trn-stats.mcpb`, so that
     nothing stale stays in it. The first time there is nothing to delete.
   - The second line zips what the server needs: the manifest, the two files
     that list its Python packages, the code and this README. `cache` and
     `scraper` are code folders. Your settings (`.env`), the downloaded data
     (`.data`) and the tests are left out.
   - The part after `-x` skips leftover files that Python and macOS create.

   It prints one "adding" line per file. When it is done,
   `valorant-trn-stats.mcpb` is in the project folder.

5. Double-click `valorant-trn-stats.mcpb`, or run `open valorant-trn-stats.mcpb`.
   Claude Desktop shows an install screen. Click **Install** and give it a
   minute or two to fetch the Python packages.

6. Start a new chat and ask, for example: "My Riot ID is Name#TAG. What's my
   rank and K/D this act?" Allow the tool when Claude asks. The first answer
   is slower than the later ones, because Chrome has to start in the
   background.

It stays installed, so from then on just open Claude Desktop and ask. After
updating or changing the code, repeat steps 4 and 5. Details are under
[Claude Desktop bundle](#claude-desktop-bundle). Other clients are under
[Connecting an MCP client](#connecting-an-mcp-client).

## What it does

Tracker.gg has no public Valorant API, and Riot's official API is not usable
for this. The server therefore drives a real browser session, reads the same
JSON the tracker.gg profile pages load, and exposes it as MCP tools with a
SQLite cache in front. The host LLM combines the tools to answer questions
such as:

- "Which of my 5 most played teammates has the lowest KD on Split?"
- "Who has the highest ACS when I play with them on Ascent?"
- "Show me my win rate when playing with X vs without X."
- "Which of my 5 most played teammates dies first the most?"
- "Who on my team baits the most?"
- "Am I better on attack or defense on Lotus?"
- "How often do we win a round after getting the first kill?"
- "Walk me through round 12 of my last match."
- "Who have I played with the most in the last few months, and do I do better solo or in a five-stack?"
- "Is my K/D going up or down this month, and what was my best game ever?"
- "What share of players is my rank in the top of?"
- "Which agent should I pick on Bind this act?"

## Tools

| Tool | Returns |
| --- | --- |
| `get_player_overview(riot_id, playlist, season, include_career, detailed, force_refresh)` | Rank, peak rank, K/D, HS%, ADR, ACS, win rate, matches, KAST and more for one act, percentiles, and career totals |
| `get_player_agents(riot_id, playlist, season, agents, detailed, force_refresh)` | Per-agent stats with each agent's most played maps, plus totals per role |
| `get_player_maps(riot_id, playlist, season, maps, detailed, force_refresh)` | Per-map stats with attack/defense numbers and top agents |
| `get_player_weapons(riot_id, playlist, season, force_refresh)` | Per-weapon kills, deaths, headshot rate, damage and kill distance |
| `get_recent_matches(riot_id, limit, playlist, include_opponents, detailed, skip, map_name, agent, season, force_refresh)` | Match history with the player's line and every teammate's line |
| `get_match_details(match_id_or_url, detailed)` | Full scoreboard: both teams, all ten players |
| `get_match_rounds(match_id_or_url, rounds, riot_id, detailed)` | One match round by round: result, economy, plant and defuse, and every kill in order |
| `get_round_stats(riot_id, map_name, agent, limit_matches, playlist)` | How rounds go for the player's team over recent matches: by side, after a plant, on pistol rounds, after the first kill, by buy |
| `get_teammate_stats(riot_id, map_name, agent, limit_matches, playlist, top, detailed)` | Teammates in the matches analysed, their stats, per-map breakdown, and your record with and without each |
| `get_top_teammates(riot_id, playlist)` | Tracker.gg's own list of the most played teammates over the last months, and the player's record by party size |
| `get_daily_stats(riot_id, playlist, days)` | Day-by-day matches, wins, K/D, ADR and placement |
| `get_stat_history(riot_id, stat, playlist)` | One stat day by day for about a month, and the ten best matches for it |
| `get_rank_distribution(region, season)` | Share of ranked players per rank, and which top percent each rank is |
| `get_leaderboard(region, season, start_rank, limit)` | The ranked leaderboard of a region |
| `get_meta_insights()` | Agent tier list, pick and win rates, and map numbers across all tracked matches |
| `get_premier_team(riot_id, roster_id, detailed)` | A Premier team: standing, players, stages and recent matches |
| `get_game_data(kind)` | Reference lists: agents, maps, weapons, acts, playlists |
| `search_player(query)` | Riot IDs matching a name |

Every tool returns a JSON object. Responses carry `source`, `cached` (false
when anything had to be scraped for this answer), `fetched_at` and, when
something degraded, `warnings`. Percentages are on a 0-100 scale. `season`
accepts `current`, `all`, or an act such as `E26: A5`. The rank distribution
and the leaderboard are per act, so they take `current` or an act, not `all`.

### Headline numbers and the full sheet

Tracker.gg sends far more than fits in a readable answer, so most tools
return the headline numbers by default and the full stat sheet with
`detailed=true`. Asking for detail costs no extra requests, only a longer
answer. Fields tracker.gg has no value for are left out.

| Tool | `detailed=true` adds |
| --- | --- |
| `get_player_overview`, `get_player_agents`, `get_player_maps` | The whole stat sheet: attack and defense blocks, clutches won and lost by size, multi-kills, trades, rounds survived, last deaths, entry success, plants, defuses, econ rating, ability casts, shots dealt and received by body part, flawless and thrifty rounds. Agents also get the name and casts of each ability, and every top map or top agent gets its K/D, ACS, ADR, HS% and KAST |
| `get_match_details` | Per player: attack and defense blocks, their rounds by buy type, kills per weapon, duels against each opponent and the parts of the performance score. For the match: a log of every round |
| `get_recent_matches` | The whole scoreboard line for the player and every teammate, for at most eight matches per call |
| `get_match_rounds` | Per kill: the assists, the distance, whether it was alternate fire and where both players stood on the minimap. Per plant and defuse: where it happened. Per round: the line of all ten players |
| `get_teammate_stats` | Per teammate: attack and defense blocks, rounds by buy type, kills per weapon, tracker.gg's match labels |

`get_match_details` and `get_teammate_stats` already include clutches,
multi-kills, trades, survival, economy and ability casts without it. A
detailed agent or map table is limited to the five most played unless you
name the rows you want (`agents=["Jett"]`, `maps=["Split"]`).

MCP clients reject or cut off very long answers, so a list that would run
past roughly 18,000 tokens is shortened and a `note` in the answer says so.
For the match history the note gives the `skip` value that continues where
the answer stopped.

### Tracker.gg's own totals

Besides profiles and scoreboards, tracker.gg keeps totals of its own, and a
few tools read those directly. Each costs one request.

- `get_top_teammates`: the up to twenty most played teammates over tracker.gg's
  recent window (a few months, the answer says which days), with the record
  together and the teammate's own K/D and average placement in those matches,
  plus the player's record by party size. This covers hundreds of matches,
  where `get_teammate_stats` reads scoreboards one at a time but knows every
  stat. `get_teammate_stats` marks each teammate with `most_played_rank`,
  their place on this list.
- `get_daily_stats`: one line per day played.
- `get_stat_history`: one stat day by day for about the last month, and the
  ten best matches for it from any act, each with the value it reached.
  `stat="rank"` gives the rank history over about three months, which
  tracker.gg only keeps for Immortal and Radiant players. Its days are UTC
  days, while `get_daily_stats` goes by this computer's time zone, so the two
  can put an evening match on different dates.

`map_name`, `agent` and (for the history) `season` filter on tracker.gg's
side. So `get_teammate_stats(map_name="Split", limit_matches=30)` analyses the
last thirty matches on Split, not the Split matches among the last thirty.

The rest is not about one player: `get_rank_distribution` and
`get_leaderboard` per region and act, `get_meta_insights` for agents and maps
across all tracked matches, `get_premier_team` for a Premier roster, and
`get_game_data` for the reference lists.

### Round by round

Every scoreboard comes with the match's rounds, and the server keeps them:
who attacked, how the round ended, the spike plant and defuse, what each
player bought and did, and every kill with its time, weapon and position.

- `get_match_rounds` returns that for one match. Pass `riot_id` to follow one
  player through it, `rounds=[1, 13]` to look at particular rounds, and
  `detailed=true` for positions, assists and all ten players' lines.
- `get_round_stats` adds the rounds of many matches up into patterns: round
  win rate by side, with and without the spike planted and per site (on
  defense that is the retake rate), pistol rounds and the round after, rounds
  in which the team got or lost the first kill, both teams' buy, how rounds
  ended, and the player's own opening duels, fight timing and range.

A team's buy in a round is the type most of its five players were on. Kills
inside a team and suicides stay in the round log, since they happened, but
are not counted as kills anywhere else. A player who was not in the game for
a round is marked `away` in it and has no buy.

### Stat names

The same names are used in every tool.

| Name | Meaning |
| --- | --- |
| `acs`, `adr` | Combat score and damage per round |
| `kast` | Share of rounds with a kill, assist, survival or trade |
| `damage_delta_per_round` | Damage dealt minus damage taken, per round |
| `first_kills`, `first_deaths` | Rounds in which the player got the first kill, or was the first of all ten to die |
| `team_first_deaths` | Rounds in which the player was the first of their own team to die |
| `entry_success_rate` | First kills as a share of the rounds the player opened, either way |
| `rounds`, `rounds_survived`, `last_deaths` | Rounds played, rounds survived, and rounds in which the player was the last one to die |
| `deaths_traded`, `trade_kills` | Deaths a teammate avenged, and kills that avenged a teammate |
| `clutches`, `clutches_lost`, `clutches_by_size` | Rounds won or lost as the last one alive, and wins by the number of opponents left (`1v1` to `1v5`) |
| `multi_kills` | Rounds with three or more kills |
| `double_kills`, `triple_kills`, `quadra_kills` | Rounds with exactly two, three and four kills |
| `aces` | Rounds with five kills on a scoreboard. On profile rows it is tracker.gg's own ace count, which can be lower than its five-kill rounds |
| `shots_dealt`, `shots_received` | Hits by body part (`head`, `body`, `leg`). `hs_pct` is the head share of the hits dealt |
| `econ_rating` | Damage per 1000 credits spent |
| `avg_loadout_value`, `credits_spent` | Average worth of the loadout per round, and credits spent in the match |
| `ability_casts` | Ability uses by slot: `c`, `q`, `e` and `x` |
| `tracker_score` | Tracker.gg's rating out of 1000 |
| `performance_score`, `performance_rank` | Tracker.gg's performance number for a match and the position among the ten players by it |
| `performance_grade`, `performance_parts` | Tracker.gg's grade for that number (pass, merit or distinction) and the parts it is made of |
| `avg_placement` | The average `performance_rank` over a set of matches, 1 being best |
| `duels` | Per opponent in a match: kills, deaths and damage both ways |
| `attack`, `defense` | The player's numbers on one side |
| `buys`, `buy` | The player's rounds by tracker.gg's buy type. `pistol` is the first round of a half. Otherwise it goes by credits spent in the round: `eco` up to 1000, `semi` up to 3850, `full` from 3900 |
| `killer_at`, `victim_at` | Minimap positions as `[x, y]`, each from 0 at the top left to 1 |
| `first_kill_rate`, `first_death_rate`, `team_first_death_rate`, `survival_rate` | In teammate stats: the count as a percentage of the rounds played together |
| `deaths_traded_rate`, `clutch_win_rate` | In teammate stats: the share of deaths that a teammate avenged, and the share of clutch situations won |

## Requirements

- Python 3.11 or newer
- Google Chrome, or the Chromium build that patchright can download
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Node.js, only for the MCP Inspector (`mcp dev`)

## Installation

```bash
# with uv
uv sync

# or with pip
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

The server uses your installed Google Chrome by default. On a Mac that
includes a copy in your own Applications folder and one that Finder named
"Google Chrome 2". Without Chrome, install the bundled Chromium, which is
picked up automatically:

```bash
uv run patchright install chromium
```

If Chrome lives somewhere else, set `TRN_BROWSER_EXECUTABLE` to the binary's
full path.

## Running

```bash
# MCP Inspector, for trying the tools by hand
uv run mcp dev server.py

# stdio (what desktop clients use)
uv run server.py

# streamable HTTP on http://127.0.0.1:8000/mcp
uv run server.py --transport streamable-http --port 8000
```

### Connecting an MCP client

Clients that are configured through an `mcpServers` JSON block take:

```json
{
  "mcpServers": {
    "valorant-trn-stats": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/this/project", "run", "server.py"]
    }
  }
}
```

Clients that register servers on the command line take the same command:
`uv --directory /absolute/path/to/this/project run server.py`.

Several copies of the server can run at the same time, which is what happens
when a client starts one copy per window. Copies that use the same data folder
act like one visitor: they share the cache, make one request at a time between
them and count against the same hourly budget. Each copy that has a browser
open at that moment uses a browser profile of its own, up to three. Copies
with different data folders know nothing of each other.

### Claude Desktop bundle

`manifest.json` describes the server as a Claude Desktop extension.
[Quick start](#quick-start) has the command that packs it into one file and
the steps to install it.

Claude Desktop installs the dependencies itself with uv, so the file holds
only the source. It is a copy: after changing the code, pack and install it
again.

- Settings do not come from `.env`. The Chrome path and whether the browser
  window is hidden are set in the extension's settings in Claude Desktop. Both
  can be left as they are.
- Data goes to `~/.valorant-trn-mcp` instead of `.data`, so it survives
  installing a newer bundle.
- Claude Desktop starts two copies of the server. They share that folder, so
  they take turns and count as one visitor.
- The official packer, `npx @anthropic-ai/mcpb pack . valorant-trn-stats.mcpb`,
  can be used instead. `.mcpbignore` keeps local data and the virtual
  environment out of its output.
- The bundle is for your own machine. Do not share it.

## Configuration

Copy `.env.example` to `.env`. Everything is optional.

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRN_HEADLESS` | `true` | Run the browser without a window |
| `TRN_BROWSER_CHANNEL` | `chrome` | `chrome`, `msedge` or `chromium` (bundled). Chromium is the automatic fallback |
| `TRN_BROWSER_EXECUTABLE` | | Full path to a Chrome binary |
| `TRN_USER_AGENT` | | Override the user agent. Leave empty |
| `TRN_BROWSER_IDLE_SECONDS` | `120` | Close the browser after this long without requests. `0` keeps it open |
| `TRN_MIN_DELAY` / `TRN_MAX_DELAY` | `1.5` / `4.0` | Random pause between requests, in seconds |
| `TRN_MAX_CONCURRENT_SCRAPES` | `1` | Requests in flight at once, `1` or `2`. Keep it at `1` |
| `TRN_MAX_REQUESTS_PER_HOUR` | `240` | Hourly request cap, shared by the copies that use one data folder. `0` disables it |
| `TRN_MAX_RETRIES` | `2` | Retries for transient failures, `0` to `3`, with exponential backoff |
| `TRN_BACKOFF_BASE` | `2.0` | First backoff delay, in seconds |
| `TRN_REQUEST_TIMEOUT` | `30` | Seconds to wait for one response |
| `TRN_CHALLENGE_TIMEOUT` | `30` | Seconds to wait for a Cloudflare challenge to clear |
| `TRN_CACHE_TTL_OVERVIEW` | `2700` | Profile and overview stats, stat history, Premier teams |
| `TRN_CACHE_TTL_AGENTS` / `TRN_CACHE_TTL_MAPS` | `5400` | Agent, role and weapon tables / map table |
| `TRN_CACHE_TTL_MATCHES` | `1200` | Match history list, top teammates and daily stats |
| `TRN_CACHE_TTL_CAREER` | `21600` | All-act totals, rank distribution, insights |
| `TRN_CACHE_TTL_SEARCH` | `3600` | Search results, leaderboards |
| `TRN_CACHE_TTL_MATCH_DETAILS` | `2592000` | Scoreboards (finished matches never change) |
| `FLARESOLVERR_URL` | | FlareSolverr endpoint, used as a fallback |
| `TRN_BACKEND` | `playwright` | Set to `flaresolverr` to make it the primary |
| `TRN_FLARESOLVERR_TIMEOUT_MS` | `60000` | FlareSolverr challenge timeout |
| `TRN_DATA_DIR` | `.data` | SQLite cache, browser profiles and the pacing shared between copies |
| `TRN_LOG_LEVEL` | `INFO` | Logs go to stderr |
| `MCP_TRANSPORT` / `MCP_HOST` / `MCP_PORT` | `stdio` / `127.0.0.1` / `8000` | Transport defaults |

## Example tool calls

```jsonc
// Current rank, peak rank and headline stats, plus career totals
{"tool": "get_player_overview", "arguments": {"riot_id": "Player#NA1"}}

// Lifetime agent stats in unrated
{"tool": "get_player_agents", "arguments": {"riot_id": "Player#NA1", "playlist": "unrated", "season": "all"}}

// Last 20 competitive matches with teammates
{"tool": "get_recent_matches", "arguments": {"riot_id": "Player#NA1", "limit": 20}}

// One scoreboard, by URL or ID
{"tool": "get_match_details", "arguments": {"match_id_or_url": "https://tracker.gg/valorant/match/<match-id>"}}

// Most played teammates over 50 matches, with their numbers on Split
{"tool": "get_teammate_stats", "arguments": {"riot_id": "Player#NA1", "map_name": "Split", "limit_matches": 50}}

// The five most played teammates with attack/defense, buy-type and weapon breakdowns
{"tool": "get_teammate_stats", "arguments": {"riot_id": "Player#NA1", "top": 5, "detailed": true}}

// The full stat sheet for one agent, lifetime
{"tool": "get_player_agents", "arguments": {"riot_id": "Player#NA1", "season": "all", "agents": ["Jett"], "detailed": true}}

// Kills, headshot rate and kill distance per weapon
{"tool": "get_player_weapons", "arguments": {"riot_id": "Player#NA1"}}

// One match round by round, following one player
{"tool": "get_match_rounds", "arguments": {"match_id_or_url": "<match-id>", "riot_id": "Player#NA1"}}

// Rounds 1 and 13 with positions and all ten players
{"tool": "get_match_rounds", "arguments": {"match_id_or_url": "<match-id>", "rounds": [1, 13], "detailed": true}}

// Round patterns over the last 40 matches on Split
{"tool": "get_round_stats", "arguments": {"riot_id": "Player#NA1", "map_name": "Split", "limit_matches": 40}}

// The most played teammates of the last months, and the record by party size
{"tool": "get_top_teammates", "arguments": {"riot_id": "Player#NA1"}}

// Headshot rate day by day, and the ten best matches for it
{"tool": "get_stat_history", "arguments": {"riot_id": "Player#NA1", "stat": "hs_pct"}}

// The last ten matches on Jett on Ascent
{"tool": "get_recent_matches", "arguments": {"riot_id": "Player#NA1", "limit": 10, "agent": "Jett", "map_name": "Ascent"}}

// Which top percent each rank is in Europe
{"tool": "get_rank_distribution", "arguments": {"region": "eu"}}

// Find a tagline
{"tool": "search_player", "arguments": {"query": "Player"}}
```

Riot IDs are accepted as `Name#TAG`, with stray spaces, URL-encoded
(`Name%23TAG`), or as a full tracker.gg profile URL.

For the Split question above, `get_teammate_stats` with `map_name="Split"`
analyses the most recent matches on Split, and every teammate in them carries
`most_played_rank`, their place among the player's most played teammates of
the last months. The answer is the lowest `kd` among those ranked 1 to 5.

For "who dies first the most", compare `first_death_rate`: the percentage of
rounds played together in which that teammate was the first of all ten players
to die. `team_first_death_rate` counts being the first of their own team to
die instead. Compare teammates by rates and averages rather than totals, since
they played different numbers of games with you.

## How it works

### Cloudflare

Tracker.gg sits behind Cloudflare. What was observed while building this:

- Plain HTTP clients get a 403 challenge page.
- Navigating a browser straight to a data endpoint is challenged too.
- The same endpoint answers normally when the request is made by a page on
  tracker.gg in a real Chrome session, which is what the site itself does.

So the server opens one tiny document on tracker.gg in a persistent Chrome
profile and issues `fetch()` calls from it. No profile page is ever rendered,
which also means no ads or analytics are loaded on your behalf.

Browser automation goes through [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python),
a drop-in Playwright build without the usual automation fingerprints (plain
Playwright is used if patchright is not installed). Headless Chrome is only
challenged because its user agent says `HeadlessChrome`, so the server reads
the real user agent once and relaunches with that word removed.

If a challenge appears anyway, the server loads a normal tracker.gg page and
waits up to `TRN_CHALLENGE_TIMEOUT` for it to clear. If it does not:

1. FlareSolverr is tried when `FLARESOLVERR_URL` is set.
2. Otherwise the tool fails with a message that says what happened.

A block is never retried. The blocked backend is left alone for five minutes,
during which calls fail fast (or go straight to the fallback) instead of
knocking again. Setting `TRN_HEADLESS=false` shows the browser, which passes
more easily and lets you solve a challenge by hand. The clearance is stored in
the profile under `TRN_DATA_DIR`.

### FlareSolverr (optional)

```bash
docker run -d --name flaresolverr -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest
```

```env
FLARESOLVERR_URL=http://localhost:8191
```

Any proxy that speaks the FlareSolverr `/v1` API works. It is slower than the
built-in browser (about ten seconds for the first request) and is only used
when the browser is blocked or unavailable, unless `TRN_BACKEND=flaresolverr`.

### Rate limiting

The scraper is slow on purpose:

- one request at a time, also between copies that share a data folder
- a random 1.5 to 4 second pause after every request
- at most 240 requests per hour, counted across those copies
- two retries with exponential backoff for timeouts and server errors, a
  longer wait after a rate-limit response, and no retry at all after a
  Cloudflare block
- tool calls that overlap share one scrape instead of each making their own

With `TRN_MAX_CONCURRENT_SCRAPES=2` the pause is measured between the starts
of two requests rather than after each one finishes, and copies stop waiting
for each other's requests to end. The browser handles one request at a time
either way, so there is nothing to gain from it.

Approximate cost of a call on a cold cache:

| Call | Requests |
| --- | --- |
| `get_player_overview` | 1, plus 1 for career totals |
| `get_player_agents` | 0 after an overview, otherwise 1 to 2 |
| `get_player_maps`, `get_player_weapons` | 1 after an overview, otherwise 2. The second of the two is free |
| `get_recent_matches`, `get_round_stats` | 1 per 20 matches, plus 1 per match not seen before |
| `get_teammate_stats` | The same, plus 1 for the most-played list it shares with `get_top_teammates` |
| `get_match_details`, `get_match_rounds`, `search_player` | 1 |
| `get_top_teammates`, `get_daily_stats` | 1 for the two together |
| `get_stat_history`, `get_leaderboard`, `get_rank_distribution` | 1 |
| `get_meta_insights` | 2 |
| `get_premier_team` | 1, plus 1 to look the team up from a player |
| `get_game_data`, and the first use of a map, agent or act filter | 1, then nothing for a week. They are fetched again sooner when the act ends or a name is not on them |

Scoreboards dominate. Twenty new matches take roughly a minute, after which
they are served from the cache for 30 days. If your MCP client gives up on a
long call, run it again: everything fetched so far has been kept.

### Caching

Results live in `TRN_DATA_DIR/cache.sqlite3`, keyed by tool, Riot ID and
parameters, each with its own TTL. One scrape fills the cache for related
tools (the profile response also feeds the agent table, for example). When
tracker.gg cannot be reached, an expired entry is returned with a warning
instead of an error. Pass `force_refresh=true` to bypass the cache, and delete
the file to clear it.

### Private and missing profiles

- An unknown Riot ID fails with "Tracker.gg could not find Name#TAG".
- A private profile fails with a message explaining that its owner has to sign
  in at tracker.gg and make it public. The server recognises this the same way
  the site's own frontend does (HTTP 451 or 403, or an error code containing
  `Private`).

Players with private profiles still appear in the scoreboards of public
players, so teammate analysis covers them.

## Limitations

- Rank rating (RR) is only available for Immortal and Radiant players.
  Tracker.gg does not have it for lower ranks.
- On scoreboards tracker.gg divides its per-round defense numbers by the
  wrong round count, so the server rebuilds the per-side ACS, ADR, round win
  rate and damage delta from the round data. A scoreboard that comes without
  round data has no such numbers, nor buy types, weapon kills or round log.
- Act and career totals are tracker.gg's own aggregates and can be a few off
  their breakdowns (clutches by size, kills per side).
- Kill distances assume the game's units are centimetres.
- Positions are minimap coordinates. Tracker.gg does not name the place, so
  nothing here says "A Main" or "Heaven". Only spike plants carry a site.
- The spending limits behind the buy types are not published. The ones used
  here reproduce tracker.gg's own counts on every match tested.
- Modes without rounds, such as deathmatch, have no round data.
- Tracker.gg's own totals reach back a few months, not to the start of an act,
  and list at most twenty teammates. They cannot be narrowed to an act or a map.
- `get_meta_insights` is one set of numbers for everyone. Tracker.gg's rank and
  map filters for it did not respond to anything tried.
- Rank history exists for Immortal and Radiant players only.
- Premier schedules and Premier leaderboards did not answer without more
  parameters than could be found, so only teams are covered.
- Personal details tracker.gg shows next to stats (country, linked social
  accounts, site membership) are left out on purpose.
- A stored match takes about 80 KB in the cache with its rounds.
- MVPs, trade kills, thrifty rounds, the tracker score and damage taken per
  weapon exist per act only, so all-act results leave them out.
- Tracker.gg has no kills per ability. Kills made with an ability show up in
  `weapon_kills` on scoreboards and in the weapon table.
- Buy-type rows are tracker.gg's own and count a kill on a teammate as a
  kill, unlike every other number here. They also carry no headshot rate.
- "Current" means the act tracker.gg shows by default for that player.
- Private-profile handling could not be exercised against a real private
  profile, since none turned up during testing.
- Console playlists are passed through but untested.
- Tracker.gg changes its site from time to time. If parsing breaks, the
  response shapes are all handled in `scraper/parsers.py`.

Last verified against tracker.gg on 18 November 2026.

## Project layout

```
server.py              MCP server and tools
analysis.py            Teammate aggregation
models.py              Pydantic models for scraped data
config.py              Settings (environment / .env)
manifest.json          Claude Desktop bundle description
scraper/
  trn.py               Browser session, FlareSolverr client, pacing, retries
  locks.py             File locks shared between copies of the server
  parsers.py           Tracker.gg JSON (or HTML-wrapped JSON) to models
  utils.py             Riot ID parsing, playlist names, URL building
  exceptions.py        Error types
cache/
  sqlite_cache.py      SQLite cache with per-entry TTLs
tests/                 Offline tests on made-up sample data
```

## Tests

```bash
uv run --with pytest pytest
```

The tests are offline. They run on made-up sample data and never contact
tracker.gg.

## Disclaimer

This is an unofficial personal tool. It is not affiliated with, endorsed by or
supported by Tracker Network or Riot Games. Tracker.gg's terms of service and
`robots.txt` do not allow automated collection of profile and match pages in
general. This project relies on a personal-use permission from Tracker
Network's owner and is deliberately kept to low volumes. Do not raise the rate
limits, do not run it for other people, and stop using it if that permission
is withdrawn.

Valorant is a trademark of Riot Games, Inc.
