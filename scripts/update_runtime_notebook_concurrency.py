"""Upgrade the Bob Lightning notebook to three isolated, sticky model lanes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MODEL_RUNTIME = r'''# Phase 0.6 — Three-lane LLM runtime for Lightning AI Studio
# Each lane owns a separate 4-bit model/tokenizer. A request is bound to one
# lane for its complete pipeline so planner/coder/reviewer state cannot mix.

SHARED_MODEL_NAME = "Qwen/Qwen2.5-Coder-7B-Instruct"
MODEL_ROOT = Path(os.environ.get("BOB_MODEL_DIR", "./models")).resolve()
MODEL_LOCAL_DIR = MODEL_ROOT / SHARED_MODEL_NAME.rsplit("/", 1)[-1]
BOB_MODEL_LANE_COUNT = max(1, min(3, int(os.environ.get("BOB_MODEL_LANE_COUNT", "3"))))

_downloaded_model_path = None
_bob_runtime_state = threading.local()
_bob_model_download_lock = threading.RLock()
_bob_model_load_locks = [threading.RLock() for _ in range(BOB_MODEL_LANE_COUNT)]
_bob_model_lanes = [None for _ in range(BOB_MODEL_LANE_COUNT)]
_bob_tokenizer_lanes = [None for _ in range(BOB_MODEL_LANE_COUNT)]
_bob_generation_state_lock = threading.RLock()
_bob_active_generation_count = 0


def _current_model_lane() -> int:
    lane = int(getattr(_bob_runtime_state, "model_lane", 0) or 0)
    if lane < 0 or lane >= BOB_MODEL_LANE_COUNT:
        raise RuntimeError(f"Invalid model lane {lane}; expected 0..{BOB_MODEL_LANE_COUNT - 1}")
    return lane


def download_shared_model(force_download: bool = False) -> str:
    """Download/resume the shared repository once and return its local path."""
    global _downloaded_model_path
    with _bob_model_download_lock:
        if _downloaded_model_path and not force_download:
            return _downloaded_model_path
        MODEL_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Model repository: {SHARED_MODEL_NAME}")
        print(f"Local model directory: {MODEL_LOCAL_DIR}")
        _downloaded_model_path = snapshot_download(
            repo_id=SHARED_MODEL_NAME,
            local_dir=str(MODEL_LOCAL_DIR),
            token=os.environ.get("HF_TOKEN") or None,
            force_download=force_download,
        )
        print("✅ Model download complete.")
        return _downloaded_model_path


def _load_shared_model(model_lane: Optional[int] = None):
    """Lazily load and return the independent model/tokenizer for one lane."""
    lane = _current_model_lane() if model_lane is None else int(model_lane)
    if lane < 0 or lane >= BOB_MODEL_LANE_COUNT:
        raise RuntimeError(f"Invalid model lane {lane}; expected 0..{BOB_MODEL_LANE_COUNT - 1}")
    with _bob_model_load_locks[lane]:
        if _bob_model_lanes[lane] is not None and _bob_tokenizer_lanes[lane] is not None:
            return _bob_model_lanes[lane], _bob_tokenizer_lanes[lane]
        if not torch.cuda.is_available():
            raise RuntimeError(
                "No CUDA GPU is available. In Lightning AI Studio, stop the Studio, "
                "select a GPU machine, restart it, and rerun the notebook."
            )
        model_path = _downloaded_model_path or download_shared_model()
        print(f"Loading model lane {lane} on {torch.cuda.get_device_name(0)}...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            local_files_only=True,
            use_fast=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            quantization_config=bnb_config,
            device_map="auto",
            dtype=torch.float16,
            low_cpu_mem_usage=True,
        )
        model.eval()
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        _bob_model_lanes[lane] = model
        _bob_tokenizer_lanes[lane] = tokenizer
        allocated = torch.cuda.memory_allocated() / (1024 ** 3)
        reserved = torch.cuda.memory_reserved() / (1024 ** 3)
        print(f"✅ Model lane {lane} loaded. GPU memory: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved.")
        return model, tokenizer


def preload_shared_model_lanes() -> None:
    """Load lanes sequentially to avoid concurrent downloads and memory spikes."""
    for lane in range(BOB_MODEL_LANE_COUNT):
        _load_shared_model(lane)


def _unload_shared_model(model_lane: Optional[int] = None, all_lanes: bool = False):
    """Unload the current lane, or every lane when explicitly requested."""
    lanes = range(BOB_MODEL_LANE_COUNT) if all_lanes else [_current_model_lane() if model_lane is None else int(model_lane)]
    for lane in lanes:
        with _bob_model_load_locks[lane]:
            model = _bob_model_lanes[lane]
            tokenizer = _bob_tokenizer_lanes[lane]
            if model is not None:
                print(f"Unloading model lane {lane}...")
                _bob_model_lanes[lane] = None
                _bob_tokenizer_lanes[lane] = None
                del model, tokenizer
    clear_temporary_generation_memory()


def run_shared_generation(
    system_prompt: str,
    user_prompt: str,
    max_new_tokens: int = 2000,
    temperature: float = 0.0,
    do_sample: bool = False,
    top_p: float = 0.95,
) -> str:
    """Generate on the model lane assigned to the current sticky pipeline."""
    lane = _current_model_lane()
    model, tokenizer = _load_shared_model(lane)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt")
    input_token_count = int(inputs["input_ids"].shape[-1])
    device = model.get_input_embeddings().weight.device
    inputs = {key: value.to(device) for key, value in inputs.items()}
    generation_kwargs = {
        **inputs,
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "pad_token_id": tokenizer.pad_token_id,
        "eos_token_id": tokenizer.eos_token_id,
        "repetition_penalty": 1.0,
        "use_cache": True,
    }
    if do_sample:
        generation_kwargs["temperature"] = temperature
        generation_kwargs["top_p"] = top_p
    global _bob_active_generation_count
    with _bob_generation_state_lock:
        _bob_active_generation_count += 1
    try:
        with torch.inference_mode():
            outputs = model.generate(**generation_kwargs)
    finally:
        with _bob_generation_state_lock:
            _bob_active_generation_count = max(0, _bob_active_generation_count - 1)
    generated_tokens = outputs[0][inputs["input_ids"].shape[1]:]
    output_token_count = int(generated_tokens.shape[-1])
    raw = tokenizer.decode(generated_tokens, skip_special_tokens=True)
    _bob_runtime_state.usage = {
        "input_tokens": input_token_count,
        "output_tokens": output_token_count,
        "total_tokens": input_token_count + output_token_count,
        "model_lane": lane,
    }
    del messages, text, inputs, outputs, generated_tokens, generation_kwargs
    clear_temporary_generation_memory()
    return raw


print(f"✅ Lightning three-lane LLM runtime ready ({BOB_MODEL_LANE_COUNT} lanes).")
'''


CLEANUP_FUNCTION = r'''_bob_gpu_cleanup_lock = globals().get("_bob_gpu_cleanup_lock", threading.RLock())


def clear_temporary_generation_memory():
    """Clear temporary GPU cache only when no other lane is generating."""
    if int(globals().get("_bob_active_generation_count", 0) or 0) > 0:
        return
    with _bob_gpu_cleanup_lock:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            allocated = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            print(f"Temporary memory cleared. Allocated: {allocated:.2f} GB | Reserved: {reserved:.2f} GB")
        else:
            print("CPU run - temporary memory cleared.")


'''


CONTEXT_DECLARATIONS = r'''_bob_request_context = globals().get("_bob_request_context", threading.local())


def _bob_context_payload() -> Dict[str, Any]:
    return getattr(_bob_request_context, "payload", {})


def _bob_context_files() -> Dict[str, Optional[str]]:
    return getattr(_bob_request_context, "files", {})


def _bob_context_tree() -> Any:
    return getattr(_bob_request_context, "tree", None)


def _bob_context_active_path() -> str:
    return getattr(_bob_request_context, "active_path", "")


def _bob_context_project() -> str:
    return getattr(_bob_request_context, "project", "sample_project")
'''


CONTEXT_SETTERS = r'''def set_bob_payload_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Set request-local workspace state so concurrent pipelines cannot mix context."""
    payload = payload or {}
    files = {
        _normalize_path(k): v
        for k, v in (payload.get("files") or {}).items()
        if _normalize_path(k) and not _normalize_path(k).startswith(".bob/")
    }
    tree = payload.get("workspace_tree") or {}
    active_path = _normalize_path(payload.get("active_path") or payload.get("activePath") or "")
    project = str(payload.get("project") or "sample_project")
    _bob_request_context.payload = payload
    _bob_request_context.files = files
    _bob_request_context.tree = tree
    _bob_request_context.active_path = active_path
    _bob_request_context.project = project
    return {
        "project": project,
        "active_path": active_path,
        "file_count": len(files),
        "tree_count": len(_flatten_workspace_tree(tree)),
    }


