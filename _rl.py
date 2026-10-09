from pathlib import Path
s = Path("frontend/src/views/ChangeoverListView.vue").read_text(encoding="utf-8")
lines = s.split("\n")
for i in range(158, min(200, len(lines))):
    print(f"{i+1}: {lines[i]}")
