# 5-Minute Loom Recording Script & Walkthrough Guide

Use this script while recording your screen. Keep your terminal on one side and VS Code / Markdown preview on the other.

---

## ⏱️ Timeline & Section Breakdown

| Time | Section | Screen to Show |
| :--- | :--- | :--- |
| **0:00 – 0:30** | What I Picked & Why | `BUILD_PLAN.md` (Top summary) |
| **0:30 – 1:00** | The Sample Data | `data/meeting_notes_2026-11-16.md` & `data/goals.json` |
| **1:00 – 3:00** | Live Demo: Extraction & Approval | Terminal: `pipeline.py` then `approve.py` |
| **3:00 – 4:00** | Slip Cascade Simulation | Terminal: `test_scenarios.py` |
| **4:00 – 5:00** | Architecture, Buy vs. Build, Failures & Cost | `BUILD_PLAN.md` (Diagram, Tables & Runbook) |

---

### [0:00 – 0:30] 1. What I Picked and Why

**Screen:** Open [BUILD_PLAN.md](file:///Users/srijantelang27/Desktop/Personal/product/BUILD_PLAN.md) showing Section 1.

> **Spoken Script:**  
> "Hi everyone. For this assignment, I built an end-to-end AI operations engine that takes unstructured, multilingual meeting notes, extracts structured commitments through a human-in-the-loop review workflow, and simulates schedule slip cascades across an in-memory dependency graph with time-zoned Slack alerts.  
>  
> I chose to ship extraction, human staging, and the slip cascade engine first because downstream slip alerts across dependent chains are the core problem founders face, and it's what the trial's pass test measures. Without reliable extraction and verified commitments, there's nothing trustworthy to track. I intentionally deferred automated priority ranking to v2 so we could focus 100% on getting the dependency physics and delay mechanics right."

---

### [0:30 – 1:00] 2. The Sample Data

**Screen:** Switch to [data/meeting_notes_2026-11-16.md](file:///Users/srijantelang27/Desktop/Personal/product/data/meeting_notes_2026-11-16.md). Highlight lines with Hindi/Gujarati phrases.

> **Spoken Script:**  
> "Let’s look at the sample data. In early-stage Indian startups, syncs are rarely neat English transcripts. They're informal, fast-paced, and multilingual.  
>  
> In this synthetic meeting note, I specifically engineered realistic edge cases:  
> 1. **Mixed Hinglish and Gujarati code-switching**—like Karan saying *'vendor sample Friday tak ready ho jayega'* and *'pachhi j bulk production order trigger karvano chhe'*.  
> 2. **A 4-step dependency chain** for our Diwali Gift Box launch: packaging artwork $\rightarrow$ vendor physical sample $\rightarrow$ sample inspection $\rightarrow$ bulk run and warehouse dispatch.  
> 3. **Relative dates** like 'this Wednesday' and 'Friday', which must resolve to exact calendar dates relative to the meeting date of November 16th.  
> 4. And finally, **conversational chatter and ambiguous brainstorms**—like *'someone should write campaign copy'*—which shouldn't become committed tasks without an owner or deadline."

---

### [1:00 – 3:00] 3. Extraction, Flagged Items & Human Approval

**Screen:** Split terminal. Run Command 1.

```bash
PYTHONPATH=. ./.venv/bin/python src/pipeline.py
```

> **Spoken Script:**  
> "Now let's run the extraction pipeline.  
> *(Wait 2-3 seconds for pipeline output)*  
>  
> Behind the scenes, this calls Groq using `openai/gpt-oss-20b`. A key finding during prototyping: because 20B is a reasoning model, default settings burned over 2,000 tokens on internal chain-of-thought, hitting token limits. By setting `reasoning_effort='low'` and expanding completion tokens, it drops reasoning burn to under 600 tokens and returns valid JSON on attempt 1. Cost per meeting is under one-tenth of a cent—about **$0.00032**.  
>  
> The output passes strict Pydantic validation and deterministic business rules—checking for cycles, team roster matching, and temporal bounds."

**Screen:** Now run Command 2 (Interactive Review):

```bash
PYTHONPATH=. ./.venv/bin/python src/approve.py
```

> **Spoken Script:**  
> "Next is the human approval workflow. An LLM should propose, but a human must commit.  
>  
> Notice how flagged items stand out:  
> - Task 1 (Packaging Artwork) has full owner and date, so I'll press `a` to **Approve**. *(Press Enter)*  
> - Task 2 (Vendor Sample): Let's say I want to reassign this from Karan to Vikram. I press `e` for **Edit**, type `Vikram Desai`, and keep the date. *(Type Vikram Desai, hit Enter)*  
> - Task 3 (Inspection): Press `a` to **Approve**.  
> - Task 4 (Bulk Run): The model correctly flagged this with `needs_confirmation: true` because no explicit deadline was stated. I press `e` to edit, keep Karan as owner, and type `2026-12-05` because the meeting note anchored it to the Dec 5 launch date. *(Type 2026-12-05, hit Enter)*  
> - Task 5 (Influencer Roster): Press `a` to **Approve**.  
> - Task 6 (Teaser Reels): Unspecified deadline. I press `r` to **Reject** and enter the reason: *'Postponed until after Diwali launch'*. *(Hit Enter)*  
>  
> At the bottom, our accuracy benchmark shows: **5 of 5 core tasks correct (100%), 2 of 2 ambiguous items correctly flagged, and zero hallucinated owners**.  
>  
> To be completely transparent: for downstream simulation, our approved dataset is hand-curated, because as our 5-run stability benchmark proved, task counts can wobble slightly between 5 and 8 on borderline conversational remarks. That’s why human review is an intentional design rule."

---

### [3:00 – 4:00] 4. Schedule Slip Cascade Simulation

**Screen:** In the terminal, run Command 3:

```bash
PYTHONPATH=. ./.venv/bin/python src/test_scenarios.py
```

> **Spoken Script:**  
> "Now for the core differentiator: the dependency graph and slip cascade simulation.  
>  
> In simple project management tools, slack is zero by construction because tasks are scheduled back-to-back. If task 1 slips by a day, every downstream task breaks. That’s not how real projects work.  
>  
> In our graph engine in `src/graph.py`, we explicitly **separate task duration from schedule slack**:  
> Let’s look at **Scenario A**, where Task 1 (artwork) slips by 1 day:  
> - **Task 2** (Vendor Sample) has zero slack buffer, so it turns 🔴 **BROKEN**—it will finish 1 day late.  
> - **Task 3** (Inspection) absorbs part of the delay, but its remaining buffer erodes to 1 day. That’s below our safety threshold, so it is marked 🟡 **AT_RISK**.  
> - **Task 4** (Bulk Run) has a healthy 7-day buffer before launch, so the upstream slip is absorbed cleanly—it stays 🟢 **SAFE**.  
> - Company Goal 1 rolls up to 🟡 **AT_RISK**: the schedule is compressed, but the final December 5th launch is still protected!  
>  
> Notice the alerts dispatched at the bottom: Pooja gets a confirmation alert, while Vikram and Aarav receive downstream cascade alerts explaining the root cause and suggested action. Furthermore, the engine respects **IST business hours** (9am–7pm Mon–Sat): if a slip occurs at 10:30 PM, alerts are automatically queued for 9:00 AM the next business day."

---

### [4:00 – 5:00] 5. Architecture, Buy vs. Build, Failures & Cost

**Screen:** Switch back to [BUILD_PLAN.md](file:///Users/srijantelang27/Desktop/Personal/product/BUILD_PLAN.md). Point to Section 2 (Production Architecture) and Sections 4–6.

> **Spoken Script:**  
> "Finally, let's look at how this scales into production.  
>  
> **Architecture:**  
> In production, meeting notes originate in Notion—or directly via Notion AI Meeting Notes. A webhook triggers our ingestion and extraction service. Instead of a CLI, proposed tasks are dispatched to Slack via Block Kit cards with interactive Approve, Edit, and Reject buttons. Approved commitments write back to the canonical Notion Tasks database. A background worker polls every 10 to 15 minutes, listening for due-date changes, and triggers our slip cascade engine to dispatch time-zoned Slack alerts.  
>  
> **Buy vs. Build:**  
> - We **buy** Notion for the task database, Slack for user interaction, the LLM API for inference, and cloud hosting like Render or AWS Lambda.  
> - We **build** the multilingual extraction prompt and the slip cascade engine, because off-the-shelf tools don't parse informal Indian speech, nor do they calculate transitive buffer erosion across multi-node chains.  
>  
> **Failures & Runbook:**  
> We have three common failure modes covered:  
> 1. *Notion API errors* are buffered in a dead-letter queue with exponential backoff (1m, 5m, 15m), alerting `#ops-alerts` if persistent.  
> 2. *Model hallucination or cycle errors* are caught by our business rules. Our `--simulate-break` test proves that injected cycles are caught, fed back, and self-corrected on Attempt 2.  
> 3. *Slack delivery failures* fallback from direct DMs to the public `#project-alerts` channel.  
>  
> **Monthly Cost:**  
> For a 20-person startup running 40 meetings a month, LLM inference costs just **1.8 cents per month** on Groq. Including a $5 to $10 serverless hosting tier on Render or Railway, the entire production system operates for **under $10 a month**.  
>  
> Thanks for watching!"

---

## 💡 Quick Tips for Recording
1. **Pacing:** Speak at a steady, confident pace. Don't rush; the script is ~620 words, which naturally takes 4 minutes and 30 seconds at a normal speaking pace (130-140 words/min).
2. **Terminal Text Size:** Increase your terminal font size (`Cmd + +` twice) so the tables and status icons (`🔴`, `🟡`, `🟢`) are crisp on camera.
3. **Keep Commands Ready:** You can have the commands typed or in your shell history so you can just hit Up-Arrow + Enter smoothly.
