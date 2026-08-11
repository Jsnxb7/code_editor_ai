"""Add a validated single-lane/multi-lane switch to the Lightning runtime notebook."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


CONFIG_MARKER = "BOB_RUNTIME_MODE_SWITCH_V1"

MODE_GUIDE = """## Runtime lane mode — choose before running the runtime

All core cells are compatible with both modes and are tagged **MODE: BOTH**.

- **SINGLE**: one model replica and one model lane. Use this for the one-lane production queue and lower GPU-memory use.
- **MULTI**: multiple independent model replicas and sticky pipeline lanes. The default maximum is three and requires enough GPU memory for every loaded replica.
- **MODE SWITCH**: run the configuration cell once, before Phase 0.5/0.6. To change modes after the model runtime or API has started, restart the kernel and run from the top. Do not rerun only the switch cell against a live server.
- **OPTIONAL** cells are safe in either mode but are not required for production startup.

There are no separate SINGLE-only or MULTI-only implementation cells: preload, generation, cleanup, health, request routing, and API startup all use the selected configuration. This prevents accidentally running the wrong implementation for the selected mode.
"""

MODE_CONFIG = '''# Phase 0.2A — MODE SWITCH [RUN ONCE BEFORE PHASE 0.5/0.6]
# MODE: BOTH — this is the only notebook setting you need to change.
# Set the fallback to "single" or "multi". A BOB_RUNTIME_MODE environment
# variable, when present, intentionally overrides the notebook fallback.
# BOB_RUNTIME_MODE_SWITCH_V1

BOB_NOTEBOOK_RUNTIME_MODE = "single"  # <-- TOGGLE: "single" or "multi"
BOB_NOTEBOOK_MULTI_LANE_COUNT = 3       # Used only when mode is "multi".

_requested_runtime_mode = os.environ.get(
    "BOB_RUNTIME_MODE", BOB_NOTEBOOK_RUNTIME_MODE
).strip().lower().replace("-lane", "").replace("_lane", "")
if _requested_runtime_mode not in {"single", "multi"}:
    raise ValueError('BOB_RUNTIME_MODE must be either "single" or "multi"')

_requested_multi_lane_count = int(os.environ.get(
    "BOB_MULTI_LANE_COUNT",
    str(BOB_NOTEBOOK_MULTI_LANE_COUNT),
))
if not 2 <= _requested_multi_lane_count <= 3:
    raise ValueError("BOB_MULTI_LANE_COUNT must be 2 or 3")

_requested_lane_count = 1 if _requested_runtime_mode == "single" else _requested_multi_lane_count
if globals().get("_BOB_RUNTIME_INITIALIZED"):
    _active_configuration = (
        globals().get("BOB_RUNTIME_MODE"),
        globals().get("BOB_MODEL_LANE_COUNT"),
    )
    if _active_configuration != (_requested_runtime_mode, _requested_lane_count):
        raise RuntimeError(
            "The model runtime is already initialized with a different lane mode. "
            "Restart the kernel, choose the new mode, and run from the top."
        )

BOB_RUNTIME_MODE = _requested_runtime_mode
BOB_MULTI_LANE_COUNT = _requested_multi_lane_count
BOB_MODEL_LANE_COUNT = _requested_lane_count


def bob_runtime_configuration() -> Dict[str, Any]:
    """Return the effective configuration used by every runtime function."""
    return {
        "runtime_mode": BOB_RUNTIME_MODE,
        "model_lane_count": BOB_MODEL_LANE_COUNT,
        "multi_lane_count": BOB_MULTI_LANE_COUNT,
        "preload_model_lanes": os.environ.get("BOB_PRELOAD_MODEL_LANES", "1") == "1",
    }


print("Selected Bob runtime configuration:", bob_runtime_configuration())
'''


def source(cell: dict) -> str:
    return "".join(cell.get("source", []))


def set_source(cell: dict, value: str) -> None:
    cell["source"] = value.splitlines(keepends=True)


def replace_once(value: str, old: str, new: str, label: str) -> str:
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label}, found {count}")
    return value.replace(old, new, 1)


def find_cell(cells: list[dict], *markers: str) -> int:
    matches = [index for index, cell in enumerate(cells) if all(marker in source(cell) for marker in markers)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one cell containing {markers!r}, found {matches}")
    return matches[0]


def add_tag(cell: dict, tag: str) -> None:
    tags = cell.setdefault("metadata", {}).setdefault("tags", [])
    if tag not in tags:
        tags.append(tag)


def add_mode_label(cell: dict, label: str) -> None:
    value = source(cell)
    if "# MODE:" in value[:400] or "# MODE SWITCH" in value[:400]:
        return
    lines = value.splitlines(keepends=True)
    insertion = 1 if lines and lines[0].lstrip().startswith("#") else 0
    lines.insert(insertion, f"# MODE: {label}\n")
    cell["source"] = lines


def label_code_cells(cells: list[dict]) -> None:
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        value = source(cell)
        tags = cell.setdefault("metadata", {}).setdefault("tags", [])
        tags[:] = [tag for tag in tags if tag not in {"bob-mode-both", "bob-mode-switch", "bob-mode-sensitive", "bob-optional"}]
        add_tag(cell, "bob-mode-both")
        if CONFIG_MARKER in value:
            add_tag(cell, "bob-mode-switch")
            continue
        lines = [line for line in value.splitlines(keepends=True) if not line.startswith("# MODE:")]
        cell["source"] = lines
        value = source(cell)
        header = "\n".join(value.splitlines()[:6]).lower()
        if "optional" in header or "test:" in header or "smoke test" in header:
            add_tag(cell, "bob-optional")
            add_mode_label(cell, "BOTH (OPTIONAL) — safe in single and multi mode")
        elif "phase 0.6" in header or "phase 14" in header or "phase 15 —" in header:
            add_tag(cell, "bob-mode-sensitive")
            add_mode_label(cell, "BOTH — uses the Phase 0.2A selection")
        else:
            add_mode_label(cell, "BOTH — safe in single and multi mode")


def update_notebook(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = notebook.get("cells", [])

    if (
        notebook.get("metadata", {}).get("bob_concurrency", {}).get("schema_version") == "2.0"
        and sum(CONFIG_MARKER in source(cell) for cell in cells) == 1
    ):
        config_index = find_cell(cells, CONFIG_MARKER)
        set_source(cells[config_index], MODE_CONFIG)
        if config_index > 0 and "## Runtime lane mode" in source(cells[config_index - 1]):
            set_source(cells[config_index - 1], MODE_GUIDE)
        label_code_cells(cells)
        for cell in cells:
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
        path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("Notebook lane-mode toggle is already current; labels and configuration refreshed.")
        return

    imports_index = find_cell(cells, "# Phase 0.2", "import threading", "import torch")
    existing_config = [index for index, cell in enumerate(cells) if CONFIG_MARKER in source(cell)]
    if existing_config:
        if len(existing_config) != 1:
            raise RuntimeError(f"Expected one mode configuration cell, found {existing_config}")
        config_index = existing_config[0]
        set_source(cells[config_index], MODE_CONFIG)
        if config_index == 0 or "## Runtime lane mode" not in source(cells[config_index - 1]):
            cells.insert(config_index, {"cell_type": "markdown", "metadata": {"tags": ["bob-mode-guide"]}, "source": MODE_GUIDE.splitlines(keepends=True)})
    else:
        insertion = imports_index + 1
        cells[insertion:insertion] = [
            {"cell_type": "markdown", "metadata": {"tags": ["bob-mode-guide"]}, "source": MODE_GUIDE.splitlines(keepends=True)},
            {"cell_type": "code", "execution_count": None, "metadata": {"tags": ["bob-mode-switch", "bob-mode-both"]}, "outputs": [], "source": MODE_CONFIG.splitlines(keepends=True)},
        ]

    intro_index = find_cell(cells, "# Bob IDE Model Runtime", "## Recommended run order")
    intro = source(cells[intro_index])
    intro = intro.replace("- one shared model for planner, coder, and reviewer", "- one shared model family for planner, coder, and reviewer\n- a toggleable single-lane or multi-lane runtime")
    intro = intro.replace("Run cells **Phase 0.1 through Phase 0.6**", "Run **Phase 0.1**, **Phase 0.2**, and the **Phase 0.2A MODE SWITCH**, then continue through **Phase 0.6**")
    set_source(cells[intro_index], intro)

    cleanup_index = find_cell(cells, "def unload_all_models", "clear_temporary_generation_memory")
    cleanup = source(cells[cleanup_index]).replace(
        '"""Explicitly unload all three model lanes after the whole session."""',
        '"""Unload every configured model lane in either runtime mode."""',
    )
    set_source(cells[cleanup_index], cleanup)

    model_index = find_cell(cells, "SHARED_MODEL_NAME", "def run_shared_generation", "_bob_model_lanes")
    model = source(cells[model_index])
    model = replace_once(
        model,
        "# Phase 0.6 — Three-lane LLM runtime for Lightning AI Studio\n# Each lane owns a separate 4-bit model/tokenizer. A request is bound to one\n# lane for its complete pipeline so planner/coder/reviewer state cannot mix.\n",
        "# Phase 0.6 — Mode-aware LLM runtime [RUN IN SINGLE OR MULTI MODE]\n# MODE: BOTH — reads Phase 0.2A. Restart the kernel before changing modes.\n# Each configured lane owns an independent 4-bit model/tokenizer; the request\n# pipeline and thread-local workspace context use the same functions in both modes.\n",
        "model runtime heading",
    )
    model = replace_once(
        model,
        'BOB_MODEL_LANE_COUNT = max(1, min(3, int(os.environ.get("BOB_MODEL_LANE_COUNT", "3"))))\n',
        'if "BOB_RUNTIME_MODE" not in globals() or "BOB_MODEL_LANE_COUNT" not in globals():\n    raise RuntimeError("Run the Phase 0.2A MODE SWITCH cell before the model runtime")\n_BOB_RUNTIME_INITIALIZED = True\n',
        "hard-coded model lane count",
    )
    model = model.replace(
        '"model_lane": lane,\n    }',
        '"model_lane": lane,\n        "runtime_mode": BOB_RUNTIME_MODE,\n    }',
        1,
    )
    model = replace_once(
        model,
        'print(f"✅ Lightning three-lane LLM runtime ready ({BOB_MODEL_LANE_COUNT} lanes).")',
        'print(f"✅ Lightning {BOB_RUNTIME_MODE}-lane runtime ready ({BOB_MODEL_LANE_COUNT} model lane(s)).")',
        "model ready message",
    )
    set_source(cells[model_index], model)

    contract_index = find_cell(cells, 'BOB_COLAB_CONTRACT_VERSION = "bob-colab-v4-llmops"', "def _lane_health")
    contract = source(cells[contract_index])
    contract = contract.replace("# BOB_THREE_MODEL_LANES_V1_BEGIN", "# BOB_CONFIGURABLE_MODEL_LANES_V1_BEGIN")
    contract = contract.replace("# BOB_THREE_MODEL_LANES_V1_END", "# BOB_CONFIGURABLE_MODEL_LANES_V1_END")
    contract = replace_once(
        contract,
        '        return {\n            "model_lane_count": BOB_MODEL_LANE_COUNT,\n',
        '        return {\n            "runtime_mode": BOB_RUNTIME_MODE,\n            "model_lane_count": BOB_MODEL_LANE_COUNT,\n            "configured_multi_lane_count": BOB_MULTI_LANE_COUNT,\n',
        "lane health mode metadata",
    )
    contract = contract.replace(
        '            "sticky_pipeline_routing": True,\n',
        '            "sticky_pipeline_routing": BOB_RUNTIME_MODE == "multi",\n            "single_lane_serialization": BOB_RUNTIME_MODE == "single",\n',
        1,
    )
    contract = contract.replace(
        'print(f"✅ Staged Bob Chat contract ready with {BOB_MODEL_LANE_COUNT} isolated model lanes")',
        'print(f"✅ Staged Bob Chat contract ready in {BOB_RUNTIME_MODE} mode with {BOB_MODEL_LANE_COUNT} lane(s)")',
    )
    set_source(cells[contract_index], contract)

    tunnel_index = find_cell(cells, "# Phase 15", "preload_shared_model_lanes", "start_colab_http_server")
    tunnel = source(cells[tunnel_index]).replace(
        'print(f"Preloading {BOB_MODEL_LANE_COUNT} model lanes sequentially...")',
        'print(f"Preloading {BOB_MODEL_LANE_COUNT} lane(s) for {BOB_RUNTIME_MODE} mode sequentially...")',
    )
    tunnel = tunnel.replace(
        'print("Runtime logs:    ", BOB_RUNTIME_LOG_DIR)',
        'print("Runtime mode:    ", BOB_RUNTIME_MODE)\nprint("Model lanes:     ", BOB_MODEL_LANE_COUNT)\nprint("Runtime logs:    ", BOB_RUNTIME_LOG_DIR)',
    )
    set_source(cells[tunnel_index], tunnel)

    final_cleanup_index = find_cell(cells, "# Phase 15.3", "shutdown_colab_http_server", "_unload_shared_model")
    final_cleanup = source(cells[final_cleanup_index]).replace("_unload_shared_model()", "_unload_shared_model(all_lanes=True)")
    set_source(cells[final_cleanup_index], final_cleanup)

    label_code_cells(cells)

    notebook.setdefault("metadata", {})["bob_concurrency"] = {
        "schema_version": "2.0",
        "runtime_mode_toggle": True,
        "default_runtime_mode": "single",
        "supported_runtime_modes": ["single", "multi"],
        "model_lane_counts": {"single": 1, "multi_min": 2, "multi_max": 3},
        "sticky_pipeline_routing_in_multi_mode": True,
        "thread_local_workspace_context": True,
        "atomic_helper_writes_required": True,
    }
    for cell in cells:
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("notebook", nargs="?", default="Untitled28_lightning_ai_bob_runtime (1).ipynb")
    args = parser.parse_args()
    path = Path(args.notebook).resolve()
    update_notebook(path)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
