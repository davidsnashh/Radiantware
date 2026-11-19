"""Made-up tracker.gg payloads for the parser tests.

Every builder returns a fresh structure, so a test can change it before parsing.
"""

from __future__ import annotations

from typing import Any

BRIM = "Brim Stone#TST"
JETT = "Jett Lag#0001"
SAGE = "Sage Advice#HEAL"
CYPHER = "Cypher Punk#CAM"
RED = "Red"
BLUE = "Blue"
TEAM_OF = {BRIM: RED, JETT: RED, SAGE: BLUE, CYPHER: BLUE}
AGENT_OF = {BRIM: "Brimstone", JETT: "Jett", SAGE: "Sage", CYPHER: "Cypher"}

MATCH_ID = "00000000-0000-4000-8000-00000000000a"
ROSTER_ID = "11111111-0000-4000-8000-000000000001"
ACT_ID = "22222222-0000-4000-8000-000000000005"

# Minimap x comes from game y and minimap y from game x.
MAP_DETAILS = {
    "xMultiplier": 0.0001,
    "yMultiplier": -0.0001,
    "xScalarToAdd": 0.5,
    "yScalarToAdd": 0.5,
}


def stats(**values: Any) -> dict[str, dict[str, Any]]:
    return {key: {"value": value} for key, value in values.items()}


def spot(x: float, y: float) -> dict[str, float]:
    return {"x": x, "y": y, "z": 0}


def team_summary(team: str, won: bool, rounds_won: int, rounds_lost: int) -> dict[str, Any]:
    return {
        "type": "team-summary",
        "attributes": {"teamId": team},
        "metadata": {"name": team, "hasWon": won},
        "stats": stats(roundsWon=rounds_won, roundsLost=rounds_lost),
    }


def player_summary(
    name: str, team: str | None, agent: str | None = None, **values: Any
) -> dict[str, Any]:
    return {
        "type": "player-summary",
        "attributes": {"platformUserIdentifier": name},
        "metadata": {
            "teamId": team,
            "agentName": agent,
            "platformInfo": {"platformUserHandle": name},
        },
        "stats": stats(**values),
    }


def round_summary(
    number: int,
    winner: str,
    result: str,
    *,
    plant: dict[str, Any] | None = None,
    defuse: dict[str, Any] | None = None,
    exploded: int | None = None,
) -> dict[str, Any]:
    return {
        "type": "round-summary",
        "attributes": {"round": number},
        "metadata": {"plant": plant, "defuse": defuse, "exploded": exploded},
        "stats": stats(winningTeam=winner, roundResult=result),
    }


def spike_event(
    name: str, time_ms: int, site: str | None = None, at: dict[str, float] | None = None
) -> dict[str, Any]:
    return {"platformUserIdentifier": name, "site": site, "roundTime": time_ms, "location": at}


def player_round(
    number: int, name: str, team: str, side: str, won: bool, **values: Any
) -> dict[str, Any]:
    return {
        "type": "player-round",
        "attributes": {"round": number, "platformUserIdentifier": name},
        "metadata": {"teamId": team, "teamSide": side, "hasWon": won},
        "stats": stats(**values),
    }


def kill(
    number: int,
    time_ms: int,
    killer: str,
    victim: str,
    weapon: str | None,
    *,
    cause: str = "Weapon",
    alt_fire: bool = False,
    killer_at: dict[str, float] | None = None,
    victim_at: dict[str, float] | None = None,
    assists: tuple[str, ...] = (),
    also_seen: tuple[str, ...] = (),
) -> dict[str, Any]:
    locations = [{"platformUserIdentifier": name, "location": spot(0, 0)} for name in also_seen]
    if killer_at is not None:
        locations.append({"platformUserIdentifier": killer, "location": killer_at})
    return {
        "type": "player-round-kills",
        "attributes": {
            "round": number,
            "platformUserIdentifier": killer,
            "opponentPlatformUserIdentifier": victim,
        },
        "metadata": {
            "roundTime": time_ms,
            "weaponName": weapon,
            "finishingDamage": {"damageType": cause, "isSecondaryFireMode": alt_fire},
            "opponentLocation": victim_at,
            "playerLocations": locations,
            "assistants": [{"platformUserIdentifier": name} for name in assists],
        },
    }


def damage(
    number: int, attacker: str, victim: str, amount: int, head: int = 0, body: int = 0, leg: int = 0
) -> dict[str, Any]:
    return {
        "type": "player-round-damage",
        "attributes": {
            "round": number,
            "platformUserIdentifier": attacker,
            "opponentPlatformUserIdentifier": victim,
        },
        "stats": stats(damage=amount, headshots=head, bodyshots=body, legshots=leg),
    }


def loadout(name: str, kind: str, **values: Any) -> dict[str, Any]:
    return {
        "type": "player-loadout",
        "attributes": {"platformUserIdentifier": name, "loadout": kind},
        "stats": stats(**values),
    }


def match_payload(segments: list[dict[str, Any]], **metadata: Any) -> dict[str, Any]:
    return {
        "attributes": {"id": MATCH_ID},
        "metadata": {
            "dateStarted": "2026-03-01T18:00:00+00:00",
            "mapName": "Ascent",
            "modeName": "Competitive",
            "queueId": "competitive",
            "isRanked": True,
            "duration": 1_530_000,
            "mapDetails": dict(MAP_DETAILS),
            **metadata,
        },
        "segments": segments,
    }


# The sample match: Red attacks in rounds 1 to 3 and Blue in rounds 4 to 6.
# Red wins rounds 1, 2, 4 and 6. Every number the tests expect is worked out
# from the tables below.

# round: attacking team, winner, how it ended
ROUNDS = {
    1: (RED, RED, "Elimination"),
    2: (RED, RED, "Bomb detonated"),
    3: (RED, BLUE, "Elimination"),
    4: (BLUE, RED, "Bomb defused"),
    5: (BLUE, BLUE, "Elimination"),
    6: (BLUE, RED, "Elimination"),
}

