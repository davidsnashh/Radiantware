"""Made-up matches for the tests. Every player, ID and number in here is invented."""

from __future__ import annotations

from models import (
    Kill,
    MatchDetails,
    MatchEntry,
    MatchPlayer,
    MatchTeam,
    Round,
    RoundPlayer,
    Shots,
    SpikeEvent,
    SplitStats,
)

ME = "Brim Stone#TST"
JETT = "Jett Lag#0001"
SAGE = "Sage Advice#HEAL"
OMEN = "Omen Clature#SHDW"
VIPER = "Vy Pear#ACID"
SOVA = "Sova Reign#DART"

SPENT = {"pistol": 800, "eco": 400, "semi": 2500, "full": 4100}
# What a loadout is worth beyond the credits spent on it in the round.
CARRIED_OVER = 500


def match_id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def player(
    riot_id: str,
    team: str | None,
    kills: int | None = None,
    deaths: int | None = None,
    assists: int | None = None,
    **stats,
) -> MatchPlayer:
    return MatchPlayer(
        riot_id=riot_id, team=team, kills=kills, deaths=deaths, assists=assists, **stats
    )


def match(
    number: int,
    map_name: str,
    rounds: int,
    winner: str | None,
    players: list[MatchPlayer],
    **extra,
) -> MatchDetails:
    """Red against Blue. winner=None is a draw."""
    teams = [MatchTeam(team=team, won=team == winner) for team in ("Red", "Blue")]
    return MatchDetails(
        match_id=match_id(number),
        map=map_name,
        rounds=rounds,
        teams=teams,
        players=players,
        **extra,
    )


def scoreboards() -> list[MatchDetails]:
    """Four matches of ME: a win, a loss and a win on Red, then a draw on Blue.

    JETT plays the first three, SAGE the first and third, OMEN the second and
    fourth. JETT's third line has nothing but kills, deaths and assists.
    """
    first = match(
        1,
        "Ascent",
        20,
        "Red",
        [
            player(
                ME,
                "Red",
                20,
                10,
                5,
                agent="Brimstone",
                party_id="p1",
                acs=250,
                adr=160,
                first_kills=3,
                first_deaths=1,
                plants=4,
            ),
            player(
                JETT,
                "Red",
                15,
                15,
                3,
                agent="Jett",
                party_id="p1",
                account_level=82,
                acs=200,
                first_kills=4,
                first_deaths=2,
                deaths_traded=5,
                clutches=1,
                clutches_lost=1,
                clutches_by_size={"1v2": 1},
                weapon_kills={"Vandal": 10, "Sheriff": 5},
                tags=["Top Frag", "Trader"],
                attack=SplitStats(rounds=12, rounds_won=7, kills=9, deaths=8, acs=210),
                defense=SplitStats(rounds=8, rounds_won=6, kills=6, deaths=7, acs=190),
                buys={
                    "pistol": SplitStats(rounds=2, kills=3, deaths=1),
                    "full": SplitStats(rounds=18, kills=12, deaths=14),
                },
            ),
            player(
                SAGE,
                "Red",
                10,
                12,
                12,
                agent="Sage",
                acs=150,
                first_kills=0,
                first_deaths=0,
                clutches=0,
                clutches_lost=0,
                rounds_survived=8,
            ),
            player(VIPER, "Blue", 14, 15, 4, agent="Viper", acs=190),
            player(SOVA, "Blue", 12, 16, 9, agent="Sova", acs=170),
        ],
        duration_minutes=34.5,
    )
    second = match(
        2,
        "Bind",
        24,
        "Blue",
        [
            player(ME, "Red", 12, 18, 4, agent="Brimstone", party_id="p2", acs=150, adr=100),
            player(
                JETT,
                "Red",
                24,
                12,
                6,
                agent="Jett",
                party_id="p2",
                account_level=80,
                acs=260,
                first_kills=6,
                first_deaths=6,
                deaths_traded=6,
                clutches=2,
                clutches_lost=0,
                clutches_by_size={"1v2": 1, "1v1": 1},
                weapon_kills={"Vandal": 14, "Operator": 10},
                tags=["Top Frag"],
                attack=SplitStats(rounds=12, rounds_won=5, kills=14, deaths=5, acs=270),
                defense=SplitStats(rounds=12, rounds_won=6, kills=10, deaths=7, acs=250),
                buys={
                    "pistol": SplitStats(rounds=2, kills=1, deaths=2),
                    "eco": SplitStats(rounds=4, kills=3, deaths=4),
                    "full": SplitStats(rounds=18, kills=20, deaths=6),
                },
            ),
            player(OMEN, "Red", 14, 14, 7, agent="Omen", party_id="solo", acs=180),
            player(VIPER, "Blue", 20, 16, 5, agent="Viper"),
            player(SOVA, "Blue", 24, 14, 8, agent="Sova"),
        ],
    )
    third = match(
        3,
        "Ascent",
        16,
        "Red",
        [
            player(ME, "Red", 16, 8, 2, agent="Brimstone", acs=300),
            player(JETT.upper(), "Red", 8, 16, 1, agent="Raze", weapon_kills={"Phantom": 8}),
            player(
                SAGE,
                "Red",
                6,
                6,
                9,
                agent="Sage",
                acs=195,
                first_kills=0,
                first_deaths=0,
                rounds_survived=10,
            ),
            player(VIPER, "Blue", 15, 15, 2, agent="Viper"),
            player(SOVA, "Blue", 15, 15, 3, agent="Sova"),
        ],
    )
    fourth = match(
        4,
        "Haven",
        30,
        None,
        [
            player(ME, "Blue", 24, 24, 10, agent="Brimstone", party_id="p4", acs=200),
            player(
                OMEN, "Blue", 30, 20, 5, agent="Omen", party_id="p4", account_level=150, acs=240
            ),
            player("Unknown", "Blue", 5, 5, 0),
            player(VIPER, "Red", 25, 27, 6, agent="Viper"),
            player(SOVA, "Red", 24, 27, 7, agent="Sova"),
        ],
    )
    return [first, second, third, fourth]


