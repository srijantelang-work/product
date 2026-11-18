import json
import os
from datetime import datetime, timedelta, time, timezone
from typing import Dict, List, Any, Optional, Set

# Constants & Assumptions
# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))
ALERT_START_TIME = time(9, 0)   # 9:00 AM IST
ALERT_END_TIME = time(19, 0)    # 7:00 PM IST
BUFFER_THRESHOLD_DAYS = 1       # 1 day buffer or less is considered 'at_risk'

class TaskNode:
    def __init__(self, data: Dict[str, Any]):
        self.id = data["id"]
        self.title = data["title"]
        self.owner = data.get("owner")
        self.goal = data.get("goal")
        self.original_due_date = data.get("due_date")
        self.current_due_date = data.get("due_date")
        self.depends_on: List[str] = data.get("depends_on", [])
        self.downstream: List[str] = []
        self.status = "safe"  # safe, at_risk, broken
        self.status_reason: Optional[str] = None
        self.buffer_remaining: Optional[int] = None
        self.days_slipped: int = 0

class DependencyGraph:
    def __init__(self, tasks: List[Dict[str, Any]]):
        self.nodes: Dict[str, TaskNode] = {t["id"]: TaskNode(t) for t in tasks}
        self._build_downstream_links()

    def _build_downstream_links(self):
        for node in self.nodes.values():
            for parent_id in node.depends_on:
                if parent_id in self.nodes:
                    self.nodes[parent_id].downstream.append(node.id)

    def topological_order(self) -> List[str]:
        in_degree = {nid: len(n.depends_on) for nid, n in self.nodes.items()}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order = []
        while queue:
            curr = queue.pop(0)
            order.append(curr)
            for child_id in self.nodes[curr].downstream:
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)
        return order

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d")

def format_date(dt: Optional[datetime]) -> str:
    if not dt:
        return "TBD"
    return dt.strftime("%Y-%m-%d")

def is_within_alert_hours(dt: datetime) -> bool:
    """Checks whether the datetime falls between Mon-Sat, 9:00 AM - 7:00 PM IST."""
    # weekday() returns 0 for Monday and 6 for Sunday
    if dt.weekday() == 6:  # Sunday
        return False
    local_time = dt.time()
    return ALERT_START_TIME <= local_time <= ALERT_END_TIME