# Per round: credits spent, loadout value, score, kills, deaths, damage.
# Kills and damage are tracker.gg's, so Jett's round 1 includes the kill on
# a teammate and the damage done to him.
ROUND_ROWS = {
    BRIM: [
        (800, 800, 300, 1, 1, 150),
        (3900, 4700, 250, 1, 0, 150),
        (4500, 5300, 50, 0, 1, 40),
        (800, 800, 500, 2, 0, 300),
        (1050, 1900, 0, 0, 1, 0),
        (4000, 4800, 40, 0, 0, 0),
    ],
    JETT: [
        (800, 800, 250, 2, 0, 240),
        (3850, 4650, 30, 0, 1, 30),
        (2000, 2900, 0, 0, 1, 0),
        (0, 500, 100, 0, 0, 0),
        (1000, 1800, 70, 0, 1, 70),
        (2500, 3400, 280, 1, 0, 150),
    ],
    SAGE: [
        (800, 800, 60, 0, 1, 60),
        (1000, 1800, 200, 1, 1, 150),
        (3900, 4700, 0, 0, 1, 100),
        (800, 800, 90, 0, 1, 90),
        (3850, 4650, 550, 2, 0, 300),
        (4200, 5000, 0, 0, 1, 0),
    ],
    # Cypher is not in the game for round 6.
    CYPHER: [
        (800, 800, 0, 0, 1, 0),
        (1050, 1850, 0, 0, 0, 0),
        (500, 1300, 500, 2, 0, 300),
        (700, 700, 0, 0, 1, 0),
        (3900, 4700, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0),
    ],
}

# round, attacker, victim, damage, head, body and leg hits
DAMAGE_ROWS = [
    (1, BRIM, SAGE, 150, 1, 2, 0),
    (1, JETT, BRIM, 100, 1, 0, 0),
    (1, JETT, CYPHER, 140, 0, 4, 1),
    (1, SAGE, BRIM, 60, 0, 2, 0),
    (2, SAGE, JETT, 150, 1, 0, 0),
    (2, BRIM, SAGE, 150, 1, 1, 0),
    (2, JETT, SAGE, 30, 0, 1, 0),
    (3, SAGE, SAGE, 100, 0, 1, 0),
    (3, CYPHER, BRIM, 150, 0, 1, 0),
    (3, CYPHER, JETT, 150, 1, 0, 0),
    (3, BRIM, CYPHER, 40, 0, 0, 2),
    (4, BRIM, CYPHER, 150, 0, 5, 0),
    (4, BRIM, SAGE, 150, 1, 1, 0),
    (4, SAGE, BRIM, 90, 0, 3, 0),
    (5, SAGE, BRIM, 150, 1, 0, 0),
    (5, SAGE, JETT, 150, 0, 4, 0),
    (5, JETT, SAGE, 70, 0, 2, 1),
    (6, JETT, SAGE, 150, 0, 6, 2),
]

SUMMARY_STATS = {
    BRIM: {
        "kills": 4,
        "deaths": 3,
        "assists": 1,
        "kdRatio": 1.3333,
        "score": 1140,
        "scorePerRound": 190.0,
        "damage": 640,
        "damageReceived": 450,
        "damagePerRound": 106.6667,
        "damageDeltaPerRound": 31.6667,
        "hsAccuracy": 21.4286,
        "kast": 83.3333,
        "headshots": 3,
        "firstKills": 2,
        "firstDeaths": 1,
        "esr": 66.6667,
        "survived": 3,
        "traded": 1,
        "tradesAvenger": 0,
        "clutches": 0,
        "clutchesLost": 0,
        "multiKills": 0,
        "doubleKills": 1,
        "tripleKills": 0,
        "quadraKills": 0,
        "pentaKills": 0,
        "plants": 1,
        "defuses": 0,
        "econRating": 42.5249,
        "grenadeCasts": 3,
        "ability1Casts": 4,
        "ability2Casts": 6,
        "ultimateCasts": 1,
        "grenadeKills": 0,
        "ability1Kills": 0,
        "ability2Kills": 0,
        "ultimateKills": 0,
        "trnPerformanceScore": 780,
        "performance": 61.54,
        "placement": 1,
        "attackKills": 2,
        "attackDeaths": 2,
        "attackAssists": 1,
        "attackFirstKills": 1,
        "attackFirstDeaths": 0,
        "defenseKills": 2,
        "defenseDeaths": 1,
        "defenseAssists": 0,
        "defenseFirstKills": 1,
        "defenseFirstDeaths": 1,
    },
    JETT: {
        "kills": 2,
        "deaths": 3,
        "assists": 1,
        "kdRatio": 0.6667,
        "score": 730,
        "scorePerRound": 121.6667,
        "damage": 390,
        "damageReceived": 450,
        "damagePerRound": 65.0,
        "damageDeltaPerRound": -10.0,
        "hsAccuracy": 5.5556,
        "kast": 50.0,
        "headshots": 1,
        "firstKills": 1,
        "firstDeaths": 1,
        "esr": 50.0,
        "doubleKills": 1,
        "tripleKills": 0,
        "quadraKills": 0,
        "pentaKills": 0,
        "multiKills": 0,
        "plants": 0,
        "defuses": 1,
        "placement": 3,
        "attackKills": 2,
        "attackDeaths": 2,
        "defenseKills": 1,
        "defenseDeaths": 1,
    },
    SAGE: {
        "kills": 3,
        "deaths": 5,
        "assists": 0,
        "kdRatio": 0.6,
        "score": 900,
        "scorePerRound": 150.0,
        "damage": 600,
        "damageReceived": 700,
        "damagePerRound": 100.0,
        "damageDeltaPerRound": -16.6667,
        "hsAccuracy": 18.1818,
        "kast": 33.3333,
        "headshots": 2,
        "firstKills": 2,
        "firstDeaths": 3,
        "esr": 40.0,
        "clutches": 0,
        "clutchesLost": 1,
        "clutchesLost1v1": 0,
        "clutchesLost1v2": 1,
        "doubleKills": 1,
        "tripleKills": 0,
        "quadraKills": 0,
        "pentaKills": 0,
        "multiKills": 0,
        "plants": 1,
        "defuses": 0,
        "placement": 2,
        "attackKills": 2,
        "attackDeaths": 2,
        "defenseKills": 1,
        "defenseDeaths": 3,
    },
    CYPHER: {
        "kills": 2,
        "deaths": 2,
        "assists": 0,
        "kdRatio": 1.0,
        "score": 500,
        "scorePerRound": 83.3333,
        "damage": 300,
        "damageReceived": 330,
        "damagePerRound": 50.0,
        "damageDeltaPerRound": -5.0,
        "hsAccuracy": 50.0,
        "kast": 16.6667,
        "headshots": 1,
        "firstKills": 0,
        "firstDeaths": 1,
        "esr": 0.0,
        "clutches": 1,
        "clutches1v1": 0,
        "clutches1v2": 1,
        "clutches1v3": 0,
        "clutchesLost": 0,
        "doubleKills": 1,
        "tripleKills": 0,
        "quadraKills": 0,
        "pentaKills": 0,
        "multiKills": 0,
        "plants": 0,
        "defuses": 0,
        "placement": 4,
        "attackKills": 0,
        "attackDeaths": 1,
        "defenseKills": 2,
        "defenseDeaths": 1,
    },
}

