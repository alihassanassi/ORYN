import pathlib

ROOT = pathlib.Path(r'C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab')

# Fix 1: boot_manager - add bridge autostart
BM = ROOT / 'runtime' / 'boot_manager.py'
txt = BM.read_text(encoding='utf-8')
if '_start_bridge' not in txt:
    method = '''
    def _start_bridge(self):
        import subprocess, os, atexit
        cmd = [r'D:/jarvis_env/Scripts/python.exe', '-m', 'uvicorn',
               'bridge.server:app', '--host', '127.0.0.1', '--port', '5000', '--log-level', 'warning']
        try:
            p = subprocess.Popen(cmd, cwd=str(pathlib.Path(__file__).parent.parent),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            atexit.register(p.terminate)
            self.step_done.emit('Bridge started')
        except Exception as exc:
            self.step_done.emit('Bridge failed: ' + str(exc))

'''
    txt = txt.replace('    def run(self):', method + '    def run(self):')
    txt = txt.replace('    def run(self):\n', '    def run(self):\n        self._start_bridge()\n', 1)
    BM.write_text(txt, encoding='utf-8')
    print('BOOT_MANAGER OK')
else:
    print('BOOT_MANAGER already patched')

# Fix 2: main_window - confirm setUrl is present
MW = ROOT / 'gui' / 'main_window.py'
txt = MW.read_text(encoding='utf-8')
if '127.0.0.1:5000/ops' in txt:
    print('MAIN_WINDOW already has setUrl - OK')
else:
    print('MAIN_WINDOW needs manual fix - setUrl not found')
    print('Search for setHtml in gui/main_window.py and replace with:')
    print('  _web_view.setUrl(_QUrl("http://127.0.0.1:5000/ops"))')
