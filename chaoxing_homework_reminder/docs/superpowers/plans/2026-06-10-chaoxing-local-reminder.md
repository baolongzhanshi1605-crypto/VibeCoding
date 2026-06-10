# Chaoxing Local Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Windows-friendly homework reminder that can later read Chaoxing assignments and notify by WeChat/popup without modifying system settings by default.

**Architecture:** Keep reminder policy, sent-state suppression, assignment providers, and notifiers separate. The first working version uses a manual JSON provider so reminder behavior can be tested safely before adding Chaoxing-specific HTTP parsing.

**Tech Stack:** Python 3.11 standard library, `unittest`, JSON config/state, optional PushPlus HTTP API.

---

### Task 1: Reminder Rules

**Files:**
- Create: `cx_reminder/models.py`
- Create: `cx_reminder/policy.py`
- Test: `tests/test_policy.py`

- [x] Write tests for submitted, urgent, strong, preview, overdue, and outside-window decisions.
- [x] Verify tests fail before modules exist.
- [x] Implement `Assignment`, `ReminderDecision`, `ReminderTier`, and `ReminderPolicy`.
- [x] Verify policy tests pass.

### Task 2: Duplicate Suppression

**Files:**
- Create: `cx_reminder/state.py`
- Test: `tests/test_state.py`

- [x] Write tests for once-daily preview reminders, 15-minute urgent reminders, and `NONE` suppression.
- [x] Verify tests fail before state module exists.
- [x] Implement JSON-backed sent-state tracking.
- [x] Verify state tests pass.

### Task 3: Safe Provider and Message Formatting

**Files:**
- Create: `cx_reminder/providers/manual_json.py`
- Create: `cx_reminder/notifiers/messages.py`
- Test: `tests/test_manual_provider.py`
- Test: `tests/test_messages.py`

- [x] Write tests for loading assignments from local JSON.
- [x] Write tests for human-readable reminder text.
- [x] Implement provider and formatter.
- [x] Verify tests pass.

### Task 4: Runner and Notifiers

**Files:**
- Create: `cx_reminder/runner.py`
- Create: `cx_reminder/notifiers/console.py`
- Create: `cx_reminder/notifiers/pushplus.py`
- Create: `cx_reminder/notifiers/windows_popup.py`
- Create: `cx_reminder/cli.py`
- Test: `tests/test_runner.py`

- [x] Write runner test for fetching, deciding, sending, and recording a reminder.
- [x] Verify test fails before runner exists.
- [x] Implement runner and CLI.
- [x] Verify tests pass.

### Task 5: Documentation and Safe Setup

**Files:**
- Create: `README.md`
- Create: `config.example.json`
- Create: `data/manual_assignments.example.json`
- Create: `run_check.ps1`

- [x] Document that no system settings are modified.
- [x] Document PushPlus setup and local test commands.
- [x] Document Chaoxing integration principles that avoid abnormal login or high-frequency polling.
- [x] Provide a PowerShell helper script that only runs the local checker.

