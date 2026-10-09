const fs = require('fs');
const path = 'C:/Users/Administrator/Desktop/Pro/TChat-app/PCC_v1.0/frontend/src/styles/index.css';
let s = fs.readFileSync(path, 'utf8');
const old = `/* 顶部导航（深色） */
.topbar {
  position: sticky; top: 0; z-index: 20;
  display: flex; align-items: center; gap: 12px;
  padding: 0 24px; height: 56px;
  background: var(--topbar); color: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, .15);
}`;
const neu = `/* 顶部导航（深色） */
.topbar {
  position: sticky; top: 0; z-index: 20;
  display: flex; align-items: center; gap: 12px;
  padding: 0 24px; height: 56px;
  background:
    radial-gradient(circle at 12% 50%, rgba(64, 189, 255, .22), transparent 38%),
    radial-gradient(circle at 72% 50%, rgba(139, 92, 246, .18), transparent 42%),
    linear-gradient(180deg, #1f2d3d 0%, #172231 100%);
  color: #fff;
  box-shadow: 0 12px 28px rgba(0, 0, 0, .22), 0 1px 0 rgba(255, 255, 255, .06) inset;
}
.topbar::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -26px;
  width: min(760px, 90vw);
  height: 116px;
  transform: translateX(-50%) scale(.98);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56, 189, 248, .70) 0%, rgba(139, 92, 246, .42) 36%, transparent 70%);
  filter: blur(42px);
  opacity: .56;
  z-index: -1;
  pointer-events: none;
  animation: topbar-glow-breathe 3.6s ease-in-out infinite;
}
@keyframes topbar-glow-breathe {
  0%, 100% { opacity: .38; transform: translateX(-50%) scale(.96); }
  50% { opacity: .86; transform: translateX(-50%) scale(1.05); }
}`;
if (!s.includes(old)) {
  console.error('old block not found');
  process.exit(1);
}
fs.writeFileSync(path, s.replace(old, neu));
console.log('patched');
