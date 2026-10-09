from pathlib import Path
p = Path(r'C:\Users\Administrator\Desktop\Pro\TChat-app\PCC_v1.0\frontend\src\styles\index.css')
s = p.read_text(encoding='utf-8')
start = s.index('/* 顶部导航（深色） */')
end = s.index('.brand { font-size: 16px;', start)
new = '''/* 顶部导航（深色 + 登录背景承接渐变） */
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 24px;
  height: 56px;
  color: #fff;
  overflow: hidden;
  background:
    radial-gradient(circle at 14% 52%, rgba(64, 189, 255, .30), transparent 36%),
    radial-gradient(circle at 74% 48%, rgba(139, 92, 246, .28), transparent 42%),
    radial-gradient(circle at 50% 118%, rgba(45, 212, 191, .18), transparent 38%),
    linear-gradient(145deg, #07101d 0%, #0c1728 42%, #142847 78%, #08111f 100%);
  box-shadow: 0 12px 28px rgba(0, 0, 0, .24), inset 0 1px 0 rgba(255,255,255,.08);
}
.topbar::before {
  content: '';
  position: absolute;
  inset: -42% -18% -18% -18%;
  background:
    radial-gradient(circle at 18% 24%, rgba(48, 213, 255, .32), transparent 24%),
    radial-gradient(circle at 80% 32%, rgba(139, 92, 246, .26), transparent 28%),
    radial-gradient(circle at 48% 88%, rgba(45, 212, 191, .20), transparent 28%);
  filter: blur(28px);
  opacity: .78;
  pointer-events: none;
  animation: topbar-bg-drift 10s ease-in-out infinite alternate;
}
.topbar::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: -48px;
  width: min(860px, 94vw);
  height: 150px;
  transform: translateX(-50%) scale(.96);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56, 189, 248, .62) 0%, rgba(99, 102, 241, .38) 35%, transparent 70%);
  filter: blur(42px);
  opacity: .52;
  pointer-events: none;
  animation: topbar-glow-breathe 3.6s ease-in-out infinite;
}
.topbar > * { position: relative; z-index: 1; }
@keyframes topbar-bg-drift {
  from { transform: translate3d(0, 0, 0) scale(1); }
  to { transform: translate3d(18px, -12px, 0) scale(1.08); }
}
@keyframes topbar-glow-breathe {
  0%, 100% { opacity: .34; transform: translateX(-50%) scale(.94); }
  50% { opacity: .82; transform: translateX(-50%) scale(1.05); }
}
'''
p.write_text(s[:start] + new + s[end:], encoding='utf-8')
print('index.css patched')