def clear_bob_payload_context():
    """Clear only the current request thread's context; model lanes stay loaded."""
    _bob_request_context.payload = {}
    _bob_request_context.files = {}
    _bob_request_context.tree = None
    _bob_request_context.active_path = ""
    _bob_request_context.project = "sample_project"
    clear_temporary_generation_memory()


'''


LANE_MANAGER = r'''_bob_request_lock = globals().get("_bob_request_lock", threading.RLock())  # legacy compatibility only

# BOB_THREE_MODEL_LANES_V1_BEGIN
from contextlib import contextmanager as _bob_contextmanager

_bob_pipeline_state_lock = globals().get("_bob_pipeline_state_lock", threading.RLock())
_bob_lane_locks = [threading.RLock() for _ in range(BOB_MODEL_LANE_COUNT)]
_bob_lane_owners = [None for _ in range(BOB_MODEL_LANE_COUNT)]
_bob_pipeline_assignments = {}
_bob_pipeline_stages = {}
_bob_pipeline_last_seen = {}
_BOB_PIPELINE_TTL_SECONDS = max(300, int(os.environ.get("BOB_PIPELINE_TTL_SECONDS", "3600")))


class BobPipelineLaneError(RuntimeError):
    pass


def _pipeline_id(payload: dict) -> str:
    value = payload.get("pipeline_id") or payload.get("run_id") or payload.get("trace_id")
    if not value:
        raise BobPipelineLaneError("pipeline_id or run_id is required for model execution")
    return str(value)


