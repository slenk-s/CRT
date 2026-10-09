from pathlib import Path
p = Path(r'C:\Users\Administrator\Desktop\Pro\TChat-app\PCC_v1.0\frontend\src\views\LoginView.vue')
s = p.read_text(encoding='utf-8')
s = s.replace('''  <div class="login-wrap">
    <div class="login-stage">''', '''  <div class="login-wrap" :class="{ launching }">
    <div class="login-stage">''')
s = s.replace('''  transition: height .52s cubic-bezier(.34,1.2,.5,1), opacity .18s ease .16s, transform .52s cubic-bezier(.34,1.2,.5,1);
}''', '''  transition: height .52s cubic-bezier(.34,1.2,.5,1), opacity .18s ease .16s, transform .52s cubic-bezier(.34,1.2,.5,1);
}
.login-wrap { transition: transform .52s cubic-bezier(.34,1.2,.5,1), filter .52s ease, opacity .52s ease; }
.login-wrap.launching { transform: translateY(-28px) scale(1.01); filter: brightness(1.02); }''')
p.write_text(s, encoding='utf-8')
print('LoginView transition patched')
