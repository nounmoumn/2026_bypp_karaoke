"""Run once on the Pod to expose the app through Runpod's existing 8888 proxy."""
from pathlib import Path
import subprocess

nginx = Path('/etc/nginx/nginx.conf')
start = Path('/start.sh')
prestart = Path('/pre_start.sh')

server = '''
    # SJ karaoke public web app
    server {
        listen 8888;
        client_max_body_size 300M;
        location / {
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            include snippets/nginx-proxy.conf;
            proxy_pass http://localhost:8000;
        }
    }
'''
content = nginx.read_text()
if '# SJ karaoke public web app' not in content:
    nginx.with_suffix('.conf.bypp-backup').write_text(content)
    pos = content.rfind('\n}')
    nginx.write_text(content[:pos] + server + content[pos:])

content = start.read_text()
if '\nstart_jupyter\n' in content:
    start.with_suffix('.sh.bypp-backup').write_text(content)
    start.write_text(content.replace('\nstart_jupyter\n', '\n# start_jupyter  # port 8888 serves SJ\n'))

prestart.write_text('''#!/bin/bash
bash /workspace/bypp/deploy/start_web.sh
''')
prestart.chmod(0o755)
subprocess.run(['pkill', '-f', '^/usr/local/bin/python /usr/local/bin/jupyter-lab'], check=False)
subprocess.run(['nginx', '-t'], check=True)
subprocess.run(['nginx', '-s', 'reload'], check=True)
subprocess.run(['bash', '/workspace/bypp/deploy/start_web.sh'], check=True)
