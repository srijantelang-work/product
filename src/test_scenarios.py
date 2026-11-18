import json
from datetime import datetime, timedelta, timezone
from src.graph import CascadeDependencyGraph

IST = timezone(timedelta(hours=5, minutes=30))

def run_scenarios():
    with open("data/approved_tasks.json") as f:
        tasks = json.load(f)

    graph = CascadeDependencyGraph(tasks)
    sim_time_off_hours = datetime(2026, 11, 18, 22, 30, tzinfo=IST) # 10:30 PM IST (Outside hours)
    sim_time_in_hours = datetime(2026, 11, 19, 14, 0, tzinfo=IST)    # 2:00 PM IST (Within hours)

    print("=" * 80)
    print("SCENARIO 1: Large slip at root (task-1 slips by 4 days)")
    print("Expected: Cascades downstream breaking task-2 and task-3, goal OFF_TRACK")
    print("=" * 80)
    res1 = graph.simulate_cascade("task-1", slip_days=4, simulation_time_ist=sim_time_off_hours)
    print(f"Goal 1 Status: {res1['goal_rollups']['goal-1']['status'].upper()}")
    print(f"Goal Reason:   {res1['goal_rollups']['goal-1']['consequence_reason']}")
    print(f"Downstream Impacts ({len(res1['downstream_impacts'])} tasks):")
    for d in res1['downstream_impacts']:
        print(f"  - [{d['id']}] {d['title']} (Owner: {d['owner']}) -> {d['status'].upper()} (Projected: {d['projected_finish']})")
    print(f"Alerts Dispatched ({len(res1['slack_alerts'])} owners):")
    for a in res1['slack_alerts']:
        print(f"  - Recipient: {a['recipient_owner']} | Type: {a['type']} | Status: {a['delivery_status']}")

    print("\n" + "=" * 80)
    print("SCENARIO 2: 1-day slip at root (task-1 slips by 1 day)")
    print("Expected: Buffer erodes to 1 day -> AT_RISK (not broken)")
    print("=" * 80)
    res2 = graph.simulate_cascade("task-1", slip_days=1, simulation_time_ist=sim_time_in_hours)
    print(f"Goal 1 Status: {res2['goal_rollups']['goal-1']['status'].upper()}")
    print(f"Goal Reason:   {res2['goal_rollups']['goal-1']['consequence_reason']}")
    print(f"Downstream Impacts ({len(res2['downstream_impacts'])} tasks):")
    for d in res2['downstream_impacts']:
        print(f"  - [{d['id']}] {d['title']} (Owner: {d['owner']}) -> {d['status'].upper()} (Buffer: {d['buffer_remaining']}d)")
    for a in res2['slack_alerts']:
        print(f"  - Recipient: {a['recipient_owner']} | Status: {a['delivery_status']}")

    print("\n" + "=" * 80)
    print("SCENARIO 3: Slip in middle of chain (task-3 slips by 3 days)")
    print("Expected: task-1 and task-2 unaffected, task-4 downstream evaluated")
    print("=" * 80)
    res3 = graph.simulate_cascade("task-3", slip_days=3, simulation_time_ist=sim_time_in_hours)
    print(f"Goal 1 Status: {res3['goal_rollups']['goal-1']['status'].upper()}")
    print(f"Downstream Impacts ({len(res3['downstream_impacts'])} tasks):")
    for d in res3['downstream_impacts']:
        print(f"  - [{d['id']}] {d['title']} -> {d['status'].upper()}")

    print("\n" + "=" * 80)
    print("SCENARIO 4: Slip of final task in chain (task-4 slips by 2 days)")
    print("Expected: No downstream tasks affected, only root confirmation and goal roll-up")
    print("=" * 80)
    res4 = graph.simulate_cascade("task-4", slip_days=2, simulation_time_ist=sim_time_in_hours)
    print(f"Downstream Impacts: {len(res4['downstream_impacts'])} (Expected: 0)")
    print(f"Goal 1 Status: {res4['goal_rollups']['goal-1']['status'].upper()}")
    for a in res4['slack_alerts']:
        print(f"  - Recipient: {a['recipient_owner']} | Type: {a['type']}")

    # Save test results
    with open("logs/simulation_scenarios.json", "w") as f:
        json.dump({
            "scenario_1_large_slip": res1,
            "scenario_2_at_risk_1day": res2,
            "scenario_3_mid_chain": res3,
            "scenario_4_leaf_task": res4
        }, f, indent=2)
    print("\nAll 4 scenarios executed and saved to logs/simulation_scenarios.json")

if __name__ == "__main__":
    run_scenarios()
