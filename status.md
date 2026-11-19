# Status

Last updated: 19 November 2026

## Summary

The server is finished and at version 1.0.0. All 18 tools were run against the live tracker.gg site and returned real data. It packs into one file that installs in Claude Desktop, several copies can run side by side, and it has an offline test suite.

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
- Several copies can run at once, which is what Claude Desktop does. Copies that share a data folder keep to those limits together, and each copy that has a browser open uses its own browser profile.
- Two ways to connect: stdio and streamable HTTP.
- Settings in a `.env` file. Every setting has a default.
- A Claude Desktop bundle. `manifest.json` describes it, and one zip command packs it into `valorant-trn-stats.mcpb`.
- An offline test suite of more than 500 tests that runs on made-up sample data.
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
- Two copies were run at the same time on one data folder, on 19 November 2026. Both got their answers, each used its own browser profile, and their requests stayed at least 1.5 seconds apart.
- Writing the test suite turned up 5 small bugs in the parser and the round statistics. All were fixed, and each has a test now.
- A review of the code for running several copies found 1 bug and 6 smaller points. All were fixed, and the reviewer's own stress tests pass now.
- The packed version 1.0.0 was started as two copies with no Chrome path set. Chrome was found by itself, a real match went through the parser correctly, and the requests stayed more than 2 seconds apart.

## What was not tested

- Claude Desktop's own copy of uv (0.9.7). It only downloads that when no uv is installed. Here it used the uv that was already on this machine.
- A real private profile. The code returns a clear error for one, but none came up during testing.
- A real Cloudflare block. What the server does after a block was only tested with fake blocks.
- Console playlists.
- Windows and Linux, including the file locks that copies use to take turns. Everything was run on macOS with Python 3.12 and 3.14 and uv.
- Clicking through the MCP Inspector window by hand.

The automated tests only use made-up sample data. The checks against real player data used throwaway scripts, and those were deleted.

## Limitations

- RR (rank rating) is only shown for Immortal and Radiant players. Tracker.gg does not have it for lower ranks.
- MVPs, trade kills and a few other numbers only exist per act, so all-act totals leave them out.
- Very long answers are shortened to fit, and the answer says when that happened.
- Kill positions are map coordinates. Tracker.gg does not name the place, so nothing says "A Main". Only spike plants have a site.
- It is slow on purpose. Loading 20 new matches takes about a minute the first time. After that they come from the cache.
- At most three copies can have a browser open at the same moment. A fourth gets an error until another one has been idle for two minutes.
- Copies only work together when they use the same data folder. The project folder and the Claude Desktop bundle use different folders, so those two do not know about each other.
- The Claude Desktop bundle is a copy of the code. After a change, pack and install it again.
- If tracker.gg changes its site, the scraper can break. The fixes would go in `scraper/parsers.py`.
- Cloudflare could start blocking it at any time. If that happens, wait five minutes, or set `TRN_HEADLESS=false`, or set up FlareSolverr.

## What you need to run it

- Python 3.11 or newer
- uv (or pip)
- Google Chrome. Without Chrome, run `uv run patchright install chromium`.
- Node.js, only for the MCP Inspector
- Docker, only if you want FlareSolverr
- Permission from the owner of Tracker Network to scrape for personal use

On this machine Chrome is an app named "Google Chrome 2". The server finds it by itself, so the `TRN_BROWSER_EXECUTABLE` line in `.env` is no longer needed.

## How to run it

- Install: `uv sync`
- Try the tools by hand: `uv run mcp dev server.py`
- Run it for an MCP client: `uv run server.py`
- Run it over HTTP: `uv run server.py --transport streamable-http --port 8000`
- Run the tests: `uv run --with pytest pytest`
- Use it in Claude Desktop: follow Quick start at the top of the README.

The README has the full setup steps and every setting.

## What is next

- Install version 1.0.0 in Claude Desktop. Version 0.1.0 is installed there now. Double-click `valorant-trn-stats.mcpb` and confirm the update.
- Try a private profile and a console playlist when the chance comes up.
- Check from time to time that tracker.gg has not changed its site.

## Rules

- Personal use only.
- Never sell it, market it or make it public.
- Never present the data as your own work. Tracker Network gets the credit.
- Keep the request limits low.
- Keep the repo private.