def _requested_lane(payload: dict):
    value = payload.get("model_lane")
    if value is None or value == "":
        return None
    try:
        lane = int(value)
    except (TypeError, ValueError) as exc:
        raise BobPipelineLaneError("model_lane must be an integer") from exc
    if lane < 0 or lane >= BOB_MODEL_LANE_COUNT:
        raise BobPipelineLaneError(f"model_lane must be between 0 and {BOB_MODEL_LANE_COUNT - 1}")
    return lane


def _prune_stale_pipelines(timestamp: float) -> None:
    stale = [pipeline_id for pipeline_id, seen in _bob_pipeline_last_seen.items() if timestamp - seen > _BOB_PIPELINE_TTL_SECONDS]
    for pipeline_id in stale:
        lane = _bob_pipeline_assignments.pop(pipeline_id, None)
        _bob_pipeline_stages.pop(pipeline_id, None)
        _bob_pipeline_last_seen.pop(pipeline_id, None)
        if lane is not None and _bob_lane_owners[lane] == pipeline_id:
            _bob_lane_owners[lane] = None


def _reserve_pipeline(payload: dict) -> tuple[str, int]:
    pipeline_id = _pipeline_id(payload)
    requested = _requested_lane(payload)
    timestamp = time.monotonic()
    with _bob_pipeline_state_lock:
        _prune_stale_pipelines(timestamp)
        assigned = _bob_pipeline_assignments.get(pipeline_id)
        if assigned is not None:
            if requested is not None and requested != assigned:
                raise BobPipelineLaneError(
                    f"Pipeline {pipeline_id} is already bound to lane {assigned}; lane switching is forbidden"
                )
            _bob_pipeline_last_seen[pipeline_id] = timestamp
            return pipeline_id, assigned
        candidate_lanes = [requested] if requested is not None else list(range(BOB_MODEL_LANE_COUNT))
        lane = next((item for item in candidate_lanes if _bob_lane_owners[item] is None), None)
        if lane is None:
            raise BobPipelineLaneError("All model lanes are busy; retry with the same pipeline_id")
        _bob_pipeline_assignments[pipeline_id] = lane
        _bob_lane_owners[lane] = pipeline_id
        _bob_pipeline_last_seen[pipeline_id] = timestamp
        return pipeline_id, lane