# What tracker.gg sends for the per-round numbers of a side. They are wrong on
# defense, so none of them may reach the result.
WRONG_SIDE_NUMBERS = {
    "ScorePerRound": 999.0,
    "DamagePerRound": 888.0,
    "RoundsWinPct": 77.0,
    "DamageDeltaPerRound": 66.0,
}

# name: buy type -> rounds, rounds won, kills
BUY_ROWS = {
    BRIM: {"full": (3, 2, 1), "eco": (0, 0, 0), "pistol": (2, 2, 3), "semi": (1, 0, 0)},
    JETT: {"semi": (3, 2, 1), "pistol": (2, 2, 2), "eco": (1, 0, 0)},
    SAGE: {"full": (2, 1, 0), "semi": (1, 1, 2), "eco": (1, 0, 1), "pistol": (2, 0, 0)},
    CYPHER: {"eco": (1, 1, 2), "full": (1, 1, 0), "semi": (1, 0, 0), "pistol": (2, 0, 0)},
}


def sample_kills() -> list[dict[str, Any]]:
    """The kill events of the sample match, deliberately not in time order."""
    return [
        kill(1, 35_500, JETT, CYPHER, "Ghost"),
        kill(1, 28_000, JETT, BRIM, "Classic"),
        kill(
            1,
            20_000,
            BRIM,
            SAGE,
            "Classic",
            killer_at=spot(1000, 2000),
            victim_at=spot(1000, 5000),
            assists=(JETT,),
        ),
        # Sage is killed after the spike has gone off and taken Cypher with it.
        # The spike death is listed with Cypher as his own killer.
        kill(2, 80_000, BRIM, SAGE, "Vandal", killer_at=spot(0, 0), victim_at=spot(0, 1250)),
        kill(2, 75_000, CYPHER, CYPHER, None, cause="Bomb"),
        kill(
            2,
            15_000,
            SAGE,
            JETT,
            "Sheriff",
            killer_at=spot(-5500, -5500),
            victim_at=spot(5500, 5500),
        ),
        kill(3, 5_000, SAGE, SAGE, None, cause="Fall"),
        kill(3, 20_000, CYPHER, BRIM, "Operator", victim_at=spot(0, 0)),
        kill(3, 40_000, CYPHER, JETT, "Operator", killer_at=spot(0, 0), victim_at=spot(90_000, 0)),
        kill(4, 20_000, BRIM, CYPHER, "Ghost"),
        kill(4, 50_000, BRIM, SAGE, "Ghost"),
        kill(5, 12_000, SAGE, BRIM, "Phantom"),
        kill(5, 25_000, SAGE, JETT, "Phantom"),
        kill(6, 30_000, JETT, SAGE, "Bucky", alt_fire=True, also_seen=(BRIM,)),
    ]


def sample_round_summaries() -> list[dict[str, Any]]:
    extras: dict[int, dict[str, Any]] = {
        2: {"plant": spike_event(BRIM, 30_000, "A", spot(2000, -1000)), "exploded": 75_000},
        4: {
            "plant": spike_event(SAGE, 40_000, "B", spot(-1000, 1000)),
            "defuse": spike_event(JETT, 70_000, at=spot(-1000, 1000)),
        },
    }
    return [
        round_summary(number, winner, result, **extras.get(number, {}))
        for number, (_, winner, result) in reversed(ROUNDS.items())
    ]


def sample_round_rows() -> list[dict[str, Any]]:
    rows = []
    for name, lines in ROUND_ROWS.items():
        team = TEAM_OF[name]
        for number, (spent, value, score, kills, deaths, dealt) in enumerate(lines, start=1):
            attacking, winner, _ = ROUNDS[number]
            rows.append(
                player_round(
                    number,
                    name,
                    team,
                    "attacker" if team == attacking else "defender",
                    team == winner,
                    spentCredits=spent,
                    loadoutValue=value,
                    remainingCredits=9000 - spent,
                    score=score,
                    kills=kills,
                    deaths=deaths,
                    assists=0,
                    damage=dealt,
                )
            )
    return rows


