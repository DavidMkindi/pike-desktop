import re

app = open('static/css/style.css', encoding='utf-8').read()
ext = open('pike-vscode/media/pike.css', encoding='utf-8').read()


def root_vars(css):
    # grab the first :root { ... } block
    m = re.search(r':root\s*\{(.*?)\}', css, re.S)
    body = m.group(1)
    out = {}
    for line in body.splitlines():
        line = line.strip()
        m2 = re.match(r'--([a-zA-Z0-9-]+)\s*:\s*(.+?);\s*$', line)
        if m2:
            out[m2.group(1)] = m2.group(2).strip()
    return out


a = root_vars(app)
e = root_vars(ext)
print('app vars:', len(a), ' ext vars:', len(e))
print()
print(f'{"token":24} {"app":34} {"extension":34} match')
for k in sorted(a):
    av = a[k]
    ev = e.get(k, '<missing>')
    ok = 'OK' if av == ev else 'DIFF'
    print(f'{k:24} {av:34} {ev:34} {ok}')
print()
only_ext = sorted(set(e) - set(a))
print('extension-only vars:', only_ext)
missing = sorted(k for k in a if k not in e)
print('missing from extension:', missing)