# Sleeper Fantasy Agent

A read-only AI agent for Sleeper fantasy football. It watches your leagues, computes optimal lineups, and explains swaps. It never changes your rosters.

Built as a portfolio project: real API, deterministic optimizer, agent loop.

## Why this exists

Managing 8 fantasy leagues (5 Sleeper + 3 ESPN) means missing bye-week starters and leaving points on the bench. General AI can optimize one lineup when you ask. This agent is proactive: it checks all leagues, flags urgent actions, and explains them in context.

## What it does (Layer 1 + 2)

- Pulls all Sleeper leagues for a username via the public Sleeper API (no password)
- Computes optimal lineup per league for a given week using Sleeper projections
  - Handles PPR / Half-PPR / Standard, FLEX, SUPER_FLEX, K, DEF, Best Ball
  - Treats Out / IR / Suspended as 0 projection (Sleeper projections can be stale)
  - Flags bye-week starters (no projection) and Out/IR starters
- Sunday digest: one page, all leagues, total gap, urgent actions, suggested swaps (read-only)
- Start/sit: compare two players you own, with projections + injury flags

## Example - Week 7, 2026 (IMthatGuyton, 5 Sleeper leagues)

See `example_digest_week7.md` for full output.

- Rodger Goodells Epstein List: Current 114.2 -> Optimal 140.9 (+26.7). Lawrence (bye) -> Burrow, Wilson -> Smith
- Multiverse: +23.9 gap, 5 starters on bye / Out
- UW Practice Squad: +31.0 gap, 4 starters on bye
- Euroamerican Cup: +39.1 gap, Daniels (bye) -> Murray, Washington (bye) -> Brown
- Elite SFBB Dynasty: Best Ball, no action needed

Total gap across leagues: +121.7 projected points, 10 urgent starters. That is the problem this agent solves.

## Architecture

```
perceive (Sleeper API: leagues, rosters, players, projections)
  -> reason (deterministic optimizer: greedy by scarcity, FLEX / SUPER_FLEX aware)
  -> explain (template + injury / bye flags, LLM only for wording, never for numbers)
  -> act (suggest only, read-only, user taps swaps in Sleeper app)
```

Files:
- `sleeper_optimizer.py` - optimizer + CLI, read-only
- `agent.py` - digest + start/sit chat logic, read-only
- `example_digest_week7.md` - real output for Week 7

## Usage

```bash
python3 sleeper_optimizer.py --username IMthatGuyton --week 7 --season 2026
python3 agent.py IMthatGuyton 7
```

No API key needed. Sleeper API is public. No roster changes.

## Roadmap

- Layer 1 (done): Optimizer
- Layer 2 (done): Digest + start/sit chat
- Layer 3: Waiver wire - top free agents by team need
- Layer 4: Trade finder - win-win trades that raise both starters
- Layer 5: Memory + learning - preferences, track if calls were right
- Later: ESPN (beta, via espn_api), Discord / SMS alerts, auto-sub opt-in

## Safety

- READ ONLY. Only GET requests to Sleeper. No POST, no roster changes.
- Projections are noisy. Agent shows projection + injury flag, never promises wins.
- Out / IR treated as 0. Bye-week players have no projection.

## What I learned building this

- Sleeper projections endpoint is `/projections/nfl/regular/{season}/{week}`, not `/projections/nfl/{season}/{week}`
- Stale projections for Out players must be zeroed, or the optimizer will start injured players
- Multi-league triage is the real value, not single-lineup optimization. One league is easy, 5 leagues is where you miss things.
