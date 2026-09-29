"""Current passwordless demo checks, including explicit role selection."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name("check_roles_template_browser.py")), run_name="__main__")
