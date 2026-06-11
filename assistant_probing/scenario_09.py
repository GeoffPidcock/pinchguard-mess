import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path.cwd().parent))
from assistant_probing.projection import run_probe, save_csv
from assistant_probing.axis_download import download_axis, load_axis

# --- configure paths here ---
AXIS_DIR = Path.cwd() / "data" / "axis"
RUNS_BASE = Path("../data/runs")
RUN_GLOB = "scenario_09*"
LAYERS = (32, 50)
PROJECTION_ROOT = Path.cwd() / "data" / "projections"
# ----------------------------

axis_path = download_axis("Qwen/Qwen3-32B", AXIS_DIR)
axis = load_axis(axis_path)
print(f"axis loaded, shape: {axis.shape}")

run_dirs = sorted(d for d in RUNS_BASE.glob(RUN_GLOB) if d.is_dir())
if not run_dirs:
    print(f"no runs matched {RUN_GLOB} in {RUNS_BASE}")

for run_dir in run_dirs:
    run_name = run_dir.name
    activations_dir = run_dir / "activations"
    projection_dir = PROJECTION_ROOT / run_name

    print(f"\n########## {run_name} ##########")
    print(activations_dir)

    npz_files = list(activations_dir.glob("*.npz"))
    if not npz_files:
        print(f"  no .npz activations found, skipping")
        continue

    # debug
    d = np.load(npz_files[0])
    print(d.files)

    for layer in LAYERS:
        scores = run_probe(activations_dir, axis_dir=AXIS_DIR, layer=layer)
        print(f"\n=== layer {layer} ===")
        for turn, (name, score) in enumerate(scores):
            print(f"turn {turn:>2}  label_probe = {score: 9.4f}   {name}")
        save_csv(scores, f"{run_name}_L{layer}", output_dir=projection_dir)