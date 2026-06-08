"""Linear probe: project captured activations onto the Assistant Axis, per turn.

Step 1 of the drift experiment ("does drift occur at all?"): load the 15
captured `L<layer>` activations for a scenario_02 run in turn order, project
each onto the Assistant Axis, and print `label_probe` per turn so a drop
around the contamination window is visible by eye.

    axis[layer] = mean(default_activations) - mean(role_activations)

Higher projection = more Assistant-like; lower = drifted toward a
role/persona. See axis.py / AGENTS.md §3 (`label_probe`) for background.

Usage:
    uv run python -m assistant_probing.linear_probe <activations_dir>
    uv run python -m assistant_probing.linear_probe \
        /datapool/analysis_data/tara/pinchguard/runs/scenario_02/activations
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

from .axis import download_axis, load_axis

LAYER = 32  # Qwen3-32B target layer; module-output of model.model.layers[32].


def project(activation: np.ndarray | torch.Tensor, axis: torch.Tensor, layer: int, *, normalize: bool = True) -> float:
    """Dot product of one activation vector with the (unit-)axis direction at `layer`."""
    act = torch.as_tensor(np.asarray(activation)).float().reshape(-1)
    ax = axis[layer].float()
    if normalize:
        ax = ax / (ax.norm() + 1e-8)
    return float(act @ ax)


def project_npz(npz_path: str | Path, axis: torch.Tensor, layer: int, *, normalize: bool = True) -> float:
    """Project the `L<layer>` activation stored in a Pinchguard activation `.npz`."""
    key = f"L{layer}"
    with np.load(Path(npz_path)) as data:
        if key not in data:
            raise KeyError(f"{npz_path}: no {key!r} array (keys={sorted(data.files)})")
        return project(data[key], axis, layer, normalize=normalize)


def run_probe(
    activations_dir: str | Path,
    *,
    model_id: str = "Qwen/Qwen3-32B",
    layer: int = LAYER,
) -> list[tuple[str, float]]:
    """Project every `.npz` in `activations_dir` onto the axis, in filename order.

    Filename order = turn order for scenario_02 captures (see README.md).
    Returns a list of (filename, label_probe) pairs, index == turn.
    """
    axis = load_axis(download_axis(model_id))
    npz_paths = sorted(Path(activations_dir).glob("*.npz"))
    return [(p.name, project_npz(p, axis, layer)) for p in npz_paths]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("activations_dir", type=Path, help="Directory of <step_id>.npz captures, named in turn order")
    parser.add_argument("--model", default="Qwen/Qwen3-32B", help="Model id whose axis to project onto")
    parser.add_argument("--layer", type=int, default=LAYER, help="Layer index to project at")
    args = parser.parse_args(argv)

    scores = run_probe(args.activations_dir, model_id=args.model, layer=args.layer)
    if not scores:
        print(f"no .npz files found in {args.activations_dir}", file=sys.stderr)
        return 1

    for turn, (name, score) in enumerate(scores):
        print(f"turn {turn:>2}  label_probe = {score: 9.4f}   {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