def sample_summaries() -> list[dict[str, Any]]:
    segments = []
    for name, values in SUMMARY_STATS.items():
        wrong = {
            side + key: number
            for side in ("attack", "defense")
            for key, number in WRONG_SIDE_NUMBERS.items()
        }
        segment = player_summary(name, TEAM_OF[name], AGENT_OF[name], **values, **wrong)
        segment["stats"]["rank"] = {"value": "Gold 2", "metadata": {}}
        segments.append(segment)
    brim = segments[0]["metadata"]
    brim["partyId"] = 7
    brim["accountLevel"] = 120
    brim["tags"] = [{"name": "Top Frag"}, {"name": "Planter"}, {"icon": "no-name"}]
    brim["performanceScores"] = {
        "damage": 12.346,
        "killImpact": 20.5,
        "deathImpact": -4.25,
        "plants": 1,
        "ratings": {"qualifier": "distinction"},
    }
    return segments


def sample_buy_rows() -> list[dict[str, Any]]:
    return [
        loadout(name, kind, roundsPlayed=played, roundsWon=won, kills=kills, hsAccuracy=50.0)
        for name, kinds in BUY_ROWS.items()
        for kind, (played, won, kills) in kinds.items()
    ]


def sample_match() -> dict[str, Any]:
    segments = [
        team_summary(RED, True, 4, 2),
        team_summary(BLUE, False, 2, 4),
        *sample_summaries(),
        *sample_round_summaries(),
        *sample_round_rows(),
        *sample_kills(),
        *(damage(*row) for row in DAMAGE_ROWS),
        *sample_buy_rows(),
    ]
    return match_payload(segments, rounds=6)


def surrendered_match() -> dict[str, Any]:
    """The sample match, given up by Blue: rounds 7 and 8 are listed but were never played."""
    data = sample_match()
    data["metadata"]["rounds"] = 8
    for number in (7, 8):
        data["segments"].append(round_summary(number, RED, "Surrendered"))
        for name, team in TEAM_OF.items():
            side = "attacker" if team == BLUE else "defender"
            data["segments"].append(
                player_round(
                    number,
                    name,
                    team,
                    side,
                    team == RED,
                    spentCredits=0,
                    loadoutValue=0,
                    score=0,
                    kills=0,
                    deaths=0,
                    damage=0,
                )
            )
    data["segments"].append(kill(7, 1_000, SAGE, BRIM, "Vandal"))
    data["segments"].append(damage(7, SAGE, BRIM, 150, head=1))
    return data


def deathmatch() -> dict[str, Any]:
    """A free-for-all: every player is listed as a team of their own."""
    lines = {BRIM: (2, 1, 310.0), JETT: (1, 2, 150.0), SAGE: (1, 1, 180.0)}
    segments = [team_summary(name, name == BRIM, 0, 0) for name in lines]
    segments += [
        player_summary(name, name, AGENT_OF[name], kills=kills, deaths=deaths, scorePerRound=acs)
        for name, (kills, deaths, acs) in lines.items()
    ]
    segments += [
        kill(1, 4_000, BRIM, JETT, "Vandal"),
        kill(1, 9_000, JETT, SAGE, "Phantom"),
        kill(1, 15_000, SAGE, SAGE, None, cause="Fall"),
        kill(1, 21_000, BRIM, JETT, "Sheriff"),
        kill(1, 30_000, SAGE, BRIM, "Vandal"),
        damage(1, BRIM, JETT, 300, head=2),
        damage(1, JETT, SAGE, 150, body=4),
        damage(1, SAGE, BRIM, 150, head=1),
        round_summary(1, BRIM, "Elimination"),
    ]
    segments += [
        player_round(1, name, name, "attacker", name == BRIM, spentCredits=0, score=100)
        for name in lines
    ]
    return match_payload(
        segments,
        modeName="Deathmatch",
        queueId="deathmatch",
        isRanked=False,
        isTeamBased=False,
        isRoundBased=False,
    )


def segment(
    kind: str,
    name: str | None = None,
    *,
    attributes: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    **values: Any,
) -> dict[str, Any]:
    return {
        "type": kind,
        "attributes": attributes or {},
        "metadata": {"name": name, **(metadata or {})},
        "stats": stats(**values),
    }


# One act of a player. The agent, map and role rows add up to these numbers.
OVERALL_STATS = {
    "matchesPlayed": 20,
    "matchesWon": 12,
    "matchesLost": 7,
    "matchesTied": 1,
    "matchesWinPct": 60.0,
    "kills": 300,
    "deaths": 250,
    "assists": 100,
    "kDRatio": 1.2,
    "kDARatio": 1.6,
    "scorePerRound": 231.46,
    "damagePerRound": 150.27,
    "damageDeltaPerRound": 12.34,
    "headshotsPercentage": 24.56,
    "kAST": 71.23,
    "firstBloods": 45,
    "firstDeaths": 30,
    "esr": 0.6,
    "aces": 1,
    "clutches": 9,
    "clutches1v1": 5,
    "clutches1v2": 3,
    "clutches1v3": 1,
    "clutches1v4": 0,
    "clutches1v5": 0,
    "clutchesLost": 14,
    "clutchesLost1v1": 4,
    "clutchesLost1v2": 6,
    "clutchesLost1v3": 4,
    "clutchesLost1v4": 0,
    "clutchesLost1v5": 0,
    "mVPs": 6,
    "roundsPlayed": 420,
    "roundsWon": 230,
    "roundsLost": 190,
    "roundsWinPct": 54.76,
    "timePlayed": 45_000,
    "matchesDisconnected": 0,
    "matchesDuration": 2_100,
    "performancePerMatch": 55.56,
    "damage": 63_105,
    "damageReceived": 57_922,
    "lastDeaths": 20,
    "survived": 170,
    "traded": 60,
    "tradesAvenger": 22,
    "kills2K": 30,
    "kills3K": 10,
    "kills4K": 3,
    "kills5K": 1,
    "kills6K": 0,
    "mostKillsInMatch": 31,
    "plants": 25,
    "defuses": 8,
    "econRatingPerMatch": 61.27,
    "grenadeCasts": 100,
    "ability1Casts": 200,
    "ability2Casts": 150,
    "ultimateCasts": 40,
    "grenadeKills": 0,
    "ability1Kills": 0,
    "ability2Kills": 0,
    "ultimateKills": 0,
    "dealtHeadshots": 280,
    "dealtBodyshots": 800,
    "dealtLegshots": 60,
    "receivedHeadshots": 200,
    "receivedBodyshots": 700,
    "receivedLegshots": 90,
    "flawless": 12,
    "thrifty": 5,
    "teamAces": 4,
    "suicides": 2,
    "trnPerformanceScore": 742,
    "attackKills": 160,
    "attackDeaths": 130,
    "attackRoundsPlayed": 215,
    "attackRoundsWon": 110,
    "attackRoundsWinPct": 51.16,
    "attackFirstBloods": 27,
    "attackFirstDeaths": 18,
    "attackTradesAvenger": 12,
    "defenseKills": 140,
    "defenseDeaths": 120,
    "defenseRoundsPlayed": 205,
    "defenseRoundsWon": 120,
    "defenseRoundsWinPct": 58.54,
    "defenseFirstBloods": 18,
    "defenseFirstDeaths": 12,
    "defenseTradesAvenger": 10,
}

