# Status

Last updated: 18 November 2026

## Summary

The server is built and working. All 7 tools were run against the live tracker.gg site and returned real data. The newest fixes are in the project folder but were not committed yet when this file was written.

## What this is

A private MCP server that lets an AI assistant look up Valorant stats. The data comes from tracker.gg. It is for personal use only, and all credit for the data goes to Tracker Network.

## What was built

Seven tools:

- `get_player_overview`: rank, peak rank, K/D, headshot %, ADR, ACS, win rate and more
- `get_player_agents`: stats for each agent
- `get_player_maps`: stats for each map, split by attack and defense
- `get_recent_matches`: recent matches with your teammates and their K/D/A
- `get_match_details`: the full scoreboard of one match
- `get_teammate_stats`: your most played teammates, their stats, and your record with and without each of them
- `search_player`: find a Riot ID from a name

Behind the tools:

- A scraper that uses a real Chrome browser to get through Cloudflare. FlareSolverr can be set up as a backup.
- A SQLite cache, so the same data is not fetched twice. Overview stats are kept for 45 minutes, agent and map stats for 90 minutes, the match list for 20 minutes and scoreboards for 30 days.
- Slow and polite requests. One at a time, a random wait of 1.5 to 4 seconds between them, at most 240 per hour, and at most 2 retries when a request fails.
- Two ways to connect: stdio and streamable HTTP.
- Settings in a `.env` file. Every setting has a default.
- A README with setup steps, examples and the personal use warning.

The tools give an assistant what it needs for questions like "Which of my 5 most played teammates has the lowest KD on Split?" or "What is my win rate with X compared to without X?"

## What was tested

- Every tool was run against the live site on 18 November 2026.
- Cloudflare did not block the finished server.
- Both ways to connect (stdio and HTTP) were tested with a small client script.
- The FlareSolverr backup was tested with Docker.
- The fallback to the bundled Chromium browser was tested.
- A code review found about 14 problems. All were fixed and checked again.

## What was not tested

- A real private profile. The code returns a clear error for one, but none came up during testing.
- A real Cloudflare block. What the server does after a block was only tested with fake blocks.
- Console playlists.
- Windows and Linux. Everything was run on macOS with Python 3.14 and uv.
- The MCP Inspector window (`uv run mcp dev server.py`). The server does load with `mcp run`, which starts it the same way.

There are no automated tests in the repo. Testing used throwaway scripts with real player data, and those were deleted.

## Limitations

- RR (rank rating) is only shown for Immortal and Radiant players. Tracker.gg does not have it for lower ranks.
- MVP counts only exist per act, so all-act totals leave them out.
- It is slow on purpose. Loading 20 new matches takes about a minute the first time. After that they come from the cache.
- Only one copy of the server should run at a time.
- If tracker.gg changes its site, the scraper can break. The fixes would go in `scraper/parsers.py`.
- Cloudflare could start blocking it at any time. If that happens, wait five minutes, or set `TRN_HEADLESS=false`, or set up FlareSolverr.

## What you need to run it

- Python 3.11 or newer
- uv (or pip)
- Google Chrome. Without Chrome, run `uv run patchright install chromium`.
- Node.js, only for the MCP Inspector
- Docker, only if you want FlareSolverr
- Permission from the owner of Tracker Network to scrape for personal use

On this machine, `.env` points at a Chrome app named "Google Chrome 2". If that app is moved or renamed, change `TRN_BROWSER_EXECUTABLE` in `.env`.

## How to run it

- Install: `uv sync`
- Try the tools by hand: `uv run mcp dev server.py`
- Run it for an MCP client: `uv run server.py`
- Run it over HTTP: `uv run server.py --transport streamable-http --port 8000`

The README has the full setup steps and every setting.

## What is next

- Commit the newest fixes, together with this file.
- Add the server to your MCP client and try it on your own account.
- Add automated tests that use made-up sample data.
- Try a private profile and a console playlist when the chance comes up.
- Check from time to time that tracker.gg has not changed its site.

## Rules

- Personal use only.
- Never sell it, market it or make it public.
- Never present the data as your own work. Tracker Network gets the credit.
- Keep the request limits low.
- Keep the repo private.
