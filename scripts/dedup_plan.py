# -*- coding: utf-8 -*-
"""Remove duplicate (non-A) task sections from the plan document."""
import os

PLAN_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "docs", "superpowers", "plans", "2026-04-02-native-project-window.md",
)

SECTIONS_TO_DELETE = [
    ("### Task 19: Implement WorkspacePane", "### Task 20: Implement ProjectWindow"),
    ("### Task 20: Implement ProjectWindow", "### Task 21: Implement AppWorkspaceController"),
    ("### Task 21: Implement AppWorkspaceController", "### Task 22: Wire the controller into the launcher"),
    ("### Task 22: Wire the controller into the launcher", "### Task 23: Wire the controller into"),
    ("### Task 26: Add restore_workspace to the controller", "### Task 27: Wire save and restore into app startup/shutdown"),
    ("### Task 27: Wire save and restore into app startup/shutdown", "### Task 28: Run full test suite"),
]


def main():
    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print("Total lines before: %d" % len(lines))

    delete_ranges = []
    for start_heading, next_heading in SECTIONS_TO_DELETE:
        start_idx = None
        end_idx = None
        for i, line in enumerate(lines):
            if start_heading in line and start_idx is None:
                if line.lstrip().startswith("###"):
                    start_idx = i
            if start_idx is not None and next_heading in line and line.lstrip().startswith("###"):
                end_idx = i
                break
        if start_idx is not None and end_idx is not None:
            delete_ranges.append((start_idx, end_idx))
            print("  Delete lines %d-%d: %s" % (start_idx+1, end_idx, start_heading.strip()))
        else:
            print("  WARNING: Could not find section for '%s' (start=%s, end=%s)" % (start_heading, start_idx, end_idx))

    for start_idx, end_idx in reversed(delete_ranges):
        del lines[start_idx:end_idx]

    with open(PLAN_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("Total lines after: %d" % len(lines))
    print("Deleted %d lines across %d sections." % (
        sum(end - start for start, end in delete_ranges), len(delete_ranges)))


if __name__ == "__main__":
    main()
