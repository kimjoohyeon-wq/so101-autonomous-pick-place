# SO-101 Robot POC Bridge

Canonical bridge path:

`C:\Users\Research\Documents\Robot\bridge`

Purpose: file-based coordination between Codex, Hermes/DeepSeek, and the user
while working on the SO-101 paper-cup robot POC.

This bridge is not a live chat system. It is a durable shared workspace for
status, review requests, run records, and completion reports.

## Core Rule

Every meaningful work unit must leave a record before the next work unit starts.

Meaningful work units include:

- a physical robot run;
- a camera/data collection run;
- a code patch;
- a detector/model evaluation;
- a report/planning update;
- a failed/blocking attempt;
- a user-labeled observation.

## Files

| File | Owner | Purpose |
|---|---|---|
| `LIVE_TEST_STATUS.md` | current active runner | current live status and next decision |
| `HERMES_TO_CODEX.md` | Hermes/DeepSeek | review requests and status for Codex |
| `CODEX_TO_HERMES.md` | Codex | feedback, constraints, and next requested fixes |
| `RUN_INDEX.jsonl` | whoever runs tests | append-only index of physical/camera/data runs |
| `TASK_LOG.jsonl` | whoever completes work | append-only index of non-run work units |
| `templates\HERMES_LIVE_TEST_REPORT_TEMPLATE.md` | all | template for live physical test reports |
| `templates\WORK_COMPLETION_REPORT_TEMPLATE.md` | all | template for code/doc/offline work |
| `templates\RUN_INDEX_ENTRY.example.json` | all | JSONL entry example |

## Operating Loop

### For Hermes/DeepSeek live physical work

```text
PRECHECK -> ONE RUN -> USER LABEL -> ARTIFACT CHECK -> REPORT -> DECISION
```

After each run:

1. Append one line to `RUN_INDEX.jsonl`.
2. Update `LIVE_TEST_STATUS.md`.
3. If the run was part of a block, write a report under `reports\`.
4. If Codex review is needed, update `HERMES_TO_CODEX.md`.

### For Codex review work

1. Read `HANDOFF.md`.
2. Read this bridge `README.md`.
3. Read `LIVE_TEST_STATUS.md`.
4. Read the newest entries in `HERMES_TO_CODEX.md`, `RUN_INDEX.jsonl`, and
   `TASK_LOG.jsonl`.
5. Write feedback to `CODEX_TO_HERMES.md` and/or `reports\`.
6. Append one line to `TASK_LOG.jsonl`.

## Physical Safety Flags

Any work item that touches the robot must state:

```text
robot_motion: yes/no
com_ports: none/COM3/COM4/both
camera_devices: none/top/aux/both
gripper_close_or_lift: yes/no
user_approved_physical_step: yes/no
```

If `user_approved_physical_step` is not `yes`, do not run the physical step.

## Review Request Format

Hermes/DeepSeek should paste a short request into `HERMES_TO_CODEX.md`:

```text
## Request - YYYY-MM-DD HH:MM KST

Status:
What changed:
Files to review:
Commands run:
User labels:
Question for Codex:
Suggested next action:
```

## Stop Conditions

Stop physical testing and write a report if:

- same failure repeats twice after a patch;
- cup is pushed/knocked;
- robot sags or torque drops;
- camera role is uncertain;
- snapshots/video/result JSON are missing;
- script result contradicts user observation;
- detector reports success but frame is marked `needs_review`;
- gripper closes without cup in grasp zone.

## Current Priority

Current priority is not broad autonomous repetition. It is:

```text
camera role -> marker visibility -> state label -> review/success/failure
```

Hermes/DeepSeek may continue supervised physical tests only when the user has
explicitly approved the active test step.