def get_next_alert_window(dt: datetime) -> datetime:
    """Finds the next valid alert window (9:00 AM IST on Mon-Sat)."""
    curr = dt
    # If after 7pm, advance to next morning 9am
    if curr.time() > ALERT_END_TIME:
        curr = (curr + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    # If before 9am, set to today 9am
    elif curr.time() < ALERT_START_TIME:
        curr = curr.replace(hour=9, minute=0, second=0, microsecond=0)
    
    # If landing on Sunday, advance to Monday 9am
    if curr.weekday() == 6:
        curr = (curr + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return curr

def simulate_slip(
    graph: DependencyGraph,
    slipped_task_id: str,
    days_slipped: int,
    simulation_time_ist: Optional[datetime] = None
) -> Dict[str, Any]:
    if slipped_task_id not in graph.nodes:
        raise ValueError(f"Task '{slipped_task_id}' not found in dependency graph.")

    if simulation_time_ist is None:
        # Default to current time in IST
        simulation_time_ist = datetime.now(IST)

    slipped_node = graph.nodes[slipped_task_id]
    slipped_node.days_slipped = days_slipped
    
    orig_dt = parse_date(slipped_node.original_due_date)
    if not orig_dt:
        raise ValueError(f"Task '{slipped_task_id}' does not have a set due date.")

    new_due_dt = orig_dt + timedelta(days=days_slipped)
    slipped_node.current_due_date = format_date(new_due_dt)
    slipped_node.status = "broken" if days_slipped > 0 else "safe"
    slipped_node.status_reason = f"Primary source of delay: slipped by {days_slipped} days."

    # Propagate through topological order
    topo_order = graph.topological_order()
    start_eval = False
    affected_tasks: List[TaskNode] = []

    for nid in topo_order:
        if nid == slipped_task_id:
            start_eval = True
            affected_tasks.append(graph.nodes[nid])
            continue
        if not start_eval:
            continue

        node = graph.nodes[nid]
        node_due_dt = parse_date(node.current_due_date)
        if not node_due_dt:
            continue

        # Evaluate against all upstream dependencies
        worst_status = "safe"
        worst_reason = None
        min_buffer = 999

        for parent_id in node.depends_on:
            parent = graph.nodes[parent_id]
            parent_due_dt = parse_date(parent.current_due_date)
            if not parent_due_dt:
                continue

            buffer_days = (node_due_dt - parent_due_dt).days
            if buffer_days < min_buffer:
                min_buffer = buffer_days

            if parent_due_dt > node_due_dt:
                days_over = (parent_due_dt - node_due_dt).days
                status = "broken"
                reason = f"Upstream task '{parent.title}' finishes on {format_date(parent_due_dt)}, which is {days_over} day(s) AFTER downstream task '{node.title}' is due ({format_date(node_due_dt)})."
            elif buffer_days <= BUFFER_THRESHOLD_DAYS:
                status = "at_risk"
                reason = f"Buffer with upstream task '{parent.title}' is only {buffer_days} day(s) (threshold: <= {BUFFER_THRESHOLD_DAYS} day)."
            else:
                status = "safe"
                reason = f"Healthy buffer of {buffer_days} days."

            if status == "broken":
                worst_status = "broken"
                worst_reason = reason
                break
            elif status == "at_risk" and worst_status != "broken":
                worst_status = "at_risk"
                worst_reason = reason

        node.status = worst_status
        node.status_reason = worst_reason
        node.buffer_remaining = min_buffer
        if worst_status in ["broken", "at_risk"]:
            affected_tasks.append(node)

    # Goal Roll-up Calculation
    goals = load_goals()
    goal_rollups = {}
    for gid, goal in goals.items():
        goal_tasks = [n for n in graph.nodes.values() if n.goal == gid]
        if not goal_tasks:
            continue
        
        has_broken = any(t.status == "broken" for t in goal_tasks)
        has_at_risk = any(t.status == "at_risk" for t in goal_tasks)

        if has_broken:
            g_status = "off_track"
            broken_nodes = [t for t in goal_tasks if t.status == "broken"]
            g_reason = broken_nodes[0].status_reason
        elif has_at_risk:
            g_status = "at_risk"
            at_risk_nodes = [t for t in goal_tasks if t.status == "at_risk"]
            g_reason = at_risk_nodes[0].status_reason
        else:
            g_status = "on_track"
            g_reason = "All milestone tasks on schedule."

        goal_rollups[gid] = {
            "name": goal["name"],
            "target_date": goal["target_date"],
            "weight": goal["weight"],
            "status": g_status,
            "reason": g_reason
        }

    # Generate Slack Alert Dispatches
    slack_alerts = generate_slack_alerts(
        slipped_node=slipped_node,
        affected_tasks=affected_tasks,
        goal_rollups=goal_rollups,
        sim_time=simulation_time_ist
    )

    return {
        "slipped_task": {
            "id": slipped_node.id,
            "title": slipped_node.title,
            "days_slipped": days_slipped,
            "original_due_date": slipped_node.original_due_date,
            "new_due_date": slipped_node.current_due_date
        },
        "affected_tasks": [
            {
                "id": t.id,
                "title": t.title,
                "owner": t.owner,
                "status": t.status,
                "buffer_remaining": t.buffer_remaining,
                "reason": t.status_reason
            }
            for t in affected_tasks
        ],
        "goals": goal_rollups,
        "slack_alerts": slack_alerts
    }

def load_goals() -> Dict[str, Dict[str, Any]]:
    with open("data/goals.json") as f:
        data = json.load(f)
    return {g["id"]: g for g in data}

def generate_slack_alerts(
    slipped_node: TaskNode,
    affected_tasks: List[TaskNode],
    goal_rollups: Dict[str, Any],
    sim_time: datetime
) -> List[Dict[str, Any]]:
    alerts = []
    
    within_hours = is_within_alert_hours(sim_time)
    dispatch_header = "🟢 [DISPATCHED IMMEDIATELY]" if within_hours else "⏰ [QUEUED UNTIL NEXT ALERT WINDOW]"
    next_window = None if within_hours else get_next_alert_window(sim_time).strftime("%A, %d %b %Y, 09:00 AM IST")

    # Group affected tasks by owner (exclude the initiator if covered in root cause)
    owner_tasks: Dict[str, List[TaskNode]] = {}
    for t in affected_tasks:
        if t.owner:
            owner_tasks.setdefault(t.owner, []).append(t)

    for owner, tasks in owner_tasks.items():
        impacted_titles = [f"`{t.title}` ({t.status.upper()})" for t in tasks]
        goal_impacts = list({t.goal for t in tasks if t.goal})
        goal_names = [f"*{goal_rollups[g]['name']}* ({goal_rollups[g]['status'].upper()})" for g in goal_impacts if g in goal_rollups]
        
        # Suggested action
        if any(t.status == "broken" for t in tasks):
            action = "Fast-track vendor handoff, compress review cycle, or adjust downstream launch milestone in Notion."
        else:
            action = "Monitor timeline closely; buffer has shrunk below safety threshold."

        slack_block = {
            "recipient_owner": owner,
            "alert_status": "queued" if not within_hours else "sent",
            "dispatch_time_ist": sim_time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "delivery_status_display": f"{dispatch_header} (Next window: {next_window})" if not within_hours else dispatch_header,
            "slack_message_text": (
                f"{dispatch_header}\n"
                f"🚨 *Schedule Slip Alert: Impact on {owner}'s Deliverables*\n"
                f"• *Root Cause:* `{slipped_node.title}` (owned by {slipped_node.owner}) slipped by *{slipped_node.days_slipped} day(s)* (new due date: {slipped_node.current_due_date}).\n"
                f"• *Your Impacted Tasks:* {', '.join(impacted_titles)}\n"
                f"• *Goals At Risk:* {', '.join(goal_names) if goal_names else 'N/A'}\n"
                f"• *Reason:* {tasks[0].status_reason}\n"
                f"• *Suggested Action:* {action}\n"
                + (f"\n_Note: Sent outside operating hours (Mon-Sat 9am-7pm IST). Message queued until {next_window}._" if not within_hours else "")
            )
        }
        alerts.append(slack_block)
        
    return alerts

if __name__ == "__main__":
    import sys
    with open("data/approved_tasks.json") as f:
        tasks_data = json.load(f)

    graph = DependencyGraph(tasks_data)
    
    # Slipping task-1 (Artwork Export) by 4 days
    # Original due date: 2026-11-18 -> New due date: 2026-11-22
    # Karan's sample production is due 2026-11-20, so buffer becomes NEGATIVE (-2 days) -> BROKEN!
    print("=" * 80)
    print("SIMULATING SCHEDULE SLIP: task-1 (Artwork Export) slips by 4 days")
    print("=" * 80)

    # Test outside alert hours (e.g. 10:30 PM IST on Wednesday)
    test_sim_time = datetime(2026, 11, 18, 22, 30, tzinfo=IST)
    result = simulate_slip(graph, slipped_task_id="task-1", days_slipped=4, simulation_time_ist=test_sim_time)

    print("\n--- GOAL ROLL-UP STATUS ---")
    for gid, ginfo in result["goals"].items():
        print(f"Goal: {ginfo['name']} (Weight: {ginfo['weight']})")
        print(f"  Status: {ginfo['status'].upper()}")
        print(f"  Reason: {ginfo['reason']}")

    print("\n--- AFFECTED DOWNSTREAM TASKS ---")
    for t in result["affected_tasks"]:
        print(f"• [{t['id']}] {t['title']} | Owner: {t['owner']} | Status: {t['status'].upper()} | Buffer: {t['buffer_remaining']}d")
        print(f"   Reason: {t['reason']}")

    print("\n--- SLACK ALERT DISPATCHES (RESPECTING 9am-7pm IST ALERT HOURS) ---")
    for a in result["slack_alerts"]:
        print("\n" + "#" * 60)
        print(f"SLACK DM TO: {a['recipient_owner']}")
        print(f"STATUS: {a['delivery_status_display']}")
        print("-" * 60)
        print(a["slack_message_text"])

    # Persist simulation results
    with open("logs/slip_simulation_result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\n" + "=" * 80)
    print("Simulation results saved to logs/slip_simulation_result.json")