def _validate_pipeline_stage(pipeline_id: str, stage: str) -> None:
    previous = _bob_pipeline_stages.get(pipeline_id)
    allowed = {
        None: {"chat", "plan", "code", "run-agent"},
        "plan": {"plan", "replan", "code"},
        "replan": {"replan", "code"},
        "code": {"code", "review"},
        "chat": set(),
        "review": set(),
        "run-agent": set(),
    }
    if stage not in allowed.get(previous, set()):
        raise BobPipelineLaneError(f"Invalid pipeline stage transition {previous!r} -> {stage!r}")
    _bob_pipeline_stages[pipeline_id] = stage


def _release_pipeline(pipeline_id: str, lane: int) -> None:
    with _bob_pipeline_state_lock:
        if _bob_pipeline_assignments.get(pipeline_id) == lane:
            _bob_pipeline_assignments.pop(pipeline_id, None)
            _bob_pipeline_stages.pop(pipeline_id, None)
            _bob_pipeline_last_seen.pop(pipeline_id, None)
            if _bob_lane_owners[lane] == pipeline_id:
                _bob_lane_owners[lane] = None


@_bob_contextmanager
def _bob_pipeline_guard(payload: dict, stage: str, release: bool = False):
    pipeline_id, lane = _reserve_pipeline(payload)
    failed = False
    with _bob_lane_locks[lane]:
        with _bob_pipeline_state_lock:
            if _bob_lane_owners[lane] != pipeline_id:
                raise BobPipelineLaneError("Pipeline lane ownership changed unexpectedly")
            _validate_pipeline_stage(pipeline_id, stage)
            _bob_pipeline_last_seen[pipeline_id] = time.monotonic()
        previous_lane = getattr(_bob_runtime_state, "model_lane", None)
        previous_pipeline = getattr(_bob_runtime_state, "pipeline_id", None)
        _bob_runtime_state.model_lane = lane
        _bob_runtime_state.pipeline_id = pipeline_id
        payload["pipeline_id"] = pipeline_id
        payload["model_lane"] = lane
        try:
            yield lane
        except Exception:
            failed = True
            raise
        finally:
            clear_bob_payload_context()
            if previous_lane is None:
                if hasattr(_bob_runtime_state, "model_lane"):
                    delattr(_bob_runtime_state, "model_lane")
            else:
                _bob_runtime_state.model_lane = previous_lane
            if previous_pipeline is None:
                if hasattr(_bob_runtime_state, "pipeline_id"):
                    delattr(_bob_runtime_state, "pipeline_id")
            else:
                _bob_runtime_state.pipeline_id = previous_pipeline
            if release or failed:
                _release_pipeline(pipeline_id, lane)


def _lane_health() -> dict:
    with _bob_pipeline_state_lock:
        return {
            "model_lane_count": BOB_MODEL_LANE_COUNT,
            "loaded_model_lanes": [index for index, model in enumerate(_bob_model_lanes) if model is not None],
            "active_pipeline_count": len(_bob_pipeline_assignments),
            "sticky_pipeline_routing": True,
            "pipeline_stage_validation": True,
            "request_context_isolation": "thread_local",
        }
