"""
Sleeper Fantasy Agent - Layer 2: Chat + Digest
Read-only. Uses Sleeper public API + deterministic optimizer.
LLM is used only for explanations, never for numbers.

Core idea for GitHub: show agent loop
  perceive (Sleeper API) -> reason (optimizer + rules) -> explain (template / LLM) -> act (suggest, never auto-change)
"""
import urllib.request, json
from sleeper_optimizer import get, optimize_lineup, FLEX_ELIGIBLE, SUPER_FLEX_ELIGIBLE

def load_league_data(username, season="2026", week=7):
    user = get(f"https://api.sleeper.app/v1/user/{username}")
    uid = user["user_id"]
    leagues = get(f"https://api.sleeper.app/v1/user/{uid}/leagues/nfl/{season}")
    players = get("https://api.sleeper.app/v1/players/nfl")
    proj = get(f"https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}")
    return uid, leagues, players, proj

def build_roster_context(league, my_roster, players, proj, week):
    rec = league.get("scoring_settings", {}).get("rec", 1.0)
    plist = []
    for pid in my_roster.get("players", []):
        p = players.get(str(pid), {})
        if not p and isinstance(pid, str) and len(pid) <= 3:
            pr = proj.get(pid, {})
            pts = pr.get("pts_ppr") if rec == 1.0 else pr.get("pts_half_ppr")
            plist.append({"player_id": pid, "name": f"{pid} DEF", "pos": "DEF", "team": pid, "proj": pts or 0.0, "injury": None})
            continue
        pr = proj.get(str(pid), {})
        if rec == 0.5:
            pts = pr.get("pts_half_ppr")
        elif rec == 0:
            pts = pr.get("pts_std")
        else:
            pts = pr.get("pts_ppr")
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
    return plist

def generate_digest(username, season="2026", week=7):
    """Sunday morning digest: urgent actions across all leagues."""
    uid, leagues, players, proj = load_league_data(username, season, week)
    lines = [f"# Sunday Digest - Week {week} - {username}", ""]
    total_gap = 0
    urgent_count = 0
    for lg in leagues:
        lid = lg["league_id"]
        name = lg["name"]
        is_best_ball = lg.get("settings", {}).get("best_ball") == 1
        rosters = get(f"https://api.sleeper.app/v1/league/{lid}/rosters")
        my = None
        for r in rosters:
            if r.get("owner_id") == uid or uid in (r.get("co_owners") or []):
                my = r
                break
        if not my:
            continue
        plist = build_roster_context(lg, my, players, proj, week)
        roster_positions = lg.get("roster_positions", [])
        assignment, total_opt, _ = optimize_lineup(roster_positions, plist)
        curr_total = sum((p["proj"] or 0) for p in plist if p["player_id"] in set(my.get("starters", [])))
        gap = total_opt - curr_total
        if not is_best_ball:
            total_gap += gap
            # Urgent: starters with no proj or Out/IR
            urgent = [p for p in plist if p["player_id"] in set(my.get("starters", [])) and (p["proj"] is None or p["injury"] in ("Out","IR"))]
            urgent_count += len(urgent)
        else:
            urgent = []
        lines.append(f"## {name}")
        if is_best_ball:
            lines.append("Best Ball - no action needed.")
        else:
            lines.append(f"Current {curr_total:.1f} -> Optimal {total_opt:.1f} (gap +{gap:.1f})")
            if urgent:
                lines.append("Urgent:")
                for p in urgent:
                    reason = "bye / no projection" if p["proj"] is None else f"injury {p['injury']}"
                    lines.append(f"- {p['name']} {p['pos']} {p['team']} - {reason}")
            # Suggested swaps
            opt_ids = set(p["player_id"] for p in assignment.values())
            curr_ids = set(my.get("starters", []))
            to_start = [p for p in plist if p["player_id"] in opt_ids and p["player_id"] not in curr_ids]
            to_bench = [p for p in plist if p["player_id"] in curr_ids and p["player_id"] not in opt_ids]
            if to_start:
                lines.append("Suggested swaps (read-only):")
                for p in to_start:
                    lines.append(f"- START {p['name']} {p['pos']} proj {p['proj'] or 0:.1f}")
                for p in to_bench:
                    lines.append(f"- BENCH {p['name']} {p['pos']} proj {p['proj'] or 0:.1f}")
        lines.append("")
    lines.insert(2, f"Total gap across leagues: +{total_gap:.1f} projected points | Urgent starters: {urgent_count}")
    lines.insert(3, "")
    return "\n".join(lines)

def answer_start_sit(username, player_a_name, player_b_name, season="2026", week=7, league_name_filter=None):
    """Simple start/sit: find both players in user's rosters, compare projections."""
    uid, leagues, players, proj = load_league_data(username, season, week)
    # Build name -> player lookup
    name_to_id = {}
    for pid, p in players.items():
        if p.get("full_name"):
            name_to_id[p["full_name"].lower()] = pid
    a_id = name_to_id.get(player_a_name.lower())
    b_id = name_to_id.get(player_b_name.lower())
    if not a_id or not b_id:
        return f"Could not find one of {player_a_name} / {player_b_name} in Sleeper player pool."
    # Find which leagues you own them in
    results = []
    for lg in leagues:
        if league_name_filter and league_name_filter.lower() not in lg["name"].lower():
            continue
        rosters = get(f"https://api.sleeper.app/v1/league/{lg['league_id']}/rosters")
        my = None
        for r in rosters:
            if r.get("owner_id") == uid or uid in (r.get("co_owners") or []):
                my = r
                break
        if not my or a_id not in my.get("players", []) and b_id not in my.get("players", []):
            # Only answer if you own at least one in this league
            if a_id not in my.get("players", []) and b_id not in my.get("players", []):
                continue
        rec = lg.get("scoring_settings", {}).get("rec", 1.0)
        def get_proj(pid):
            pr = proj.get(str(pid), {})
            pts = pr.get("pts_half_ppr") if rec == 0.5 else pr.get("pts_ppr")
            p = players.get(str(pid), {})
            if p.get("injury_status") in ("Out","IR"):
                pts = 0.0
            return pts, p
        a_pts, a_p = get_proj(a_id)
        b_pts, b_p = get_proj(b_id)
        winner = player_a_name if (a_pts or 0) >= (b_pts or 0) else player_b_name
        results.append(f"{lg['name']}: {player_a_name} {a_pts or 0:.1f} vs {player_b_name} {b_pts or 0:.1f} -> Start {winner} (inj: {a_p.get('injury_status')}/{b_p.get('injury_status')})")
    if not results:
        return f"You do not own {player_a_name} or {player_b_name} in any of your Sleeper leagues."
    return "\n".join(results)

if __name__ == "__main__":
    import sys
    user = sys.argv[1] if len(sys.argv) > 1 else "IMthatGuyton"
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    print(generate_digest(user, week=week))
