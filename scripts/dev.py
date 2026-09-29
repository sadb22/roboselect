"""Start web and simulation worker, terminate both cleanly on Ctrl-C."""
import os
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
os.chdir(root)
for command in [('migrate','--noinput'),('seed_data',),('initialize_workflow',)]:
    subprocess.run([sys.executable,'manage.py',*command],check=True)
children=[]
try:
    for command in [('simulation_worker',),('runserver','127.0.0.1:8765','--noreload')]:
        children.append(subprocess.Popen([sys.executable,'manage.py',*command]))
    children[-1].wait()
except KeyboardInterrupt:
    pass
finally:
    for child in children:child.terminate()
    for child in children:
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill()
