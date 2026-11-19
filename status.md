# Status

Last updated: 19 November 2026

## Summary

The server is built and working. All 18 tools were run against the live tracker.gg site and returned real data. It can also be packed into one file that installs in Claude Desktop. The files for that are new and were not committed yet when this file was written.

## What this is

A private MCP server that lets an AI assistant look up Valorant stats. The data comes from tracker.gg. It is for personal use only, and all credit for the data goes to Tracker Network.

## What was built

Eighteen tools:

- `get_player_overview`: rank, peak rank, K/D, headshot %, ADR, ACS, win rate and more
- `get_player_agents`: stats for each agent and each role
- `get_player_maps`: stats for each map, split by attack and defense
- `get_player_weapons`: kills, deaths, headshot % and kill distance for each weapon
- `get_recent_matches`: recent matches with your teammates and their K/D/A
- `get_match_details`: the full scoreboard of one match
- `get_match_rounds`: one match round by round, with every kill in order
- `get_round_stats`: how rounds go over many matches, for example after the first kill or after a plant
- `get_teammate_stats`: your most played teammates, their stats, and your record with and without each of them
- `get_top_teammates`: tracker.gg's own list of your most played teammates over the last months, and how you do solo or in a party
- `get_daily_stats`: your numbers day by day
- `get_stat_history`: one stat day by day for about a month, and your ten best matches for it
- `get_rank_distribution`: how many players are in each rank, and which top percent a rank is
- `get_leaderboard`: the ranked leaderboard of a region
- `get_meta_insights`: which agents and maps are strong across all tracked matches
- `get_premier_team`: a Premier team with its players, stages and matches
- `get_game_data`: lists of agents, maps, weapons and acts
- `search_player`: find a Riot ID from a name

Most tools give the main numbers by default and the full stat sheet with `detailed=true`. That adds clutches, multi-kills, trades, rounds survived, first deaths, economy, ability use, attack and defense numbers, buy rounds and kills per weapon. None of it needs extra requests. It all comes in the responses the server already fetched.

Behind the tools:

- A scraper that uses a real Chrome browser to get through Cloudflare. FlareSolverr can be set up as a backup.
- A SQLite cache, so the same data is not fetched twice. Overview stats are kept for 45 minutes, agent and map stats for 90 minutes, the match list for 20 minutes and scoreboards for 30 days.
- Slow and polite requests. One at a time, a random wait of 1.5 to 4 seconds between them, at most 240 per hour, and at most 2 retries when a request fails.
- Two ways to connect: stdio and streamable HTTP.
- Settings in a `.env` file. Every setting has a default.
- A Claude Desktop bundle. `manifest.json` describes it, and one zip command packs it into `valorant-trn-stats.mcpb`.
- A README with setup steps, examples and the personal use warning.

The tools give an assistant what it needs for questions like "Which of my 5 most played teammates has the lowest KD on Split?" or "What is my win rate with X compared to without X?"

## What was tested

- Every tool was run against the live site on 18 November 2026.
- Cloudflare did not block the finished server.
- Both ways to connect (stdio and HTTP) were tested with a small client script.
- The FlareSolverr backup was tested with Docker.
- The fallback to the bundled Chromium browser was tested.
- The MCP Inspector starts with `uv run mcp dev server.py`, and a live tool call worked through the Inspector's command line mode.
- A code review found about 14 problems. All were fixed and checked again.
- The extra stats were checked against tracker.gg's own totals on 5 saved matches and 8 live ones. A second review of that work found about 15 more problems, which were also fixed.
- The round-by-round data was checked the same way on 7 saved matches and on live ones. A third review found 6 more problems, which were also fixed.
- The last batch (teammate totals, daily stats, stat history, rank distribution, leaderboard, insights, Premier, filters) was run live and reviewed. That review found 11 problems, which were fixed. Part of it could not finish its checks of Premier and the reference lists.
- The Claude Desktop bundle was unpacked and started the way Claude Desktop starts it, with uv 0.12 and Python 3.12. Eight tools were run live from that copy without errors.
- The bundle was installed in Claude Desktop on 19 November 2026. Claude Desktop's log shows that it installed, connected and found all 18 tools, and two requests made from Claude Desktop came back without errors.

## What was not tested

- Claude Desktop's own copy of uv (0.9.7). It only downloads that when no uv is installed. Here it used the uv that was already on this machine.
- A real private profile. The code returns a clear error for one, but none came up during testing.
- A real Cloudflare block. What the server does after a block was only tested with fake blocks.
- Console playlists.
- Windows and Linux. Everything was run on macOS with Python 3.14 and uv.
- Clicking through the MCP Inspector window by hand.

There are no automated tests in the repo. Testing used throwaway scripts with real player data, and those were deleted.

## Limitations

- RR (rank rating) is only shown for Immortal and Radiant players. Tracker.gg does not have it for lower ranks.
- MVPs, trade kills and a few other numbers only exist per act, so all-act totals leave them out.
- Very long answers are shortened to fit, and the answer says when that happened.
- Kill positions are map coordinates. Tracker.gg does not name the place, so nothing says "A Main". Only spike plants have a site.
- It is slow on purpose. Loading 20 new matches takes about a minute the first time. After that they come from the cache.
- Only one copy of the server should run at a time.
- The Claude Desktop bundle is a copy of the code. After a change, pack and install it again.
- Claude Desktop starts two copies of the server. They share one browser profile, and only one copy can use the browser at a time. If both were asked at the same moment, the second would fail until the first closes its browser, which takes two minutes. This has not happened so far.
- If tracker.gg changes its site, the scraper can break. The fixes would go in `scraper/parsers.py`.
- Cloudflare could start blocking it at any time. If that happens, wait five minutes, or set `TRN_HEADLESS=false`, or set up FlareSolverr.

## What you need to run it

- Python 3.11 or newer
- uv (or pip)
- Google Chrome. Without Chrome, run `uv run patchright install chromium`.
- Node.js, only for the MCP Inspector
- Docker, only if you want FlareSolverr
- Permission from the owner of Tracker Network to scrape for personal use

On this machine, `.env` points at a Chrome app named "Google Chrome 2". If that app is moved or renamed, change `TRN_BROWSER_EXECUTABLE` in `.env`. The bundle uses the same path as the default of its Chrome path setting. That one is changed in Claude Desktop, in the extension's settings.

## How to run it

- Install: `uv sync`
- Try the tools by hand: `uv run mcp dev server.py`
- Run it for an MCP client: `uv run server.py`
- Run it over HTTP: `uv run server.py --transport streamable-http --port 8000`
- Use it in Claude Desktop: follow Quick start at the top of the README. It is installed on this machine already, so opening Claude Desktop is enough.

The README has the full setup steps and every setting.

## What is next

- Commit the bundle files, together with this file.
- Add automated tests that use made-up sample data.
- Try a private profile and a console playlist when the chance comes up.
- Check from time to time that tracker.gg has not changed its site.

## Rules

- Personal use only.
- Never sell it, market it or make it public.
- Never present the data as your own work. Tracker Network gets the credit.
- Keep the request limits low.
- Keep the repo private.
