import pathlib
f = pathlib.Path(r'C:\Users\aliin\OneDrive\Desktop\Jarvis\jarvis_lab\bridge\server.py')
txt = f.read_text(encoding='utf-8')
txt = txt.replace(
    'allow_origins=[\n        "http://localhost",\n        "http://127.0.0.1",\n        "http://localhost:5000",\n        "http://127.0.0.1:5000",\n    ]',
    'allow_origins=["*"]'
)
f.write_text(txt, encoding='utf-8')
print('done')
