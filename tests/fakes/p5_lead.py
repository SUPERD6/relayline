"""Fake lead additionally emits a genuine local check artifact, no model/CLI."""
from pathlib import Path
import runpy
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ccx.workspace import run_check
run_check(subprocess.list2cmdline([sys.executable, str(Path(__file__).with_name("check_emit.py"))]), Path.cwd())
runpy.run_path(str(Path(__file__).with_name("p4_lead.py")), run_name="__main__")
