"""
Sleeper Fantasy Agent - Layer 3: Waiver Wire
Read-only. Finds top free agents by team need for next week.

Logic:
- Free agent = player not rostered in this league
- Use next-week projections (Week 8 when current is Week 7)
- Need-aware: QB is only a need in Superflex / 2QB, or if your QBs are injured / on bye.
  In 1QB, QB FAs are deprioritized even if raw projection is high.
- Drop candidate = lowest-projected bench player (redraft) - for dynasty, flag "check keeper value"
- Upgrade = FA projection > weakest starter at same position (or > bench player at FLEX)
"""
import urllib.request, json
from sleeper_optimizer import get, optimize_lineup

def get_waiver_targets(username, season="2026", current_week=7, top_n=5):
    next_week = current_week + 1
    user = get(f"https://api.sleeper.app/v1/user/{username}")
    uid = user["user_id"]
    leagues = get(f"https://api.sleeper.app/v1/user/{uid}/leagues/nfl/{season}")
    players = get("https://api.sleeper.app/v1/players/nfl")
    proj = get(f"https://api.sleeper.app/v1/projections/nfl/regular/{season}/{next_week}")

    results = {}
    for lg in leagues:
        lid = lg["league_id"]
        name = lg["name"]
        rec = lg.get("scoring_settings", {}).get("rec", 1.0)
        is_best_ball = lg.get("settings", {}).get("best_ball") == 1
        is_superflex = "SUPER_FLEX" in lg.get("roster_positions", [])
        is_dynasty = lg.get("settings", {}).get("type") == 2
        rosters = get(f"https://api.sleeper.app/v1/league/{lid}/rosters")
        my = None
        for r in rosters:
            if r.get("owner_id") == uid or uid in (r.get("co_owners") or []):
                my = r
                break
        if not my:
            continue
        rostered = set()
        for r in rosters:
            rostered.update(r.get("players", []))
        my_players = set(my.get("players", []))
        my_starters = set(my.get("starters", []))

        # Build my roster with next-week projections
        def proj_for(pid):
            pr = proj.get(str(pid), {})
            pts = pr.get("pts_half_ppr") if rec == 0.5 else pr.get("pts_ppr")
            p = players.get(str(pid), {})
            if p.get("injury_status") in ("Out", "IR"):
                return 0.0
            return pts

        # Weakest starter per position
        starters_by_pos = {}
        for pid in my_starters:
            p = players.get(str(pid), {})
            pos = p.get("position")
            if not pos:
                continue
            starters_by_pos.setdefault(pos, []).append((proj_for(pid) or 0, p.get("full_name"), pid))
        # Drop candidate: lowest bench projection
        bench = []
        for pid in my_players:
            if pid in my_starters:
                continue
            p = players.get(str(pid), {})
            bench.append((proj_for(pid) or 0, p.get("full_name"), p.get("position"), pid, p.get("injury_status")))
        bench_sorted = sorted(bench)
        drop = bench_sorted[0] if bench_sorted else None

        # Free agents
        cands = []
        for pid, pr in proj.items():
            if pid in rostered:
                continue
            p = players.get(pid, {})
            pos = p.get("position")
            if pos not in ("QB", "RB", "WR", "TE"):
                continue
            if p.get("injury_status") in ("Out", "IR"):
                continue
            pts = pr.get("pts_half_ppr") if rec == 0.5 else pr.get("pts_ppr")
            if pts is None or pts < 5:
                continue
            # Need-aware: in 1QB, QB FA is only valuable if your QBs are weak / injured
            # De-prioritize QB in 1QB by requiring higher threshold
            if pos == "QB" and not is_superflex:
                # Only show QB if your best QB proj < 15 or you have no healthy QB
                my_qb_projs = [proj_for(pid) for pid in my_players if players.get(str(pid), {}).get("position") == "QB"]
                best_qb = max(my_qb_projs) if my_qb_projs else 0
                if best_qb >= 15 and pts < 18:
                    continue
            cands.append({
                "name": p.get("full_name"),
                "pos": pos,
                "team": p.get("team"),
                "proj": pts,
                "injury": p.get("injury_status"),
                "player_id": pid,
            })
        # Sort by proj, but boost RB/WR/TE need in 1QB, QB need in Superflex
        # Simple: sort by proj, then take top per position group
        cands_sorted = sorted(cands, key=lambda x: x["proj"], reverse=True)
        # Find upgrades: FA > weakest starter at same pos, or > weakest FLEX-eligible starter
        targets = []
        for c in cands_sorted:
            if len(targets) >= top_n:
                break
            # Weakest starter at same position
            same_pos = starters_by_pos.get(c["pos"], [])
            weakest_same = min([x[0] for x in same_pos]) if same_pos else 0
            # For FLEX, also compare to weakest FLEX starter (we approximate as weakest RB/WR/TE starter)
            flex_weakest = 999
            for pos in ("RB", "WR", "TE"):
                if pos in starters_by_pos:
                    flex_weakest = min(flex_weakest, min([x[0] for x in starters_by_pos[pos]]))
            is_upgrade = c["proj"] > weakest_same or (c["pos"] in ("RB", "WR", "TE") and c["proj"] > flex_weakest)
            # Always include top 2 FAs even if not strict upgrade, for awareness
            if is_upgrade or len(targets) < 2:
                targets.append({**c, "weakest_starter_same_pos": weakest_same, "is_upgrade": is_upgrade})
        results[name] = {
            "league_id": lid,
            "is_superflex": is_superflex,
            "is_best_ball": is_best_ball,
            "is_dynasty": is_dynasty,
            "drop_candidate": {"name": drop[1], "pos": drop[2], "proj": drop[0], "injury": drop[4]} if drop else None,
            "targets": targets,
            "note": "Dynasty: check keeper / age value before dropping" if is_dynasty else "Redraft: drop lowest bench if needed",
        }
    return results

def print_waiver(username, season="2026", current_week=7):
    res = get_waiver_targets(username, season, current_week)
    print(f"# Waiver Wire - Week {current_week+1} - {username}\n")
    for league, data in res.items():
        print(f"## {league} {'(Superflex)' if data['is_superflex'] else '(1QB)'} {'(Dynasty)' if data['is_dynasty'] else '(Redraft)'} {'(Best Ball)' if data['is_best_ball'] else ''}")
        if data["drop_candidate"]:
            d = data["drop_candidate"]
            print(f"Drop candidate: {d['name']} {d['pos']} proj {d['proj']:.1f} - {data['note']}")
        print("Top targets:")
        for t in data["targets"]:
            flag = "UPGRADE" if t["is_upgrade"] else "watch"
            print(f"- {t['name']} {t['pos']} {t['team']} proj {t['proj']:.1f} [{flag}] weakest starter same pos {t['weakest_starter_same_pos']:.1f} inj: {t['injury']}")
        print("")

if __name__ == "__main__":
    import sys
    user = sys.argv[1] if len(sys.argv) > 1 else "IMthatGuyton"
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    print_waiver(user, current_week=week)
