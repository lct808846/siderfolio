"""Run plotting integration with an isolated, disposable PostgreSQL control DB."""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import psycopg
from psycopg import sql

password = next(
    line.split('=', 1)[1].strip().strip('"\'')
    for line in Path('.astroagent/postgres/admin.env').read_text().splitlines()
    if line.startswith('POSTGRES_ADMIN_PASSWORD=')
)
base = 'postgresql://postgres:' + quote(password, safe='') + '@127.0.0.1:5432/'
name = 'astroagent_test_control_' + uuid4().hex
created = False
try:
    with psycopg.connect(base + 'postgres', autocommit=True, connect_timeout=5) as db:
        db.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
    created = True
    env = os.environ.copy()
    env.update(ASTROAGENT_RUN_POSTGRES_TESTS='1', ASTROAGENT_TEST_DATABASE_URL=base + name,
               PYTHONPATH=str(Path('src').resolve()))
    result = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_plot_postgres.py', '-q',
                             '--junitxml=docs/test-records/v1.3.0/acceptance/20261109T003436Z/plot-postgres.xml'],
                            env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    output = (result.stdout + result.stderr).replace(password, '[REDACTED]').replace(quote(password, safe=''), '[REDACTED]')
    Path('docs/test-records/v1.3.0/acceptance/20261109T003436Z/plot-postgres.log').write_text(output, encoding='utf-8')
    print(output[-4000:])
    exit_code = result.returncode
finally:
    if created:
        with psycopg.connect(base + 'postgres', autocommit=True, connect_timeout=5) as db:
            db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        print('Temporary control database dropped')
raise SystemExit(exit_code)
