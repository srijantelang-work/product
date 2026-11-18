import json
import os
from datetime import datetime, timedelta, time, timezone
from typing import Dict, List, Any, Optional, Tuple

IST = timezone(timedelta(hours=5, minutes=30))
ALERT_START_TIME = time(9, 0)   # 9:00 AM IST
ALERT_END_TIME = time(19, 0)    # 7:00 PM IST
BUFFER_THRESHOLD_DAYS = 1       # 1 day buffer or less is considered 'at_risk'

def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    return datetime.strptime(date_str, "%Y-%m-%d")

def format_date(dt: Optional[datetime]) -> str:
    if not dt:
        return "TBD"
    return dt.strftime("%Y-%m-%d")

def is_within_alert_hours(dt: datetime) -> bool:
    if dt.weekday() == 6:  # Sunday
        return False
    local_time = dt.time()
    return ALERT_START_TIME <= local_time <= ALERT_END_TIME

def get_next_alert_window(dt: datetime) -> datetime:
    curr = dt
    if curr.time() > ALERT_END_TIME:
        curr = (curr + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif curr.time() < ALERT_START_TIME:
        curr = curr.replace(hour=9, minute=0, second=0, microsecond=0)
    if curr.weekday() == 6:  # Sunday
        curr = (curr + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return curr

class TaskNode:
    def __init__(self, data: Dict[str, Any]):
        self.id = data["id"]
        self.title = data["title"]
        self.owner = data.get("owner")
        self.goal = data.get("goal")
        self.committed_due_date = data.get("due_date")
        self.projected_finish_date = data.get("due_date")
        self.depends_on: List[str] = data.get("depends_on", [])
        self.downstream: List[str] = []
        self.status = "safe"  # safe, at_risk, broken
        self.buffer_remaining: Optional[int] = None
        self.delay_days: int = 0
        self.diagnostic_reason: Optional[str] = None

class CascadeDependencyGraph:
    def __init__(self, tasks: List[Dict[str, Any]]):
        self.nodes: Dict[str, TaskNode] = {t["id"]: TaskNode(t) for t in tasks}
        self.planned_durations: Dict[Tuple[str, str], int] = {}
        self._build_edges_and_durations()

    def _build_edges_and_durations(self):
        for node in self.nodes.values():
            for parent_id in node.depends_on:
                if parent_id in self.nodes:
                    self.nodes[parent_id].downstream.append(node.id)
                    parent_due = parse_date(self.nodes[parent_id].committed_due_date)
                    child_due = parse_date(node.committed_due_date)
                    if parent_due and child_due and child_due >= parent_due:
                        gap = (child_due - parent_due).days
                    else:
                        gap = 1
                    self.planned_durations[(parent_id, node.id)] = gap

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

    def simulate_cascade(
        self,
        slipped_task_id: str,
        slip_days: int,
        simulation_time_ist: datetime
    ) -> Dict[str, Any]:
        if slipped_task_id not in self.nodes:
            raise ValueError(f"Task {slipped_task_id} not found.")

        for node in self.nodes.values():
            node.projected_finish_date = node.committed_due_date
            node.status = "safe"
            node.buffer_remaining = None
            node.delay_days = 0
            node.diagnostic_reason = None

        root = self.nodes[slipped_task_id]
        root_committed_dt = parse_date(root.committed_due_date)
        if not root_committed_dt:
            raise ValueError(f"Task {slipped_task_id} has no due date.")

        root.delay_days = slip_days
        new_root_finish = root_committed_dt + timedelta(days=slip_days)
        root.projected_finish_date = format_date(new_root_finish)
        
        if slip_days > 0:
            root.status = "broken"
            root.diagnostic_reason = f"Root cause of delay: slipped by {slip_days} day(s) from committed date {root.committed_due_date} to {root.projected_finish_date}."

        topo_order = self.topological_order()
        start_eval = False

        for nid in topo_order:
            if nid == slipped_task_id:
                start_eval = True
                continue
            if not start_eval:
                continue

            node = self.nodes[nid]
            committed_dt = parse_date(node.committed_due_date)
            if not committed_dt or not node.depends_on:
                continue

            earliest_finish = committed_dt
            min_buffer = 999
            controlling_parent = None

            for parent_id in node.depends_on:
                parent = self.nodes[parent_id]
                parent_proj_dt = parse_date(parent.projected_finish_date)
                if not parent_proj_dt:
                    continue
                
                planned_gap = self.planned_durations.get((parent_id, node.id), 1)
                required_child_finish = parent_proj_dt + timedelta(days=planned_gap)
                if required_child_finish > earliest_finish:
                    earliest_finish = required_child_finish
                    controlling_parent = parent

                buffer_gap = (committed_dt - parent_proj_dt).days
                if buffer_gap < min_buffer:
                    min_buffer = buffer_gap

            node.projected_finish_date = format_date(earliest_finish)
            node.buffer_remaining = min_buffer

            if earliest_finish > committed_dt:
                days_over = (earliest_finish - committed_dt).days
                node.delay_days = days_over
                node.status = "broken"
                node.diagnostic_reason = (
                    f"Cascade bottleneck: finishes {days_over} day(s) late on {format_date(earliest_finish)} "
                    f"(committed: {format_date(committed_dt)}) due to upstream slip on '{controlling_parent.title}'."
                )
            elif min_buffer <= BUFFER_THRESHOLD_DAYS:
                node.status = "at_risk"
                node.diagnostic_reason = (
                    f"Timeline at risk: buffer with upstream '{controlling_parent.title}' "
                    f"eroded to {min_buffer} day(s) (threshold: <= {BUFFER_THRESHOLD_DAYS} day)."
                )
            else:
                node.status = "safe"
                node.diagnostic_reason = f"Healthy buffer of {min_buffer} day(s)."

        goal_rollups = self._compute_goal_rollups()
        alerts = self._build_slack_alerts(root, simulation_time_ist, goal_rollups)

        return {
            "root_cause_task": {
                "id": root.id,
                "title": root.title,
                "owner": root.owner,
                "slip_days": slip_days,
                "committed_date": root.committed_due_date,
                "projected_finish": root.projected_finish_date,
            },
            "downstream_impacts": [
                {
                    "id": self.nodes[nid].id,
                    "title": self.nodes[nid].title,
                    "owner": self.nodes[nid].owner,
                    "committed_date": self.nodes[nid].committed_due_date,
                    "projected_finish": self.nodes[nid].projected_finish_date,
                    "status": self.nodes[nid].status,
                    "buffer_remaining": self.nodes[nid].buffer_remaining,
                    "reason": self.nodes[nid].diagnostic_reason
                }
                for nid in topo_order if nid != slipped_task_id and self.nodes[nid].status in ["broken", "at_risk"]
            ],
            "goal_rollups": goal_rollups,
            "slack_alerts": alerts
        }

    def _compute_goal_rollups(self) -> Dict[str, Any]:
        with open("data/goals.json") as f:
            goals = {g["id"]: g for g in json.load(f)}

        rollups = {}
        for gid, ginfo in goals.items():
            tasks = [n for n in self.nodes.values() if n.goal == gid]
            if not tasks:
                continue

            target_dt = parse_date(ginfo["target_date"])
            broken_tasks = [t for t in tasks if t.status == "broken"]
            at_risk_tasks = [t for t in tasks if t.status == "at_risk"]

            latest_task_finish = max([parse_date(t.projected_finish_date) for t in tasks if parse_date(t.projected_finish_date)])

            if broken_tasks or (latest_task_finish and latest_task_finish > target_dt):
                status = "off_track"
                slip_delta = (latest_task_finish - target_dt).days if (latest_task_finish and latest_task_finish > target_dt) else broken_tasks[0].delay_days
                reason = f"Launch will miss target {ginfo['target_date']} by {slip_delta} day(s) because '{broken_tasks[0].title}' is delayed."
            elif at_risk_tasks:
                status = "at_risk"
                reason = f"Milestone tight; '{at_risk_tasks[0].title}' buffer eroded to {at_risk_tasks[0].buffer_remaining} day(s)."
            else:
                status = "on_track"
                reason = "All milestone deliverables on schedule with healthy buffers."

            rollups[gid] = {
                "name": ginfo["name"],
                "target_date": ginfo["target_date"],
                "weight": ginfo["weight"],
                "projected_completion": format_date(latest_task_finish),
                "status": status,
                "consequence_reason": reason
            }
        return rollups

    def _build_slack_alerts(
        self,
        root: TaskNode,
        sim_time: datetime,
        goal_rollups: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        alerts = []
        within_hours = is_within_alert_hours(sim_time)
        next_window = None if within_hours else get_next_alert_window(sim_time).strftime("%A, %d %b %Y, 09:00 AM IST")
        header = "🟢 [DISPATCHED IMMEDIATELY]" if within_hours else "⏰ [QUEUED UNTIL NEXT ALERT WINDOW]"

        # Alert to root owner (confirmation)
        root_msg = {
            "recipient_owner": root.owner,
            "type": "root_confirmation",
            "delivery_status": header,
            "slack_message_text": (
                f"{header}\n"
                f"⚠️ *Schedule Update Confirmation Needed: {root.owner}*\n"
                f"• *Task:* `{root.title}`\n"
                f"• *Status:* Proposed slip of *{root.delay_days} day(s)* (committed: {root.committed_due_date} ➔ new: {root.projected_finish_date}).\n"
                f"• *Action Required:* Please confirm or adjust this date in Notion to lock the new milestone.\n"
                + (f"\n_Note: Outside alert hours (Mon-Sat 9am-7pm IST). Message queued until {next_window}._" if not within_hours else "")
            )
        }
        alerts.append(root_msg)

        # Downstream alerts grouped by owner
        owner_tasks: Dict[str, List[TaskNode]] = {}
        for node in self.nodes.values():
            if node.id != root.id and node.status in ["broken", "at_risk"] and node.owner:
                owner_tasks.setdefault(node.owner, []).append(node)

        for owner, tasks in owner_tasks.items():
            impact_lines = [f"• `{t.title}`: {t.diagnostic_reason}" for t in tasks]
            affected_goals = list({t.goal for t in tasks if t.goal})
            goal_lines = [f"• *{goal_rollups[g]['name']}* (Status: {goal_rollups[g]['status'].upper()}): {goal_rollups[g]['consequence_reason']}" 
                          for g in affected_goals if g in goal_rollups]

            action = (
                "Expedite vendor turnaround, compress review cycle, or request milestone re-alignment in Notion."
                if any(t.status == "broken" for t in tasks)
                else "Monitor closely; schedule buffer has eroded below safety margins."
            )

            msg = {
                "recipient_owner": owner,
                "type": "downstream_cascade_alert",
                "delivery_status": header,
                "slack_message_text": (
                    f"{header}\n"
                    f"🚨 *Upstream Delay Alert: Impact on {owner}'s Deliverables*\n"
                    f"• *Root Cause:* `{root.title}` ({root.owner}) slipped by *{root.delay_days} day(s)* (projected finish: {root.projected_finish_date}).\n"
                    f"• *Your Impacted Tasks:*\n" + "\n".join(impact_lines) + "\n"
                    f"• *Company Goals Impacted:*\n" + "\n".join(goal_lines) + "\n"
                    f"• *Suggested Action:* {action}\n"
                    + (f"\n_Note: Outside alert hours (Mon-Sat 9am-7pm IST). Message queued until {next_window}._" if not within_hours else "")
                )
            }
            alerts.append(msg)

        return alerts
