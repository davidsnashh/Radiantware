# valorant-trn-mcp

An MCP server that gives an LLM structured Valorant statistics, scraped from
[tracker.gg](https://tracker.gg/valorant).

> **Personal use only. Not for sale.**
> This project must never be sold, marketed, published or offered as a public
> service, and it must never be presented as an original data source. All
> statistics belong to **Tracker Network (TRN)**, who get full credit for them.
> It exists under a personal-use permission from Tracker Network's owner. If
> you do not have that permission yourself, do not run it.

## What it does

Tracker.gg has no public Valorant API, and Riot's official API is not usable
for this. The server therefore drives a real browser session, reads the same
JSON the tracker.gg profile pages load, and exposes it as MCP tools with a
SQLite cache in front. The host LLM combines the tools to answer questions
such as:

- "Which of my 5 most played teammates has the lowest KD on Split?"
- "Who has the highest ACS when I play with them on Ascent?"
- "Show me my win rate when playing with X vs without X."
- "Which agent should I pick on Bind this act?"

## Tools

| Tool | Returns |
| --- | --- |
| `get_player_overview(riot_id, playlist, season, include_career, force_refresh)` | Rank, peak rank, K/D, HS%, ADR, ACS, win rate, matches, KAST and more for one act, percentiles, and career totals |
| `get_player_agents(riot_id, playlist, season, force_refresh)` | Per-agent stats with each agent's most played maps |
| `get_player_maps(riot_id, playlist, season, force_refresh)` | Per-map stats with attack/defense splits and top agents |
| `get_recent_matches(riot_id, limit, playlist, include_opponents, force_refresh)` | Match history with the player's line and every teammate's line |
| `get_match_details(match_id_or_url)` | Full scoreboard: both teams, all ten players |
| `get_teammate_stats(riot_id, map_name, limit_matches, playlist, top)` | Most played teammates, their stats, per-map breakdown, and your record with and without each |
| `search_player(query)` | Riot IDs matching a name |

Every tool returns a JSON object. Responses carry `source`, `cached`,
`fetched_at` and, when something degraded, `warnings`. Percentages are on a
0-100 scale. `season` accepts `current`, `all`, or an act such as `E26: A5`.

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

The server uses your installed Google Chrome by default. Without Chrome,
install the bundled Chromium, which is picked up automatically:

```bash
uv run patchright install chromium
```

If Chrome lives in a non-standard location, set `TRN_BROWSER_EXECUTABLE` to
the binary's full path.

## Running

```bash
# MCP Inspector, for trying the tools by hand
uv run mcp dev server.py

# stdio (what desktop clients use)
uv run server.py

# streamable HTTP on http://127.0.0.1:8000/mcp
uv run server.py --transport streamable-http --port 8000
```

### Claude Desktop

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

### Claude Code

```bash
claude mcp add valorant-trn-stats -- uv --directory /absolute/path/to/this/project run server.py
```

Run a single copy of the server. The browser profile can only be used by one
process at a time, and one process is also what keeps the request pacing
honest. To share it between several clients, start it once with
`--transport streamable-http` and point them all at that URL.

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
| `TRN_MAX_CONCURRENT_SCRAPES` | `1` | Requests in flight at once |
| `TRN_MAX_REQUESTS_PER_HOUR` | `240` | Hard hourly cap. `0` disables it |
| `TRN_MAX_RETRIES` | `2` | Retries for transient failures, with exponential backoff |
| `TRN_BACKOFF_BASE` | `2.0` | First backoff delay, in seconds |
| `TRN_REQUEST_TIMEOUT` | `30` | Seconds to wait for one response |
| `TRN_CHALLENGE_TIMEOUT` | `30` | Seconds to wait for a Cloudflare challenge to clear |
| `TRN_CACHE_TTL_OVERVIEW` | `2700` | Profile and overview stats |
| `TRN_CACHE_TTL_AGENTS` / `TRN_CACHE_TTL_MAPS` | `5400` | Agent and map tables |
| `TRN_CACHE_TTL_MATCHES` | `1200` | Match history list |
| `TRN_CACHE_TTL_CAREER` | `21600` | All-act totals |
| `TRN_CACHE_TTL_SEARCH` | `3600` | Search results |
| `TRN_CACHE_TTL_MATCH_DETAILS` | `2592000` | Scoreboards (finished matches never change) |
| `FLARESOLVERR_URL` | | FlareSolverr endpoint, used as a fallback |
| `TRN_BACKEND` | `playwright` | Set to `flaresolverr` to make it the primary |
| `TRN_FLARESOLVERR_TIMEOUT_MS` | `60000` | FlareSolverr challenge timeout |
| `TRN_DATA_DIR` | `.data` | SQLite cache and browser profile |
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

// Find a tagline
{"tool": "search_player", "arguments": {"query": "Player"}}
```

Riot IDs are accepted as `Name#TAG`, with stray spaces, URL-encoded
(`Name%23TAG`), or as a full tracker.gg profile URL.

For the Split question above, `get_teammate_stats` ranks teammates by games
played together across all analysed matches (`rank`), and with `map_name` adds
an `on_map` block to each. The answer is the lowest `on_map.kd` among ranks 1
to 5.

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
2. Otherwise the tool fails with a message that says so. It does not retry a
   block. Setting `TRN_HEADLESS=false` shows the browser, which passes more
   easily and lets you solve a challenge by hand. The clearance is stored in
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

- one request at a time
- a random 1.5 to 4 second pause after every request
- at most 240 requests per hour
- two retries with exponential backoff for timeouts and server errors, a
  longer wait after a rate-limit response, and no retry at all after a
  Cloudflare block

Approximate cost of a call on a cold cache:

| Call | Requests |
| --- | --- |
| `get_player_overview` | 1, plus 1 for career totals |
| `get_player_agents` | 0 after an overview, otherwise 1 to 2 |
| `get_player_maps` | 1 |
| `get_recent_matches`, `get_teammate_stats` | 1 per 20 matches, plus 1 per match not seen before |
| `get_match_details`, `search_player` | 1 |

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
scraper/
  trn.py               Browser session, FlareSolverr client, pacing, retries
  parsers.py           Tracker.gg JSON (or HTML-wrapped JSON) to models
  utils.py             Riot ID parsing, playlist names, URL building
  exceptions.py        Error types
cache/
  sqlite_cache.py      SQLite cache with per-entry TTLs
```

## Disclaimer

This is an unofficial personal tool. It is not affiliated with, endorsed by or
supported by Tracker Network or Riot Games. Tracker.gg's terms of service and
`robots.txt` do not allow automated collection of profile and match pages in
general. This project relies on a personal-use permission from Tracker
Network's owner and is deliberately kept to low volumes. Do not raise the rate
limits, do not run it for other people, and stop using it if that permission
is withdrawn.

Valorant is a trademark of Riot Games, Inc.
