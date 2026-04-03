# -*- coding: utf-8 -*-
lines = open(r"C:\Users\frena\Desktop\fontra-pak\docs\superpowers\plans\2026-04-02-native-project-window.md", encoding="utf-8").readlines()
print("Total lines: %d" % len(lines))
checks = [
    ("end of 22A / start of 23 area", 2618, 2628),
    ("end of 25 / start of 26A area", 3048, 3056),
    ("end of 27A / start of 28 area", 3610, 3620),
]
for label, lo, hi in checks:
    print("\n--- %s ---" % label)
    for i in range(lo, min(hi, len(lines))):
        print("  %d: %s" % (i+1, lines[i].rstrip()[:120]))
