from pathlib import Path
s = Path("frontend/src/views/ChangeoverListView.vue").read_text(encoding="utf-8")
lines = s.split("\n")
# Find where cards are rendered and where click handler is
for i, line in enumerate(lines, 1):
    if any(k in line for k in ['class="card', 'sess', '@click', 'goDetail', 'router.push', 'router-link', 'router-view', 'transition']):
        print(f"{i}: {line}")
