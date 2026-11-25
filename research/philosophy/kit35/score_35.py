"""Run 35 vs run 34 with score_run30.report/compare (PREREG_kit35 no-harm, descriptive)."""
import runpy, sys
sys.argv = ["score_run30.py"]
G = runpy.run_path(__file__.replace("score_35.py", "score_run30.py"), run_name="lib")
G["report"]("34"); G["report"]("35"); G["compare"]("34", "35", "run 34 vs 35 (PREREG_kit35 no-harm)")