JETT_ABILITIES = {
    "Grenade": {"name": "Cloudburst"},
    "Ability1": {"name": "Updraft"},
    "Ability2": {"name": "Tailwind"},
    "Ultimate": {"name": "Blade Storm"},
}


def stat_segments(season_id: str | None = ACT_ID) -> list[dict[str, Any]]:
    """The segment list of one act, or of all acts together when season_id is None.

    The all-act list carries tracker.gg's placeholder zeros.
    """
    all_acts = season_id is None
    scope = {"seasonId": season_id}

    def row(kind: str, name: str | None = None, **extra: Any) -> dict[str, Any]:
        attributes = {**scope, **extra.pop("attributes", {})}
        values = extra.pop("values")
        if all_acts and "mVPs" in values:
            values = {**values, "mVPs": 0, "thrifty": 0}
        if all_acts and kind == "weapon":
            values = {**values, "damageReceived": 0}
        return segment(kind, name, attributes=attributes, metadata=extra, **values)

    overall = row("playlist" if all_acts else "season", values=dict(OVERALL_STATS))
    overall["stats"]["rank"] = {
        "value": None,
        "metadata": {"tierName": "Gold 2", "iconUrl": "https://example.invalid/tiers/13.png"},
    }
    overall["stats"]["peakRank"] = {
        "value": 312,
        "rank": 480,
        "metadata": {"tierName": "Immortal 3", "tierId": 26, "actName": "V26: ACT IV"},
    }
    overall["stats"]["kDRatio"]["percentile"] = 88.0
    overall["stats"]["matchesWinPct"]["percentile"] = 71.5
    overall["stats"]["scorePerRound"]["percentile"] = 93.2

    return [
        overall,
        row(
            "agent",
            "Sage",
            role="Sentinel",
            abilities={},
            values={
                "matchesPlayed": 8,
                "matchesWon": 4,
                "matchesLost": 3,
                "kills": 100,
                "deaths": 100,
                "pickRate": 40.0,
                "mVPs": 2,
                "thrifty": 2,
                "tradesAvenger": 7,
                "grenadeCasts": 31,
                "ultimateCasts": 6,
                "grenadeKills": 0,
            },
        ),
        row(
            "agent",
            "Jett",
            role="Duelist",
            abilities=dict(JETT_ABILITIES),
            values={
                "matchesPlayed": 12,
                "matchesWon": 8,
                "matchesLost": 4,
                "kills": 200,
                "deaths": 150,
                "pickRate": 60.0,
                "mVPs": 4,
                "thrifty": 3,
                "tradesAvenger": 15,
                "attackTradesAvenger": 9,
                "attackKills": 110,
                "grenadeCasts": 30,
                "ability1Casts": 45,
                "ability2Casts": 80,
                "ultimateCasts": 9,
                "grenadeKills": 0,
                "ability1Kills": 0,
                "ability2Kills": 0,
                "ultimateKills": 0,
            },
        ),
        row("agent-top-map", "Jett", attributes={"mapKey": "bind"}, values={"matchesPlayed": 1}),
        row(
            "agent-top-map",
            "Jett",
            attributes={"mapKey": "ascent"},
            values={"matchesPlayed": 5, "matchesWon": 4, "matchesLost": 1, "kDRatio": 1.523},
        ),
        row(
            "agent-top-map",
            "Jett",
            attributes={"mapKey": "district-nine"},
            values={"matchesPlayed": 4},
        ),
        row("agent-top-map", "Jett", attributes={"mapKey": "split"}, values={"matchesPlayed": 2}),
        row("agent-top-map", "Sage", attributes={"mapKey": "split"}, values={"matchesPlayed": 4}),
        row("agent-top-map", "Sage", values={"matchesPlayed": 9}),
        row(
            "map",
            "Split",
            attributes={"key": "split"},
            values={"matchesPlayed": 6, "matchesWon": 3, "mVPs": 1, "thrifty": 1},
        ),
        row(
            "map",
            "Ascent",
            attributes={"key": "ascent"},
            values={
                "matchesPlayed": 10,
                "matchesWon": 7,
                "mVPs": 4,
                "thrifty": 3,
                "tradesAvenger": 11,
                "attackRoundsPlayed": 100,
                "attackRoundsWon": 48,
                "defenseRoundsPlayed": 110,
                "defenseRoundsWon": 67,
            },
        ),
        row(
            "map",
            "Bind",
            attributes={"key": "bind"},
            values={"matchesPlayed": 4, "matchesWon": 2, "mVPs": 1, "thrifty": 1},
        ),
        row("map-top-agent", "Omen", attributes={"mapKey": "ascent"}, values={"matchesPlayed": 1}),
        row("map-top-agent", "Sova", attributes={"mapKey": "ascent"}, values={"matchesPlayed": 2}),
        row(
            "map-top-agent",
            "Jett",
            attributes={"mapKey": "ascent"},
            values={"matchesPlayed": 4, "matchesWinPct": 75.0, "scorePerRound": 250.04},
        ),
        row("map-top-agent", "Sage", attributes={"mapKey": "ascent"}, values={"matchesPlayed": 3}),
        row("map-top-agent", "Sage", attributes={"mapKey": "split"}, values={"matchesPlayed": 4}),
        row(
            "agent-role",
            "Sentinel",
            values={"matchesPlayed": 8, "kills": 100, "mVPs": 2, "thrifty": 2, "tradesAvenger": 7},
        ),
        row(
            "agent-role",
            "Duelist",
            values={
                "matchesPlayed": 12,
                "kills": 200,
                "mVPs": 4,
                "thrifty": 3,
                "tradesAvenger": 15,
            },
        ),
        row("weapon", "Melee", category="Melee", values={"kills": 0, "killDistance": 0}),
        row(
            "weapon",
            "Classic",
            category="Sidearm",
            values={
                "kills": 20,
                "deaths": 12,
                "secondaryKills": 6,
                "damage": 3_100,
                "damageReceived": 1_800,
                "killDistance": 15_000,
                "longestKillDistance": 2_110,
            },
        ),
        row(
            "weapon",
            "Vandal",
            category="Rifle",
            values={
                "matchesPlayed": 18,
                "roundsPlayed": 200,
                "kills": 120,
                "deaths": 90,
                "kDRatio": 1.3333,
                "secondaryKills": 0,
                "headshotsPercentage": 31.26,
                "damage": 21_000,
                "damageReceived": 15_000,
                "dealtHeadshots": 100,
                "dealtBodyshots": 200,
                "dealtLegshots": 20,
                "killDistance": 240_000,
                "longestKillDistance": 5_230,
            },
        ),
    ]