# BOB_THREE_MODEL_LANES_V1_END
'''


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label}, found {count}")
    return source.replace(old, new, 1)


def update_notebook(path: Path) -> None:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = notebook.get("cells", [])

    def find(*markers: str) -> int:
        matches = []
        for index, cell in enumerate(cells):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source", []))
            if all(marker in source for marker in markers):
                matches.append(index)
        if len(matches) != 1:
            raise RuntimeError(f"Expected one cell containing {markers!r}, found {matches}")
        return matches[0]

    model_index = find("SHARED_MODEL_NAME", "def run_shared_generation", "_load_shared_model")
    cleanup_index = find("GPU/RAM cleanup utilities", "def clear_temporary_generation_memory", "def clear_gpu_memory")
    context_index = find("Bob IDE payload-backed workspace helpers", "def set_bob_payload_context", "def list_files")
    contract_index = find('BOB_COLAB_CONTRACT_VERSION = "bob-colab-v4-llmops"', "def create_colab_app", '@app.post("/replan")')
    tunnel_index = find("Start and expose the Bob API", "start_colab_http_server", "ngrok.connect")

    cells[model_index]["source"] = MODEL_RUNTIME.splitlines(keepends=True)

    cleanup = "".join(cells[cleanup_index].get("source", []))
    cleanup_start = cleanup.index("def clear_temporary_generation_memory()")
    cleanup_end = cleanup.index("def clear_gpu_memory()", cleanup_start)
    cleanup = cleanup[:cleanup_start] + CLEANUP_FUNCTION + cleanup[cleanup_end:]
    unload_start = cleanup.index("def unload_all_models()")
    unload_end = cleanup.index('print("✅ Cleanup helpers ready.")', unload_start)
    cleanup = cleanup[:unload_start] + '''def unload_all_models():
    """Explicitly unload all three model lanes after the whole session."""
    unload = globals().get("_unload_shared_model")
    if callable(unload):
        unload(all_lanes=True)
    clear_temporary_generation_memory()


