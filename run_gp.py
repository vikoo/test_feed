#!/usr/bin/env python3
"""Standalone runner for gp_upload — avoids shell issues with python -m"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from cron.server_v2.ps_backend.upload.gp_upload import run_gp_upload
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    run_gp_upload(year=year)
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)

