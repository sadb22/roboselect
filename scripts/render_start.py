"""Run web and simulation worker in one free instance, with fail-fast supervision."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main():
    os.chdir(Path(__file__).resolve().parent.parent)
    if not os.environ.get('DATABASE_URL'):
        raise SystemExit('DATABASE_URL is required: local storage is ephemeral on Render')
    port = int(os.environ.get('PORT', '10000'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT must be between 1 and 65535')
    for command in [('migrate', '--noinput'), ('seed_data',), ('initialize_workflow',)]:
        subprocess.run([sys.executable, 'manage.py', *command], check=True)
    children = []
    stopping = False
    next_deadline_check = time.monotonic()

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([sys.executable, 'manage.py', 'simulation_worker']))
        children.append(subprocess.Popen([
            sys.executable, '-m', 'gunicorn', 'config.wsgi:application',
            '--bind', f'0.0.0.0:{port}', '--workers', '1', '--threads', '4',
            '--timeout', '75', '--access-logfile', '-', '--error-logfile', '-',
        ]))
        while not stopping:
            if time.monotonic() >= next_deadline_check:
                try:
                    subprocess.run([sys.executable,'manage.py','check_supplier_deadlines'],check=True,timeout=30)
                except (subprocess.SubprocessError,OSError):
                    print('Supplier deadline check failed; will retry.',flush=True)
                next_deadline_check=time.monotonic()+900
            if any(child.poll() is not None for child in children):
                print('A service exited; restarting the instance is required.', flush=True)
                return 1
            time.sleep(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