def sample_profile() -> dict[str, Any]:
    def peak(playlist: str, rating: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "peak-rating",
            "attributes": {"playlist": playlist},
            "metadata": {},
            "stats": {"peakRating": rating},
        }

    return {
        "platformInfo": {"platformUserIdentifier": BRIM, "platformUserHandle": "Brim Stone"},
        "metadata": {
            "accountLevel": 120,
            "activeShard": "eu",
            "privacy": "public",
            "defaultPlaylist": "competitive",
            "defaultSeason": ACT_ID,
            "premierRosterId": ROSTER_ID,
            "seasons": [
                {"id": ACT_ID, "name": "V26: ACT 5", "shortName": "E26: A5"},
                {"id": "older-act", "name": "V26: ACT 4", "shortName": "E26: A4"},
                {"name": "No ID"},
            ],
            "playlists": [{"id": "competitive"}, {"id": "unrated"}, {"name": "No ID"}],
        },
        "segments": [
            *stat_segments(),
            peak(
                "competitive",
                {
                    "value": 450,
                    "rank": 212,
                    "metadata": {
                        "tierName": "Radiant",
                        "iconUrl": "https://example.invalid/tiers/27.png",
                        "actName": "V25: ACT 3",
                    },
                },
            ),
            peak("unrated", {"value": None, "metadata": {"tierName": "Silver 1"}}),
        ],
    }


def history_row(
    match_id: str | None,
    *,
    result: str | None = "victory",
    own_result: str | None = None,
    agent: str = "Jett",
    played_at: str = "2026-03-01T18:00:00+00:00",
    **values: Any,
) -> dict[str, Any]:
    return {
        "attributes": {"id": match_id},
        "metadata": {
            "timestamp": played_at,
            "mapName": "Ascent",
            "modeName": "Competitive",
            "seasonName": "V26: ACT 5",
            "result": result,
        },
        "segments": [
            {
                "type": "overview",
                "metadata": {"agentName": agent, "result": own_result},
                "stats": stats(**values),
            }
        ],
    }


def sample_match_page() -> dict[str, Any]:
    first = history_row(
        MATCH_ID,
        roundsWon=13,
        roundsLost=9,
        kills=21,
        deaths=14,
        assists=5,
        kdRatio=1.5,
        scorePerRound=262.44,
        damagePerRound=171.38,
        headshotsPercentage=28.57,
        kAST=77.27,
        damage=3770,
        score=5774,
        placement=2,
        trnPerformanceScore=812,
        lastDeaths=3,
        suicides=0,
        dealtHeadshots=12,
        dealtBodyshots=28,
        dealtLegshots=2,
    )
    first["segments"][0]["stats"]["rank"] = {"value": "Gold 2", "metadata": {"tierName": "Gold 2"}}
    second = history_row(
        "00000000-0000-4000-8000-00000000000b",
        result=None,
        own_result="defeat",
        agent="Sage",
        played_at="2026-02-28T20:30:00+00:00",
        roundsWon=7,
        roundsLost=13,
        kills=9,
        deaths=16,
    )
    return {"matches": [first, history_row(None), second], "metadata": {"next": 1}}


def sample_search() -> list[Any]:
    return [
        {"platformUserIdentifier": JETT, "status": "online"},
        {"platformUserIdentifier": BRIM},
        {"platformUserHandle": "No identifier"},
        "junk",
    ]


def record(matches: int, wins: int, kd: float, placement: float) -> dict[str, Any]:
    return stats(
        matchesPlayed=matches,
        matchesWon=wins,
        matchesLost=matches - wins,
        matchesWinPct=100 * wins / matches if matches else 0,
        kdRatio=kd,
        avgPlacement=placement,
    )


