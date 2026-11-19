"""Statistics derived from match scoreboards: who a player queues with and how it goes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from models import MatchDetails, MatchEntry, MatchPlayer, RoundPlayer, SplitStats
from scraper.utils import same_player

# Counts that are added up across matches.
_COUNTED = (
    "kills",
    "deaths",
    "assists",
    "rounds_won",
    "first_kills",
    "first_deaths",
    "team_first_deaths",
    "rounds_survived",
    "deaths_traded",
    "trade_kills",
    "clutches",
    "clutches_lost",
    "multi_kills",
    "double_kills",
    "triple_kills",
    "quadra_kills",
    "aces",
    "plants",
    "defuses",
)
# Per-round or per-match values that are averaged, weighted by rounds played.
_AVERAGED = (
    "acs",
    "adr",
    "hs_pct",
    "kast",
    "damage_delta_per_round",
    "econ_rating",
    "avg_loadout_value",
    "tracker_score",
)
# Rate -> the count it expresses as a share of rounds.
_PER_ROUND = {
    "round_win_rate": "rounds_won",
    "first_kill_rate": "first_kills",
    "first_death_rate": "first_deaths",
    "team_first_death_rate": "team_first_deaths",
    "survival_rate": "rounds_survived",
}
_OTHER_RATES = ("entry_success_rate", "deaths_traded_rate", "clutch_win_rate")
_BROKEN_DOWN = ("clutches_by_size", "ability_casts", "weapon_kills")
_SIDES = ("attack", "defense")
_BUY_ORDER = ("pistol", "eco", "semi", "full")


def find_player(
    match: MatchDetails, riot_id: str, entry: MatchEntry | None = None
) -> MatchPlayer | None:
    """Locate the player's scoreboard row.

    Scoreboards keep the name used at the time, so after a Riot ID change the
    row is recognised by the stat line from the player's match history instead.
    """
    row = next((row for row in match.players if same_player(row.riot_id, riot_id)), None)
    if row is None and entry is not None and entry.agent and entry.kills is not None:
        line = (entry.agent, entry.kills, entry.deaths, entry.assists)
        same = [r for r in match.players if (r.agent, r.kills, r.deaths, r.assists) == line]
        row = same[0] if len(same) == 1 else None
    return row


def team_won(match: MatchDetails, team: str | None) -> bool | None:
    """True or False for a decided match, None for a draw or an unknown result."""
    own = next((entry for entry in match.teams if entry.team == team), None)
    if own is None or own.won is None:
        return None
    if not own.won and not any(entry.won for entry in match.teams):
        return None
    return own.won


def _known(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


@dataclass
class _Mean:
    total: float = 0.0
    weight: float = 0.0

    def add(self, value: float | None, weight: float) -> None:
        if value is not None:
            self.total += value * weight
            self.weight += weight

    @property
    def value(self) -> float | None:
        return round(self.total / self.weight, 1) if self.weight else None

    @property
    def whole(self) -> int | None:
        return round(self.total / self.weight) if self.weight else None


@dataclass
class _Count:
    """A total that stays None until at least one match reports the stat."""

    total: int = 0
    known: bool = False

    def add(self, value: int | None) -> None:
        if value is not None:
            self.total += value
            self.known = True

    @property
    def value(self) -> int | None:
        return self.total if self.known else None


@dataclass
class _Rate:
    """A part as a percentage of its whole, over the matches that report both."""

    part: float = 0.0
    whole: float = 0.0

    def add(self, part: float | None, whole: float | None) -> None:
        if part is not None and whole:
            self.part += part
            self.whole += whole

    @property
    def value(self) -> float | None:
        return round(100 * self.part / self.whole, 1) if self.whole else None


@dataclass
class _Tally:
    """Running totals over scoreboard rows, or over one side or kind of buy of them."""

    games: int = 0
    wins: int = 0
    losses: int = 0
    rounds: int = 0
    counts: dict[str, _Count] = field(default_factory=lambda: {name: _Count() for name in _COUNTED})
    means: dict[str, _Mean] = field(default_factory=lambda: {name: _Mean() for name in _AVERAGED})
    rates: dict[str, _Rate] = field(
        default_factory=lambda: {name: _Rate() for name in (*_PER_ROUND, *_OTHER_RATES)}
    )
    breakdowns: dict[str, Counter[str]] = field(
        default_factory=lambda: {name: Counter() for name in _BROKEN_DOWN}
    )

    def add(
        self, row: MatchPlayer | SplitStats, rounds: int | None, won: bool | None = None
    ) -> None:
        def get(name: str) -> Any:
            return getattr(row, name, None)

        self.games += 1
        self.wins += won is True
        self.losses += won is False
        self.rounds += rounds or 0
        for name, count in self.counts.items():
            count.add(get(name))
        # Weighted by match length so long games count for more.
        for name, mean in self.means.items():
            mean.add(get(name), rounds or 1)
        # Shares of rounds, so the totals of whoever played more games do not decide it.
        for name, counted in _PER_ROUND.items():
            self.rates[name].add(get(counted), rounds)
        first_kills, first_deaths = row.first_kills, row.first_deaths
        if first_kills is not None and first_deaths is not None:
            self.rates["entry_success_rate"].add(first_kills, first_kills + first_deaths)
        clutches, lost = get("clutches"), get("clutches_lost")
        if clutches is not None and lost is not None:
            self.rates["clutch_win_rate"].add(clutches, clutches + lost)
        self.rates["deaths_traded_rate"].add(row.deaths_traded, row.deaths)
        for name, counter in self.breakdowns.items():
            counter.update(get(name) or {})

    @property
    def kd(self) -> float | None:
        kills, deaths = self.counts["kills"].value, self.counts["deaths"].value
        if kills is None or deaths is None:
            return None
        return round(kills / max(deaths, 1), 2)

    @property
    def win_rate(self) -> float | None:
        return round(100 * self.wins / self.games, 1) if self.games else None

    def summary(self, *, split: bool = False) -> dict[str, Any]:
        """Totals and rates, without the stats that no row reported.

        split leaves out the match record, which one side or kind of buy does not have.
        """
        count = {name: total.value for name, total in self.counts.items()}
        mean = {name: total.value for name, total in self.means.items()}
        rate = {name: total.value for name, total in self.rates.items()}
        record: dict[str, Any] = {}
        if not split:
            record = {
                "games": self.games,
                "wins": self.wins,
                "losses": self.losses,
                "win_rate": self.win_rate,
            }
        return _known(
            {
                **record,
                "kills": count["kills"],
                "deaths": count["deaths"],
                "assists": count["assists"],
                "kd": self.kd,
                "acs": mean["acs"],
                "adr": mean["adr"],
                "hs_pct": mean["hs_pct"],
                "kast": mean["kast"],
                "damage_delta_per_round": mean["damage_delta_per_round"],
                "rounds": self.rounds or None,
                "rounds_won": count["rounds_won"],
                "round_win_rate": rate["round_win_rate"],
                "first_kills": count["first_kills"],
                "first_deaths": count["first_deaths"],
                "first_kill_rate": rate["first_kill_rate"],
                "first_death_rate": rate["first_death_rate"],
                "entry_success_rate": rate["entry_success_rate"],
                "team_first_deaths": count["team_first_deaths"],
                "team_first_death_rate": rate["team_first_death_rate"],
                "rounds_survived": count["rounds_survived"],
                "survival_rate": rate["survival_rate"],
                "deaths_traded": count["deaths_traded"],
                "deaths_traded_rate": rate["deaths_traded_rate"],
                "trade_kills": count["trade_kills"],
                "clutches": count["clutches"],
                "clutches_lost": count["clutches_lost"],
                "clutch_win_rate": rate["clutch_win_rate"],
                "clutches_by_size": dict(sorted(self.breakdowns["clutches_by_size"].items()))
                or None,
                "multi_kills": count["multi_kills"],
                "double_kills": count["double_kills"],
                "triple_kills": count["triple_kills"],
                "quadra_kills": count["quadra_kills"],
                "aces": count["aces"],
                "plants": count["plants"],
                "defuses": count["defuses"],
                "econ_rating": mean["econ_rating"],
                "avg_loadout_value": self.means["avg_loadout_value"].whole,
                "tracker_score": self.means["tracker_score"].whole,
                "ability_casts": dict(self.breakdowns["ability_casts"]) or None,
            }
        )

    def brief(self) -> dict[str, Any]:
        return _known(
            {
                "games": self.games,
                "wins": self.wins,
                "win_rate": self.win_rate,
                "kd": self.kd,
                "acs": self.means["acs"].value,
            }
        )


@dataclass
class _Record:
    """One player's totals: overall, per side and per kind of buy."""

    overall: _Tally = field(default_factory=_Tally)
    sides: dict[str, _Tally] = field(default_factory=dict)
    buys: dict[str, _Tally] = field(default_factory=dict)
    tags: Counter[str] = field(default_factory=Counter)

    def add(self, row: MatchPlayer, rounds: int | None, won: bool | None) -> None:
        self.overall.add(row, rounds, won)
        for side in _SIDES:
            split = getattr(row, side)
            if split:
                self.sides.setdefault(side, _Tally()).add(split, split.rounds)
        for kind, split in (row.buys or {}).items():
            self.buys.setdefault(kind, _Tally()).add(split, split.rounds)
        self.tags.update(row.tags or [])

    def view(self, detailed: bool) -> dict[str, Any]:
        data = self.overall.summary()
        if detailed:
            extra = {
                **{side: tally.summary(split=True) for side, tally in self.sides.items()},
                "buys": {kind: tally.summary(split=True) for kind, tally in self.buys.items()},
                "weapon_kills": dict(self.overall.breakdowns["weapon_kills"].most_common()),
                "tags": dict(self.tags.most_common()),
            }
            data.update({key: value for key, value in extra.items() if value})
        return data


