import pathlib, re, sys
ROOT = pathlib.Path(r'C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab')
BM = ROOT / 'runtime' / 'boot_manager.py'
MW = ROOT / 'gui' / 'main_window.py'
mw_txt = MW.read_text(encoding='utf-8')
mw_orig = mw_txt
mw_txt = re.sub(r'_html_content\s*=\s*_html_path\.read_text\([^)]+\)\s*\n\s*_web_view\.setHtml\([^)]+\)', '_web_view.setUrl(_QUrl("http://127.0.0.1:5000/ops"))', mw_txt)
if mw_txt != mw_orig:
    MW.write_text(mw_txt, encoding='utf-8')
    print('MAIN_WINDOW OK')
else:
    print('MAIN_WINDOW SKIP - already patched or pattern not found')
bm_txt = BM.read_text(encoding='utf-8')
bm_orig = bm_txt
BRIDGE = '''
    def _start_bridge(self):
        import subprocess, os
        env = os.environ.copy()
        cmd = [r'D:\\jarvis_env\\Scripts\\python.exe', '-m', 'uvicorn', 'bridge.server:app', '--host', '127.0.0.1', '--port', '5000', '--log-level', 'warning']
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import atexit; atexit.register(proc.terminate)
            self.step_done.emit('Bridge started pid {}'.format(proc.pid))
        except Exception as e:
            self.step_done.emit('Bridge failed: {}'.format(e))
'''
if '_start_bridge' not in bm_txt:
    bm_txt = re.sub(r'(    def run\(self\):)', BRIDGE + r'\n\1', bm_txt, count=1)
    bm_txt = re.sub(r'(    def run\(self\):\s*\n\s*)', r'\1self._start_bridge()\n        ', bm_txt, count=1)
    BM.write_text(bm_txt, encoding='utf-8')
    print('BOOT_MANAGER OK')
else:
    print('BOOT_MANAGER SKIP - already patched')
print('Done. Run: D:\\jarvis_env\\Scripts\\python.exe main.py')
