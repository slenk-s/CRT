from pathlib import Path
p = Path(r'C:\Users\Administrator\Desktop\Pro\TChat-app\PCC_v1.0\frontend\src\views\LoginView.vue')
s = p.read_text(encoding='utf-8')
s = s.replace('</div>\n    </div>\n  </div>\n</template>', '</div>\n      <div class="login-rise-veil" :class="{ active: launching }"></div>\n    </div>\n  </div>\n</template>')
p.write_text(s, encoding='utf-8')
print('LoginView template patched')