@dataclass
class _Teammate:
    riot_id: str
    record: _Record = field(default_factory=_Record)
    by_map: dict[str, _Tally] = field(default_factory=dict)
    agents: Counter[str] = field(default_factory=Counter)
    party_games: int = 0
    account_level: int | None = None
    # The analysed player's own line in the matches shared with this teammate.
    player_with: _Tally = field(default_factory=_Tally)


def teammate_stats(
    riot_id: str,
    matches: Sequence[MatchDetails],
    top: int = 10,
    entries: Mapping[str, MatchEntry] | None = None,
    detailed: bool = False,
    most_played: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Aggregate the players who shared a team with riot_id across the given matches.

    Teammates are ranked by games played together in those matches. entries
    maps match IDs to the player's history rows, see find_player. detailed
    adds each player's numbers per side and per kind of buy, their kills per
    weapon and tracker.gg's match labels. most_played is tracker.gg's own
    list of the player's most played teammates, most played first: a
    teammate on it gets that position as most_played_rank.
    """
    player = _Record()
    teammates: dict[str, _Teammate] = {}
    # (teammate keys, the player's row, rounds, result) per analysed match.
    appearances: list[tuple[set[str], MatchPlayer, int | None, bool | None]] = []

    for match in matches:
        me = find_player(match, riot_id, (entries or {}).get(match.match_id))
        if me is None or me.team is None:
            continue
        won = team_won(match, me.team)
        player.add(me, match.rounds, won)

        present: set[str] = set()
        for row in match.players:
            if row.team != me.team or row is me or row.riot_id == "Unknown":
                continue
            key = row.riot_id.casefold()
            present.add(key)
            mate = teammates.setdefault(key, _Teammate(row.riot_id))
            mate.record.add(row, match.rounds, won)
            mate.player_with.add(me, match.rounds, won)
            mate.by_map.setdefault(match.map or "Unknown", _Tally()).add(row, match.rounds, won)
            if row.agent:
                mate.agents[row.agent] += 1
            if me.party_id is not None and row.party_id == me.party_id:
                mate.party_games += 1
            if row.account_level is not None:
                mate.account_level = max(mate.account_level or 0, row.account_level)
        appearances.append((present, me, match.rounds, won))

    def games(mate: _Teammate) -> int:
        return mate.record.overall.games

    ranked = sorted(
        teammates.items(),
        key=lambda item: (games(item[1]), item[1].party_games, item[1].record.overall.wins),
        reverse=True,
    )
    standing = {name.casefold(): place for place, name in enumerate(most_played or [], 1)}

    rows: list[dict[str, Any]] = []
    for rank, (key, mate) in enumerate(ranked[:top], 1):
        without = _Tally()
        for present, me, rounds, won in appearances:
            if key not in present:
                without.add(me, rounds, won)
        rows.append(
            _known(
                {
                    "riot_id": mate.riot_id,
                    "rank": rank,
                    "most_played_rank": standing.get(key),
                    "account_level": mate.account_level,
                    "games_together": games(mate),
                    "games_in_party": mate.party_games,
                    **{k: v for k, v in mate.record.view(detailed).items() if k != "games"},
                    "agents": dict(mate.agents.most_common()),
                    "by_map": {name: tally.brief() for name, tally in sorted(mate.by_map.items())},
                    "your_record_with": mate.player_with.brief(),
                    "your_record_without": without.brief(),
                }
            )
        )

    return {
        "matches_analyzed": player.overall.games,
        "your_stats": player.view(detailed),
        "teammates_seen": len(teammates),
        "teammates": rows,
    }


def team_buy(lines: Sequence[RoundPlayer]) -> str | None:
    """The buy type most of a team was on in a round, the bigger one on a tie."""
    counts = Counter(line.buy for line in lines if line.buy in _BUY_ORDER)
    if not counts:
        return None
    return max(counts, key=lambda kind: (counts[kind], _BUY_ORDER.index(kind)))


@dataclass
class _Rounds:
    """A number of rounds and how many of them the team won."""

    played: int = 0
    won: int = 0

    def add(self, won: bool) -> None:
        self.played += 1
        self.won += won

    def view(self) -> dict[str, Any]:
        rate = round(100 * self.won / self.played, 1) if self.played else None
        return _known({"rounds": self.played, "won": self.won, "win_rate": rate})


def round_stats(
    riot_id: str,
    matches: Sequence[MatchDetails],
    entries: Mapping[str, MatchEntry] | None = None,
) -> dict[str, Any]:
    """How the rounds of the given matches went for riot_id's team.

    Rounds and round wins overall and by side, with and without a spike plant,
    per site, on pistol rounds and the round after, by who got the first kill,
    by the buy of both teams and by how the round ended. "you" has the
    player's own opening duels and the timing and range of their fights.
    """
    total = _Rounds()
    sides = {side: _Rounds() for side in _SIDES}
    planted = {side: _Rounds() for side in _SIDES}
    not_planted = {side: _Rounds() for side in _SIDES}
    sites: dict[str, dict[str, _Rounds]] = {side: {} for side in _SIDES}
    pistols, after_win, after_loss = _Rounds(), _Rounds(), _Rounds()
    opening = {"first_kill": _Rounds(), "first_death": _Rounds()}
    own = {"first_kill": _Rounds(), "first_death": _Rounds()}
    economy: dict[str, _Rounds] = {}
    endings: dict[str, Counter[str]] = {"won": Counter(), "lost": Counter()}
    kill_time, death_time, kill_range, death_range = _Mean(), _Mean(), _Mean(), _Mean()
    killed_by: Counter[str] = Counter()
    analysed = without_rounds = 0

    for match in matches:
        me = find_player(match, riot_id, (entries or {}).get(match.match_id))
        if me is None or me.team is None:
            continue
        if not match.round_log:
            without_rounds += 1
            continue
        analysed += 1
        team_of = {row.riot_id: row.team for row in match.players}
        pistol_won: dict[int, bool] = {}
        for entry in match.round_log:
            if entry.winner is None:
                continue
            won = entry.winner == me.team
            total.add(won)
            endings["won" if won else "lost"][entry.ending or "Unknown"] += 1
            if entry.attackers is not None:
                side = "attack" if entry.attackers == me.team else "defense"
                sides[side].add(won)
                (planted if entry.plant else not_planted)[side].add(won)
                if entry.plant and entry.plant.site:
                    sites[side].setdefault(entry.plant.site, _Rounds()).add(won)

            lines = entry.players or []
            mine = next((line for line in lines if line.riot_id == me.riot_id), None)
            if mine and mine.buy == "pistol":
                pistols.add(won)
                pistol_won[entry.round] = won
            pistol_before = pistol_won.get(entry.round - 1)
            if pistol_before is not None:
                (after_win if pistol_before else after_loss).add(won)
            ours = team_buy([line for line in lines if team_of.get(line.riot_id) == me.team])
            theirs = team_buy([line for line in lines if team_of.get(line.riot_id) != me.team])
            if ours and theirs:
                economy.setdefault(f"{ours} vs {theirs}", _Rounds()).add(won)

            # Suicides and kills on a teammate are in the log but are not fights.
            fights = [
                kill
                for kill in entry.kills or []
                if team_of.get(kill.killer) != team_of.get(kill.victim)
            ]
            if fights:
                first = fights[0]
                ours_first = team_of.get(first.killer) == me.team
                opening["first_kill" if ours_first else "first_death"].add(won)
                if first.killer == me.riot_id:
                    own["first_kill"].add(won)
                if first.victim == me.riot_id:
                    own["first_death"].add(won)
            for kill in fights:
                if kill.killer == me.riot_id:
                    kill_time.add(kill.time, 1)
                    kill_range.add(kill.distance_m, 1)
                if kill.victim == me.riot_id:
                    death_time.add(kill.time, 1)
                    death_range.add(kill.distance_m, 1)
                    killed_by[kill.weapon or "Unknown"] += 1

    def side_view(side: str) -> dict[str, Any]:
        by_site = {site: tally.view() for site, tally in sorted(sites[side].items())}
        return {
            **sides[side].view(),
            "spike_planted": planted[side].view(),
            "spike_not_planted": not_planted[side].view(),
            **({"by_site": by_site} if by_site else {}),
        }

    by_size = sorted(economy.items(), key=lambda item: item[1].played, reverse=True)
    result: dict[str, Any] = {
        "matches_analyzed": analysed,
        "rounds": total.view(),
        "attack": side_view("attack"),
        "defense": side_view("defense"),
        "pistol_rounds": pistols.view(),
        "after_pistol_win": after_win.view(),
        "after_pistol_loss": after_loss.view(),
        "opening": {name: tally.view() for name, tally in opening.items()},
        "economy": {matchup: tally.view() for matchup, tally in by_size},
        "endings": {outcome: dict(counts.most_common()) for outcome, counts in endings.items()},
        "you": _known(
            {
                "first_kill": own["first_kill"].view(),
                "first_death": own["first_death"].view(),
                "avg_kill_time": kill_time.value,
                "avg_death_time": death_time.value,
                "avg_kill_distance_m": kill_range.value,
                "avg_death_distance_m": death_range.value,
                "killed_by": dict(killed_by.most_common(8)) or None,
            }
        ),
    }
    if without_rounds:
        result["matches_without_round_data"] = without_rounds
    return result
