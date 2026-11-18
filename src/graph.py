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
        self.estimated_duration_days: int = data.get("estimated_duration_days", 1)
        self.depends_on: List[str] = data.get("depends_on", [])
        self.downstream: List[str] = []
        self.status = "safe"  # safe, at_risk, broken
        self.buffer_remaining: Optional[int] = None
        self.delay_days: int = 0
        self.diagnostic_reason: Optional[str] = None

class CascadeDependencyGraph:
    def __init__(self, tasks: List[Dict[str, Any]]):
        self.nodes: Dict[str, TaskNode] = {t["id"]: TaskNode(t) for t in tasks}
        self._build_edges()

    def _build_edges(self):
        """Build downstream edges from depends_on relationships."""
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

    def simulate_cascade(
        self,
        slipped_task_id: str,
        slip_days: int,
        simulation_time_ist: datetime
    ) -> Dict[str, Any]:
        if slipped_task_id not in self.nodes:
            raise ValueError(f"Task {slipped_task_id} not found.")

        # Reset all nodes
        for node in self.nodes.values():
            node.projected_finish_date = node.committed_due_date
            node.status = "safe"
            node.buffer_remaining = None
            node.delay_days = 0
            node.diagnostic_reason = None

        # Apply slip to root task
        root = self.nodes[slipped_task_id]
        root_committed_dt = parse_date(root.committed_due_date)
        if not root_committed_dt:
            raise ValueError(f"Task {slipped_task_id} has no due date.")

        root.delay_days = slip_days
        new_root_finish = root_committed_dt + timedelta(days=slip_days)
        root.projected_finish_date = format_date(new_root_finish)

        if slip_days > 0:
            root.status = "broken"
            root.diagnostic_reason = (
                f"Root cause of delay: slipped by {slip_days} day(s) "
                f"from committed date {root.committed_due_date} to {root.projected_finish_date}."
            )

        # Propagate through topological order
        # Key change: separate duration from slack.
        # For each child:
        #   earliest_start = max(upstream projected finish dates)
        #   projected_finish = earliest_start + child.estimated_duration_days
        #   But projected_finish can't be earlier than committed_due (work won't start early)
        #   slack = planned_gap - child.estimated_duration_days
        #   buffer_remaining = committed_due - projected_finish (in days)
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

            # Find the latest upstream projected finish (the bottleneck parent)
            latest_upstream_finish = None
            controlling_parent = None

            for parent_id in node.depends_on:
                parent = self.nodes.get(parent_id)
                if not parent:
                    continue
                parent_proj_dt = parse_date(parent.projected_finish_date)
                if not parent_proj_dt:
                    continue
                if latest_upstream_finish is None or parent_proj_dt > latest_upstream_finish:
                    latest_upstream_finish = parent_proj_dt
                    controlling_parent = parent

            if latest_upstream_finish is None:
                continue

            # Child can't start until upstream finishes.
            # work_finish = when the work would actually complete if started right after upstream.
            work_finish = latest_upstream_finish + timedelta(days=node.estimated_duration_days)

            # Buffer: how many days of slack between work_finish and committed due date.
            # Positive = slack remaining, negative = overdue.
            buffer = (committed_dt - work_finish).days
            node.buffer_remaining = buffer

            # For display/propagation: if work finishes after committed, that's the new projected date.
            # If work finishes before committed, projected stays at committed (we don't finish early for
            # downstream propagation purposes — but we report the real buffer above).
            projected_finish = max(work_finish, committed_dt)
            node.projected_finish_date = format_date(projected_finish)

            if work_finish > committed_dt:
                # BROKEN: projected finish is past committed due date
                days_over = (projected_finish - committed_dt).days
                node.delay_days = days_over
                node.status = "broken"
                node.diagnostic_reason = (
                    f"Cascade impact: will finish {days_over} day(s) late on {format_date(projected_finish)} "
                    f"(committed: {format_date(committed_dt)}). "
                    f"Upstream '{controlling_parent.title}' now finishes {controlling_parent.projected_finish_date}, "
                    f"plus {node.estimated_duration_days}d of work pushes past deadline."
                )
            elif buffer <= BUFFER_THRESHOLD_DAYS:
                # AT_RISK: makes it, but slack has eroded to threshold or below
                node.status = "at_risk"
                node.diagnostic_reason = (
                    f"Buffer eroded: only {buffer} day(s) of slack remaining "
                    f"(threshold: ≤ {BUFFER_THRESHOLD_DAYS}d). "
                    f"Upstream '{controlling_parent.title}' finishes {controlling_parent.projected_finish_date}, "
                    f"plus {node.estimated_duration_days}d of work leaves tight margin."
                )
            else:
                # SAFE: slack absorbed the delay
                node.status = "safe"
                node.diagnostic_reason = (
                    f"Slack absorbed: {buffer} day(s) of buffer remaining. "
                    f"Upstream delay did not consume enough slack to threaten this deadline."
                )

        goal_rollups = self._compute_goal_rollups()
        alerts = self._build_slack_alerts(root, simulation_time_ist, goal_rollups)

        # Include all evaluated downstream tasks (not just broken/at_risk) for transparency
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
                    "estimated_duration_days": self.nodes[nid].estimated_duration_days,
                    "status": self.nodes[nid].status,
                    "buffer_remaining": self.nodes[nid].buffer_remaining,
                    "reason": self.nodes[nid].diagnostic_reason
                }
                for nid in topo_order if nid != slipped_task_id and self.nodes[nid].depends_on
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

            projected_dates = [parse_date(t.projected_finish_date) for t in tasks if parse_date(t.projected_finish_date)]
            latest_task_finish = max(projected_dates) if projected_dates else None

            if latest_task_finish and latest_task_finish > target_dt:
                # Goal target date will be missed
                status = "off_track"
                slip_delta = (latest_task_finish - target_dt).days
                worst_task = max(broken_tasks, key=lambda t: t.delay_days) if broken_tasks else tasks[0]
                reason = (
                    f"Launch will miss target {ginfo['target_date']} by {slip_delta} day(s). "
                    f"Critical path: '{worst_task.title}' now finishes {worst_task.projected_finish_date}."
                )
            elif broken_tasks:
                # Intermediate tasks broken but final goal deadline still met — schedule compressed
                status = "at_risk"
                reason = (
                    f"Schedule compressed: '{broken_tasks[0].title}' finishes "
                    f"{broken_tasks[0].delay_days} day(s) late. Launch date {ginfo['target_date']} "
                    f"still achievable but downstream slack is consumed."
                )
            elif at_risk_tasks:
                status = "at_risk"
                reason = (
                    f"Milestone tight: '{at_risk_tasks[0].title}' has only "
                    f"{at_risk_tasks[0].buffer_remaining} day(s) of buffer remaining."
                )
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

        # Downstream alerts grouped by owner — only for broken or at_risk tasks
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
