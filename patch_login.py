from pathlib import Path
p = Path(r"C:\Users\Administrator\Desktop\Pro\TChat-app\PCC_v1.0\frontend\src\views\LoginView.vue")
s = p.read_text(encoding='utf-8')
s = s.replace('const loading = ref(false)', 'const loading = ref(false)\nconst launching = ref(false)')
old = """  loading.value = true
  try {
    await user.login(form.emp_id.trim(), form.password)
    const redirect = (route.query.redirect as string) || '/changeover'
    router.replace(redirect)
  } catch {"""
new = """  loading.value = true
  try {
    await user.login(form.emp_id.trim(), form.password)
    launching.value = true
    await new Promise((resolve) => setTimeout(resolve, 520))
    const redirect = (route.query.redirect as string) || '/changeover'
    router.replace(redirect)
  } catch {"""
s = s.replace(old, new)
s = s.replace('</div>\n      <div class="login-footer">', '</div>\n      <div class="login-rise-veil" :class="{ active: launching }"></div>\n      <div class="login-footer">')
append = """

<style scoped>
.login-rise-veil {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  height: 0;
  z-index: 40;
  pointer-events: none;
  background:
    radial-gradient(circle at 14% 52%, rgba(64, 189, 255, .30), transparent 36%),
    radial-gradient(circle at 74% 48%, rgba(139, 92, 246, .28), transparent 42%),
    radial-gradient(circle at 50% 118%, rgba(45, 212, 191, .18), transparent 38%),
    linear-gradient(145deg, #07101d 0%, #0c1728 42%, #142847 78%, #08111f 100%);
  box-shadow: 0 -18px 60px rgba(56, 189, 248, .22);
  transform: translateY(0);
  opacity: 0;
  transition: height .52s cubic-bezier(.34,1.2,.5,1), opacity .18s ease .16s, transform .52s cubic-bezier(.34,1.2,.5,1);
}
.login-rise-veil.active {
  height: 100vh;
  opacity: 1;
  transform: translateY(0);
}
.login-rise-veil.active::after {
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
  opacity: .72;
  animation: topbar-glow-breathe 3.6s ease-in-out infinite;
}
</style>
"""
p.write_text(s + append, encoding='utf-8')
print('LoginView patched')