''' + cleanup[unload_end:]
    cells[cleanup_index]["source"] = cleanup.splitlines(keepends=True)

    context = "".join(cells[context_index].get("source", []))
    declaration_start = context.index("BOB_PAYLOAD: Dict[str, Any] = {}")
    declaration_end = context.index('if "WORKSPACE_DIR" not in globals()', declaration_start)
    context = context[:declaration_start] + CONTEXT_DECLARATIONS + "\n\n" + context[declaration_end:]
    setter_start = context.index("def set_bob_payload_context(")
    setter_end = context.index("def list_files()", setter_start)
    context = context[:setter_start] + CONTEXT_SETTERS + context[setter_end:]
    cells[context_index]["source"] = context.splitlines(keepends=True)

    replacements = {
        "BOB_CONTEXT_FILES": "_bob_context_files()",
        "BOB_WORKSPACE_TREE": "_bob_context_tree()",
        "BOB_ACTIVE_PATH": "_bob_context_active_path()",
        "BOB_PROJECT": "_bob_context_project()",
    }
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        for old, new in replacements.items():
            source = source.replace(old, new)
        cell["source"] = source.splitlines(keepends=True)

    runtime = "".join(cells[contract_index].get("source", []))
    runtime = replace_once(
        runtime,
        '_bob_request_lock = globals().get("_bob_request_lock", threading.RLock())\n',
        LANE_MANAGER,
        "legacy request lock",
    )
    runtime = replace_once(
        runtime,
        '        "approach": payload.get("approach"),\n        "model": SHARED_MODEL_NAME,\n',
        '        "approach": payload.get("approach"),\n        "pipeline_id": payload.get("pipeline_id") or payload.get("run_id"),\n        "model_lane": payload.get("model_lane", getattr(_bob_runtime_state, "model_lane", None)),\n        "model": SHARED_MODEL_NAME,\n',
        "model request lane metadata",
    )
    runtime = replace_once(
        runtime,
        '        g.bob_evaluation_metadata = {name: payload.get(name) for name in ("evaluation_run_id", "test_id", "test_name", "prompt_category", "pair_id", "approach")}\n',
        '        g.bob_evaluation_metadata = {name: payload.get(name) for name in ("evaluation_run_id", "test_id", "test_name", "prompt_category", "pair_id", "approach", "pipeline_id", "model_lane")}\n',
        "HTTP lane metadata",
    )
    runtime = runtime.replace('"shared_model_loaded": _shared_model is not None,', '"shared_model_loaded": any(model is not None for model in _bob_model_lanes),')
    runtime = runtime.replace('            "runtime_log_dir": str(BOB_RUNTIME_LOG_DIR),\n            "endpoints":', '            "runtime_log_dir": str(BOB_RUNTIME_LOG_DIR),\n            "concurrency": _lane_health(),\n            "endpoints":', 2)
    runtime = replace_once(runtime, "        with _bob_request_lock:\n            _set_staged_payload_context(payload)\n", '        with _bob_pipeline_guard(payload, "chat", release=True):\n            _set_staged_payload_context(payload)\n', "chat lane guard")
    runtime = replace_once(runtime, "            with _bob_request_lock:\n                plan = plan_from_payload(payload)\n", '            with _bob_pipeline_guard(payload, "plan", release=bool(payload.get("release_pipeline"))):\n                plan = plan_from_payload(payload)\n', "plan lane guard")
    runtime = replace_once(runtime, "            with _bob_request_lock:\n                plan = replan_from_payload(payload)\n", '            with _bob_pipeline_guard(payload, "replan", release=bool(payload.get("release_pipeline"))):\n                plan = replan_from_payload(payload)\n', "replan lane guard")
    runtime = replace_once(runtime, "            with _bob_request_lock:\n                return jsonify(code_from_payload(payload))\n", '            with _bob_pipeline_guard(payload, "code", release=bool(payload.get("release_pipeline"))):\n                return jsonify(code_from_payload(payload))\n', "code lane guard")
    runtime = replace_once(runtime, "            with _bob_request_lock:\n                return jsonify(review_from_payload(payload))\n", '            with _bob_pipeline_guard(payload, "review", release=True):\n                return jsonify(review_from_payload(payload))\n', "review lane guard")
    runtime = replace_once(runtime, "            with _bob_request_lock:\n                return jsonify(run_agent_from_payload(payload, max_iterations=int(payload.get(\"max_iterations\", 5))))\n", '            with _bob_pipeline_guard(payload, "run-agent", release=True):\n                return jsonify(run_agent_from_payload(payload, max_iterations=int(payload.get("max_iterations", 5))))\n', "agent lane guard")
    runtime = replace_once(runtime, "            with _bob_request_lock:\n                result = run_agent_from_payload(payload, max_iterations=int(payload.get(\"max_iterations\", 5)))\n", '            with _bob_pipeline_guard(payload, "run-agent", release=True):\n                result = run_agent_from_payload(payload, max_iterations=int(payload.get("max_iterations", 5)))\n', "stream lane guard")
    runtime = runtime.replace('print("✅ Staged Bob Chat Colab contract ready: /plan /replan /code /review /run-agent")', 'print(f"✅ Staged Bob Chat contract ready with {BOB_MODEL_LANE_COUNT} isolated model lanes")')
    cells[contract_index]["source"] = runtime.splitlines(keepends=True)

    tunnel = "".join(cells[tunnel_index].get("source", []))
    if "BOB_PRELOAD_MODEL_LANES" not in tunnel:
        tunnel = replace_once(
            tunnel,
            "# 3. Start or reuse the local Bob Flask server\n# ---------------------------------------------------------------------------\n\nserver_info = start_colab_http_server(\n",
            "# 3. Start or reuse the local Bob Flask server\n# ---------------------------------------------------------------------------\n\nif os.environ.get(\"BOB_PRELOAD_MODEL_LANES\", \"1\") == \"1\":\n    print(f\"Preloading {BOB_MODEL_LANE_COUNT} model lanes sequentially...\")\n    preload_shared_model_lanes()\n\nserver_info = start_colab_http_server(\n",
            "sequential lane preload hook",
        )
    cells[tunnel_index]["source"] = tunnel.splitlines(keepends=True)

    notebook.setdefault("metadata", {}).setdefault("bob_concurrency", {}).update({
        "schema_version": "1.0",
        "model_lane_count": 3,
        "sticky_pipeline_routing": True,
        "thread_local_workspace_context": True,
        "atomic_helper_writes_required": True,
    })
    for cell in cells:
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("notebook", nargs="?", default="Untitled28_lightning_ai_bob_runtime (1).ipynb")
    args = parser.parse_args()
    update_notebook(Path(args.notebook).resolve())
    print(Path(args.notebook).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