def history_entry() -> MatchEntry:
    """ME's history row for the first of scoreboards()."""
    return MatchEntry(
        match_id=match_id(1),
        map="Ascent",
        mode="Competitive",
        result="victory",
        rounds_won=13,
        rounds_lost=7,
        agent="Brimstone",
        kills=20,
        deaths=10,
        assists=5,
        acs=250,
        combat_score=5000,
        tracker_score=700,
        last_deaths=2,
        suicides=0,
        shots_dealt=Shots(head=10, body=30, leg=2),
    )


def _lines(buys: dict[str, str]) -> list[RoundPlayer]:
    return [
        RoundPlayer(
            riot_id=riot_id,
            buy=buy,
            spent=SPENT[buy],
            loadout_value=SPENT[buy] + CARRIED_OVER,
        )
        for riot_id, buy in buys.items()
    ]


def _kills(*rows: tuple[float, str, str, str, float | None]) -> list[Kill]:
    return [
        Kill(time=time, killer=killer, victim=victim, weapon=weapon, distance_m=distance)
        for time, killer, victim, weapon, distance in rows
    ]


def _buys(me: str, jett: str, viper: str, sova: str) -> dict[str, str]:
    return {ME: me, JETT: jett, VIPER: viper, SOVA: sova}


def round_match() -> MatchDetails:
    """ME and JETT (Red) against VIPER and SOVA (Blue), two against two.

    Red attacks in rounds 1 to 4 and defends in 5 to 8. Red wins rounds 1, 2,
    6 and 7. Round 4 has a suicide and round 8 a team kill, neither of which
    is a fight. Round 9 was never decided.
    """
    log = [
        Round(
            round=1,
            winner="Red",
            ending="Elimination",
            attackers="Red",
            players=_lines(_buys("pistol", "pistol", "pistol", "pistol")),
            kills=_kills((10, ME, VIPER, "Classic", None), (20, JETT, SOVA, "Ghost", 15.0)),
        ),
        Round(
            round=2,
            winner="Red",
            ending="Detonate",
            attackers="Red",
            plant=SpikeEvent(by=ME, site="A", time=35.0, at=[0.4, 0.6]),
            detonated_at=80.0,
            players=_lines(_buys("full", "full", "eco", "eco")),
            kills=[
                Kill(time=15, killer=SOVA, victim=JETT, weapon="Sheriff", distance_m=18.0),
                Kill(
                    time=30,
                    killer=ME,
                    victim=SOVA,
                    weapon="Vandal",
                    distance_m=20.0,
                    assists=[JETT],
                    killer_at=[0.5, 0.5],
                    victim_at=[0.6, 0.4],
                ),
                Kill(time=40, killer=ME, victim=VIPER, weapon="Vandal", distance_m=30.0),
            ],
        ),
        Round(
            round=3,
            winner="Blue",
            ending="Defuse",
            attackers="Red",
            plant=SpikeEvent(by=JETT, site="B", time=40.0),
            defuse=SpikeEvent(by=VIPER, site="B", time=75.0),
            players=_lines(_buys("full", "full", "semi", "full")),
            kills=_kills((8, VIPER, ME, "Vandal", 25.0), (30, SOVA, JETT, "Phantom", 9.0)),
        ),
        Round(
            round=4,
            winner="Blue",
            ending="Elimination",
            attackers="Red",
            players=_lines(_buys("eco", "eco", "full", "full")),
            kills=_kills((5, JETT, JETT, "Fall Damage", None), (12, VIPER, ME, "Operator", 40.0)),
        ),
        Round(
            round=5,
            winner="Blue",
            ending="Detonate",
            attackers="Blue",
            plant=SpikeEvent(by=VIPER, site="A", time=30.0),
            players=_lines(_buys("pistol", "pistol", "pistol", "pistol")),
            kills=_kills((18, SOVA, ME, "Ghost", 10.0), (25, VIPER, JETT, "Classic", 5.0)),
        ),
        Round(
            round=6,
            winner="Red",
            ending="Defuse",
            attackers="Blue",
            plant=SpikeEvent(by=SOVA, site="A", time=28.0),
            defuse=SpikeEvent(by=ME, site="A", time=70.0, at=[0.3, 0.7]),
            players=_lines(_buys("semi", "semi", "full", "full")),
            kills=_kills((25, JETT, VIPER, "Spectre", 11.0), (50, ME, SOVA, "Spectre", 8.0)),
        ),
        Round(
            round=7,
            winner="Red",
            ending="Elimination",
            attackers="Blue",
            players=_lines(_buys("full", "full", "full", "full")),
            kills=_kills((14, ME, VIPER, "Vandal", 30.0), (16, ME, SOVA, "Vandal", 20.0)),
        ),
        Round(
            round=8,
            winner="Blue",
            ending="Detonate",
            attackers="Blue",
            plant=SpikeEvent(by=VIPER, site="B", time=33.0),
            players=_lines(_buys("full", "full", "full", "full")),
            kills=_kills((22, ME, JETT, "Vandal", 3.0), (44, SOVA, ME, "Vandal", None)),
        ),
        Round(
            round=9,
            attackers="Blue",
            kills=_kills((1, ME, VIPER, "Vandal", 99.0)),
        ),
    ]
    return match(
        10,
        "Split",
        8,
        None,
        [
            player(ME, "Red", 6, 4, 1, agent="Brimstone"),
            player(JETT, "Red", 2, 5, 1, agent="Jett"),
            player(VIPER, "Blue", 3, 4, 0, agent="Viper"),
            player(SOVA, "Blue", 4, 4, 0, agent="Sova"),
        ],
        round_log=log,
    )


def short_round_match() -> MatchDetails:
    """Three bare rounds with ME on Blue, the last one without a known side or ending."""
    log = [
        Round(round=1, winner="Blue", ending="Elimination", attackers="Blue"),
        Round(round=2, winner="Red", ending="Time", attackers="Blue"),
        Round(round=3, winner="Blue"),
    ]
    return match(
        11,
        "Split",
        3,
        "Blue",
        [
            player(ME.lower(), "Blue", 2, 1, 0, agent="Brimstone"),
            player(SAGE, "Blue", 1, 1, 1, agent="Sage"),
            player(VIPER, "Red", 1, 2, 0, agent="Viper"),
            player(SOVA, "Red", 1, 1, 0, agent="Sova"),
        ],
        round_log=log,
    )
