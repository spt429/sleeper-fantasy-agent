"""
Sleeper Fantasy Agent - READ ONLY
Pulls Sam's Sleeper leagues, computes optimal lineup per league for a given week,
flags bye / Out starters. Never writes to Sleeper. No roster changes.

Usage: python3 sleeper_optimizer.py --username IMthatGuyton --week 7 --season 2026
"""
import argparse, urllib.request, json, sys
from collections import defaultdict

def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read().decode())

FLEX_ELIGIBLE = {"RB","WR","TE"}
SUPER_FLEX_ELIGIBLE = {"QB","RB","WR","TE"}

def eligible(pos, slot):
    if slot == "FLEX":
        return pos in FLEX_ELIGIBLE
    if slot == "SUPER_FLEX":
        return pos in SUPER_FLEX_ELIGIBLE
    if slot == "BN":
        return False
    return pos == slot

def optimize_lineup(roster_positions, players_with_proj):
    """
    players_with_proj: list of dicts {player_id, name, pos, team, proj, injury}
    Returns (assignment dict slot_index -> player, total_proj, bench_list)
    Greedy in scarcity order: QB, RB, WR, TE, K, DEF, FLEX, SUPER_FLEX
    """
    # Order slots by scarcity: fixed positions first, then FLEX, then SUPER_FLEX last
    order_priority = {"QB":0, "RB":1, "WR":2, "TE":3, "K":4, "DEF":5, "FLEX":6, "SUPER_FLEX":7, "BN":99}
    slots = [(i, s) for i, s in enumerate(roster_positions) if s != "BN"]
    slots_sorted = sorted(slots, key=lambda x: order_priority.get(x[1], 8))
    # Sort players by proj desc (None -> -1)
    remaining = sorted(players_with_proj, key=lambda p: (p["proj"] if p["proj"] is not None else -1), reverse=True)
    assignment = {}
    used = set()
    for idx, slot in slots_sorted:
        best = None
        for p in remaining:
            if p["player_id"] in used:
                continue
            if eligible(p["pos"], slot):
                best = p
                break
        if best:
            assignment[idx] = best
            used.add(best["player_id"])
    bench = [p for p in remaining if p["player_id"] not in used]
    total = sum((assignment[i]["proj"] or 0) for i in assignment)
    return assignment, total, bench

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="IMthatGuyton")
    ap.add_argument("--season", default="2026")
    ap.add_argument("--week", type=int, default=7)
    args = ap.parse_args()

    user = get(f"https://api.sleeper.app/v1/user/{args.username}")
    uid = user["user_id"]
    print(f"User: {user['username']} ({user['display_name']}) id={uid}")
    leagues = get(f"https://api.sleeper.app/v1/user/{uid}/leagues/nfl/{args.season}")
    if not leagues:
        print("No leagues found")
        return
    players = get("https://api.sleeper.app/v1/players/nfl")
    proj = get(f"https://api.sleeper.app/v1/projections/nfl/regular/{args.season}/{args.week}")
    # Sleeper projections use pts_ppr for PPR; for half-PPR we use pts_half_ppr if available
    # We will compute both and pick based on league scoring rec value later

    for lg in leagues:
        lid = lg["league_id"]
        name = lg["name"]
        rec = lg.get("scoring_settings", {}).get("rec", 1.0)
        roster_positions = lg.get("roster_positions", [])
        is_best_ball = lg.get("settings", {}).get("best_ball") == 1
        print(f"\n{'='*70}")
        print(f"{name} ({lid}) - rec={rec} best_ball={is_best_ball} positions={roster_positions}")
        rosters = get(f"https://api.sleeper.app/v1/league/{lid}/rosters")
        my = None
        for r in rosters:
            if r.get("owner_id") == uid or uid in (r.get("co_owners") or []):
                my = r
                break
        if not my:
            print("  No roster for user (not owner/co-owner)")
            continue
        # Build player list
        plist = []
        for pid in my.get("players", []):
            p = players.get(str(pid), {})
            # DEF players: pid is team abbrev, not in players dict
            if not p and isinstance(pid, str) and len(pid) <= 3:
                # team defense
                pr = proj.get(pid, {})
                pts = pr.get("pts_ppr") if rec == 1.0 else pr.get("pts_half_ppr") if rec == 0.5 else pr.get("pts_ppr")
                if pts is None:
                    pts = 0.0
                plist.append({"player_id": pid, "name": f"{pid} DEF", "pos": "DEF", "team": pid, "proj": pts, "injury": None})
                continue
            pr = proj.get(str(pid), {})
            if rec == 0.5:
                pts = pr.get("pts_half_ppr")
            elif rec == 0:
                pts = pr.get("pts_std")
            else:
                pts = pr.get("pts_ppr")
            # Out / IR players will not play - treat projection as 0 even if Sleeper still has a stale projection
            if p.get("injury_status") in ("Out", "IR", "Suspended", "PUP"):
                pts = 0.0
            plist.append({
                "player_id": pid,
                "name": p.get("full_name") or pid,
                "pos": p.get("position") or "?",
                "team": p.get("team") or "?",
                "proj": pts,
                "injury": p.get("injury_status"),
            })
        # Current starters
        current_starters = set(my.get("starters", []))
        # Optimize
        assignment, total_opt, bench = optimize_lineup(roster_positions, plist)
        # Current total
        curr_total = 0
        curr_map = {}
        for p in plist:
            if p["player_id"] in current_starters:
                curr_map[p["player_id"]] = p
                curr_total += (p["proj"] or 0)
        print(f"  Current starters total proj: {curr_total:.1f} | Optimal total proj: {total_opt:.1f} | Gap: {total_opt - curr_total:+.1f}")
        if is_best_ball:
            print("  Best Ball - no lineup action needed, optimal is auto-set. Showing optimal for reference.")
        # Show optimal lineup in slot order
        print("  -- Optimal lineup --")
        for idx, slot in enumerate(roster_positions):
            if slot == "BN":
                continue
            p = assignment.get(idx)
            if p:
                flag = ""
                if p["proj"] is None:
                    flag = " [NO PROJ - BYE/OUT?]"
                if p["injury"] in ("Out","IR"):
                    flag += f" [INJ: {p['injury']}]"
                print(f"    {slot:10} {p['name']:25} {p['pos']:3} {p['team']:4} proj={p['proj'] if p['proj'] is not None else 0:.1f}{flag}")
            else:
                print(f"    {slot:10} (empty)")
        # Diffs: players to swap
        opt_ids = set(p["player_id"] for p in assignment.values())
        to_start = [p for p in plist if p["player_id"] in opt_ids and p["player_id"] not in current_starters]
        to_bench = [p for p in plist if p["player_id"] in current_starters and p["player_id"] not in opt_ids]
        if to_start or to_bench:
            print("  -- Suggested swaps (READ ONLY, not applied) --")
            for p in to_start:
                print(f"    START {p['name']} {p['pos']} {p['team']} proj={p['proj'] or 0:.1f}")
            for p in to_bench:
                reason = ""
                if p["proj"] is None:
                    reason = "no projection (bye?)"
                if p["injury"] in ("Out","IR"):
                    reason += f" injury {p['injury']}"
                print(f"    BENCH {p['name']} {p['pos']} {p['team']} proj={p['proj'] or 0:.1f} {reason}")
        else:
            print("  Lineup already optimal.")
        # Urgent flags: current starters with no proj or Out/IR
        urgent = [p for p in plist if p["player_id"] in current_starters and (p["proj"] is None or p["injury"] in ("Out","IR"))]
        if urgent and not is_best_ball:
            print("  !! URGENT - current starters with no proj or Out/IR:")
            for p in urgent:
                print(f"     {p['name']} {p['pos']} {p['team']} proj={p['proj']} inj={p['injury']}")

if __name__ == "__main__":
    main()