def sample_aggregate() -> dict[str, Any]:
    def teammate(name: str, last: str, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "platformInfo": {"platformUserIdentifier": name},
            "metadata": {"lastMatchTimestamp": last},
            "stats": row,
        }

    def day(date: str, row: dict[str, Any], **values: Any) -> dict[str, Any]:
        return {"date": date, "stats": {**row, **stats(**values)}}

    return {
        "teammates": [
            teammate(SAGE, "2026-02-20T19:00:00+00:00", record(8, 3, 0.914, 6.25)),
            teammate(JETT, "2026-03-01T18:00:00+00:00", record(30, 18, 1.237, 3.84)),
            {"platformInfo": {}, "stats": record(50, 25, 1.0, 5.0)},
        ],
        "parties": [
            {"partySize": 5, "stats": record(6, 5, 1.31, 3.5)},
            {"partySize": 3, "stats": record(0, 0, 0, 0)},
            {"partySize": 1, "stats": record(14, 6, 1.02, 4.9)},
            {"partySize": 2, "stats": record(10, 6, 1.18, 4.2)},
        ],
        "heatmaps": [
            day(
                "2026-03-01T00:00:00+00:00",
                record(3, 2, 1.4, 3.67),
                kills=62,
                deaths=44,
                damagePerRound=158.44,
                performance=58.31,
                timePlayed=6_300_000,
            ),
            day("2026-02-28T00:00:00+00:00", record(0, 0, 0, 0), kills=0, deaths=0),
            day(
                "2026-02-27T00:00:00+00:00",
                record(1, 0, 0.75, 7.0),
                kills=12,
                deaths=16,
                timePlayed=2_190_000,
            ),
        ],
    }


def sample_stat_history() -> dict[str, Any]:
    return {
        "history": {
            "metadata": {"key": "kDRatio", "name": "K/D Ratio"},
            "data": [
                ["2026-03-03T00:00:00+00:00", {"value": 0.871, "displayValue": "0.87"}],
                ["2026-03-01T00:00:00+00:00", {"value": 1.234}],
                "not a pair",
                ["2026-03-02T00:00:00+00:00", {"value": 1.5}],
            ],
        },
        "bestMatches": [
            history_row(MATCH_ID, kdRatio=3.254, kills=26, deaths=8),
            history_row(None, kdRatio=9.0),
            history_row("00000000-0000-4000-8000-00000000000b", kdRatio=2.5, kills=20, deaths=8),
        ],
    }


def sample_rank_history() -> dict[str, Any]:
    return {
        "history": {
            "metadata": {"key": "rank", "name": "Rating"},
            "data": [
                [
                    "2026-03-02T00:00:00+00:00",
                    {"value": ["Radiant", 2_700_450, 212], "metadata": {"rr": 450}},
                ],
                [
                    "2026-03-01T00:00:00+00:00",
                    {"value": ["Immortal 3", 2_600_310, 0], "metadata": {"rr": 310}},
                ],
            ],
        },
        "bestMatches": [],
    }


def sample_distribution() -> list[Any]:
    return [
        {"tier": "Iron 1", "pct": 10.0, "count": 2_000},
        {"tier": "Gold 2", "pct": 50.0, "count": 10_000},
        {"tier": "Diamond 1", "pct": 39.95, "count": 7_990},
        {"tier": "Radiant", "pct": 0.05, "count": 10},
        {"pct": 1.0, "count": 5},
        "junk",
    ]


def sample_leaderboard() -> dict[str, Any]:
    def item(position: int, name: str | None, rating: float, tier: str, wins: int) -> dict:
        return {
            "id": f"hidden-{position}",
            "rank": position,
            "value": rating,
            "owner": {
                "metadata": {"platformUserIdentifier": name},
                "stats": [
                    {"metadata": {"key": "Tier"}, "value": tier},
                    {"metadata": {"key": "Wins"}, "value": wins},
                ],
            },
        }

    return {
        "metadata": {"title": "Competitive Rating"},
        "lastUpdated": "2026-03-02T06:00:00+00:00",
        "items": [
            item(1, JETT, 987.0, "Radiant", 88),
            item(2, None, 951.0, "Radiant", 97),
            item(3, BRIM, 640.0, "Immortal 3", 71),
            {"id": 4, "rank": 4, "value": 600, "owner": {}},
        ],
    }


def sample_agent_insights() -> dict[str, Any]:
    def row(name: str | None, role: str, tier: str, **values: Any) -> dict[str, Any]:
        return {
            "metadata": {"name": name, "className": role, "tier": tier},
            "stats": stats(**values),
        }

    return {
        "insights": [
            row(
                "Sage",
                "Sentinel",
                "A",
                pickRate=8.123,
                wlPercentage=51.26,
                kdRatio=0.934,
                killsPerMatch=13.44,
                deathsPerMatch=14.38,
                assistsPerMatch=8.91,
                damageDeltaPerRound=-3.27,
            ),
            row(None, "Duelist", "C", pickRate=99.0),
            row(
                "Jett",
                "Duelist",
                "S",
                pickRate=14.567,
                wlPercentage=49.84,
                kdRatio=1.083,
                killsPerMatch=17.26,
                deathsPerMatch=15.94,
                assistsPerMatch=3.42,
                damageDeltaPerRound=6.18,
            ),
        ]
    }


def sample_map_insights() -> dict[str, Any]:
    def row(name: str | None, played: float, attackers: float, defenders: float) -> dict:
        return {
            "metadata": {"name": name},
            "stats": stats(
                matchesPlayed=played, attackersKdRatio=attackers, defendersKdRatio=defenders
            ),
        }

    return {
        "insights": [
            row("Split", 9.871, 0.981, 1.019),
            row(None, 50.0, 1.0, 1.0),
            row("Ascent", 14.336, 1.012, 0.988),
        ]
    }


