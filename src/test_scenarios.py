import json
from datetime import datetime, timedelta, timezone
from src.graph import CascadeDependencyGraph

IST = timezone(timedelta(hours=5, minutes=30))

def print_downstream_table(result):
    """Print a readable table of all downstream tasks, including safe ones."""
    print(f"  {'Task ID':<10} {'Status':<10} {'Committed':<12} {'Projected':<12} {'Buffer':<8} {'Duration'}")
    print(f"  {'-------':<10} {'------':<10} {'---------':<12} {'---------':<12} {'------':<8} {'--------'}")
    for d in result['downstream_impacts']:
        status_icon = {"broken": "🔴", "at_risk": "🟡", "safe": "🟢"}.get(d['status'], "⚪")
        buf = f"{d['buffer_remaining']}d" if d['buffer_remaining'] is not None else "n/a"
        dur = f"{d['estimated_duration_days']}d"
        print(f"  {d['id']:<10} {status_icon} {d['status']:<7} {d['committed_date']:<12} {d['projected_finish']:<12} {buf:<8} {dur}")
    print()

def run_scenarios():
    with open("data/approved_tasks.json") as f:
        tasks = json.load(f)

    sim_time_off_hours = datetime(2026, 11, 18, 22, 30, tzinfo=IST)  # 10:30 PM IST
    sim_time_in_hours = datetime(2026, 11, 19, 14, 0, tzinfo=IST)    # 2:00 PM IST

    all_results = {}

    # ── Scenario A: 1-day slip on task-1 ──────────────────────────────────
    # Chain: task-1(2d) → task-2(2d, 0 slack) → task-3(1d, 2d slack) → task-4(5d, 7d slack)
    # Expected: task-2 BROKEN (0 slack), task-3 AT_RISK (buffer erodes to 1d), task-4 SAFE
    print("=" * 80)
    print("SCENARIO A: task-1 slips 1 day")
    print("Tests: BROKEN (zero slack), AT_RISK (buffer erodes), SAFE (slack absorbs)")
    print("=" * 80)
    graph = CascadeDependencyGraph(tasks)
    res_a = graph.simulate_cascade("task-1", slip_days=1, simulation_time_ist=sim_time_in_hours)
    print_downstream_table(res_a)
    g1 = res_a['goal_rollups'].get('goal-1', {})
    print(f"  Goal-1: {g1.get('status', 'n/a').upper()} — {g1.get('consequence_reason', '')}")
    print(f"  Alerts: {len(res_a['slack_alerts'])} dispatched")
    for a in res_a['slack_alerts']:
        print(f"    → {a['recipient_owner']} ({a['type']})")
    all_results["scenario_a_1day_slip"] = res_a

    # ── Scenario B: 4-day slip on task-1 ──────────────────────────────────
    # Expected: task-2 BROKEN, task-3 BROKEN, task-4 SAFE (7d slack absorbs)
    print("\n" + "=" * 80)
    print("SCENARIO B: task-1 slips 4 days")
    print("Tests: cascade breaks multiple tasks, but final task's large slack absorbs")
    print("=" * 80)
    graph = CascadeDependencyGraph(tasks)
    res_b = graph.simulate_cascade("task-1", slip_days=4, simulation_time_ist=sim_time_off_hours)
    print_downstream_table(res_b)
    g1 = res_b['goal_rollups'].get('goal-1', {})
    print(f"  Goal-1: {g1.get('status', 'n/a').upper()} — {g1.get('consequence_reason', '')}")
    print(f"  Alerts: {len(res_b['slack_alerts'])} dispatched")
    for a in res_b['slack_alerts']:
        print(f"    → {a['recipient_owner']} ({a['type']}) {a['delivery_status']}")
    all_results["scenario_b_4day_slip"] = res_b

    # ── Scenario C: 2-day slip on task-3 (mid-chain) ─────────────────────
    # task-3 has 7d slack before task-4, so 2d slip is absorbed easily
    # Expected: task-4 SAFE, goal ON_TRACK
    print("\n" + "=" * 80)
    print("SCENARIO C: task-3 slips 2 days (mid-chain)")
    print("Tests: ABSORBED — large downstream slack eats the slip, goal stays ON_TRACK")
    print("=" * 80)
    graph = CascadeDependencyGraph(tasks)
    res_c = graph.simulate_cascade("task-3", slip_days=2, simulation_time_ist=sim_time_in_hours)
    print_downstream_table(res_c)
    g1 = res_c['goal_rollups'].get('goal-1', {})
    print(f"  Goal-1: {g1.get('status', 'n/a').upper()} — {g1.get('consequence_reason', '')}")
    all_results["scenario_c_midchain_absorbed"] = res_c

    # ── Scenario D: 2-day slip on task-4 (leaf, no downstream) ───────────
    # Expected: 0 downstream impacts, goal OFF_TRACK (12/07 > 12/05)
    print("\n" + "=" * 80)
    print("SCENARIO D: task-4 slips 2 days (leaf task)")
    print("Tests: no cascade, but goal misses target date → OFF_TRACK")
    print("=" * 80)
    graph = CascadeDependencyGraph(tasks)
    res_d = graph.simulate_cascade("task-4", slip_days=2, simulation_time_ist=sim_time_in_hours)
    print(f"  Downstream impacts: {len([d for d in res_d['downstream_impacts'] if d['status'] != 'safe'])}")
    g1 = res_d['goal_rollups'].get('goal-1', {})
    print(f"  Goal-1: {g1.get('status', 'n/a').upper()} — {g1.get('consequence_reason', '')}")
    for a in res_d['slack_alerts']:
        print(f"    → {a['recipient_owner']} ({a['type']})")
    all_results["scenario_d_leaf_slip"] = res_d

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("STATUS COVERAGE SUMMARY")
    print("=" * 80)
    all_statuses = set()
    for key, res in all_results.items():
        for d in res['downstream_impacts']:
            all_statuses.add(d['status'])
    all_goal_statuses = set()
    for key, res in all_results.items():
        for g in res['goal_rollups'].values():
            all_goal_statuses.add(g['status'])
    
    print(f"  Task statuses exercised: {sorted(all_statuses)}")
    print(f"  Goal statuses exercised: {sorted(all_goal_statuses)}")
    
    expected_task = {"safe", "at_risk", "broken"}
    expected_goal = {"on_track", "at_risk", "off_track"}
    task_ok = expected_task.issubset(all_statuses)
    goal_ok = expected_goal.issubset(all_goal_statuses)
    print(f"  All 3 task statuses covered: {'✅' if task_ok else '❌ MISSING: ' + str(expected_task - all_statuses)}")
    print(f"  All 3 goal statuses covered: {'✅' if goal_ok else '❌ MISSING: ' + str(expected_goal - all_goal_statuses)}")

    # Save
    with open("logs/simulation_scenarios.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nAll scenarios saved to logs/simulation_scenarios.json")

if __name__ == "__main__":
    run_scenarios()
