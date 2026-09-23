"""Run Shiye tools from the Agent source edition or maintenance repository."""
from pathlib import Path
import sys

if not (Path(__file__).parent/'app').is_dir():
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.agent_tools import main

if __name__=='__main__':raise SystemExit(main())