def sample_premier() -> dict[str, Any]:
    def member(owner: str, name: str, **values: Any) -> dict[str, Any]:
        return {
            "type": "player-summary",
            "attributes": {"id": owner},
            "metadata": {"platformUserIdentifier": name},
            "stats": stats(**values),
        }

    def pick(owner: str, agent: str, played: int) -> dict[str, Any]:
        return {
            "type": "player-agent",
            "attributes": {"id": owner},
            "metadata": {"name": agent},
            "stats": stats(matchesPlayed=played),
        }

    def score(roster: str, won: int, lost: int) -> dict[str, Any]:
        return {
            "type": "team-summary",
            "attributes": {"rosterId": roster},
            "stats": stats(roundsWon=won, roundsLost=lost),
        }

    return {
        "id": ROSTER_ID,
        "name": "Test Squad",
        "region": "eu",
        "zoneName": "Central Europe",
        "divisionName": "Elite 2",
        "leagueScore": 675,
        "rank": 12,
        "wins": 8,
        "losses": 4,
        "createdDate": "2025-09-01T12:00:00+00:00",
        "players": [
            {"platformUserIdentifier": CYPHER},
            {"platformUserIdentifier": BRIM, "isOwner": True, "isCaptain": True},
            {"platformUserIdentifier": JETT, "isOwner": False, "isCaptain": True},
            {"platformUserIdentifier": SAGE, "isOwner": False, "isCaptain": False},
        ],
        "playerStats": [
            member("p-left", "Omen Gone#LEFT", matchesPlayed=20, rating=20, peakRating=21),
            pick("p-jett", "Raze", 3),
            pick("p-jett", "Jett", 9),
            pick("p-brim", "Brimstone", 10),
            member("p-sage", SAGE, matchesPlayed=4, matchesWon=2, matchesLost=2, rating=2),
            member(
                "p-brim",
                BRIM,
                matchesPlayed=10,
                matchesWon=7,
                matchesLost=3,
                rating=13,
                peakRating=3,
            ),
            member(
                "p-jett",
                JETT,
                matchesPlayed=12,
                matchesWon=8,
                matchesLost=4,
                roundsWinPct=56.78,
                scorePerRound=244.44,
                damageDeltaPerRound=21.06,
                headshotsPercentage=30.12,
                kAST=74.18,
                trnPerformanceScore=803,
                rating=26,
                peakRating=27,
            ),
        ],
        "teamStats": [{"stats": stats(matchesPlayed=12, matchesWon=8, matchesLost=4, kills=900)}],
        "seasons": [
            {
                "seasonName": "Stage 1",
                "ranking": {
                    "divisionName": "Elite 1",
                    "score": 540,
                    "wins": 5,
                    "losses": 2,
                    "roundWins": 80,
                    "roundLosses": 61,
                    "bracketFinalPlacement": 0,
                },
            },
            {
                "seasonName": "Stage 2",
                "ranking": {
                    "divisionName": "Elite 2",
                    "score": 675,
                    "wins": 3,
                    "losses": 2,
                    "roundWins": 55,
                    "roundLosses": 49,
                    "bracketFinalPlacement": 3,
                },
            },
        ],
        "recentMatches": [
            {
                "matchId": "00000000-0000-4000-8000-0000000000c1",
                "matchDate": "2026-02-21T19:00:00+00:00",
                "opponentName": "Other Squad",
                "won": True,
                "leaguePoints": 600,
                "leaguePointsDelta": 100,
                "metadata": {"mapName": "Split"},
                "segments": [score("someone-else", 7, 13), score(ROSTER_ID, 13, 7)],
            },
            {
                "matchId": "00000000-0000-4000-8000-0000000000c2",
                "matchDate": "2026-02-28T19:00:00+00:00",
                "opponentName": "Third Squad",
                "won": False,
                "leaguePoints": 575,
                "leaguePointsDelta": -25,
                "metadata": {"mapName": "Ascent"},
                "segments": [score(ROSTER_ID, 11, 13), score("third-roster", 13, 11)],
            },
        ],
    }


def sample_game_data() -> dict[str, Any]:
    return {
        "agents": [
            {
                "name": "Sage",
                "uuid": "agent-sage",
                "role": {"displayName": "Sentinel"},
                "abilities": [
                    {"slot": "Ability1", "displayName": "Slow Orb"},
                    {"slot": "Ability2", "displayName": "Healing Orb"},
                    {"slot": "Grenade", "displayName": "Barrier Orb"},
                    {"slot": "Ultimate", "displayName": "Resurrection"},
                    {"slot": "Passive", "displayName": "Not an ability slot"},
                ],
            },
            {"name": "Jett", "uuid": "agent-jett", "role": "Duelist", "abilities": []},
            {"uuid": "agent-without-name"},
        ],
        "maps": [{"name": "Ascent", "uuid": "map-ascent"}, {"uuid": "map-without-name"}],
        "weapons": [
            {
                "categoryName": "Rifles",
                "weapons": [{"name": "Vandal", "cost": 2900}, {"name": "Phantom", "cost": 2900}],
            },
            {"categoryName": "Sidearms", "weapons": [{"name": "Classic", "cost": 0}, {"cost": 1}]},
        ],
        "seasons": [
            {
                "shortName": "V25",
                "seasons": [
                    {
                        "id": "act-25-6",
                        "shortName": "ACT 6",
                        "startTime": "2025-10-29T00:00:00+00:00",
                        "endTime": "2026-01-07T00:00:00+00:00",
                    }
                ],
            },
            {
                "shortName": "V26",
                "seasons": [
                    {
                        "id": "act-26-4",
                        "shortName": "ACT 4",
                        "startTime": "2026-01-07T00:00:00+00:00",
                        "endTime": "2026-02-25T00:00:00+00:00",
                    },
                    {
                        "id": ACT_ID,
                        "shortName": "ACT 5",
                        "startTime": "2026-02-25T00:00:00+00:00",
                        "endTime": "2026-04-15T00:00:00+00:00",
                    },
                    {"shortName": "ACT 9"},
                ],
            },
        ],
        "playlists": [
            {"value": "competitive", "label": "Competitive"},
            {"value": "premier"},
            {"label": "No value"},
        ],
    }
