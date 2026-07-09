import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const notebookPath = path.join(root, "Untitled28_colab_bob_ide_http_standalone_showcase.ipynb");
const notebook = JSON.parse(fs.readFileSync(notebookPath, "utf8"));
const marker = "BOB_COLAB_CONTRACT_VERSION = \"bob-colab-v2\"";
const exists = notebook.cells.some((cell) => (cell.source || []).join("").includes(marker));

if (!exists) {
  const source = `# Phase 13 - Bob IDE Colab v2 HTTP contract
# This overrides create_colab_app() with the endpoints negotiated by Bob Chat.

BOB_COLAB_CONTRACT_VERSION = "bob-colab-v2"
_bob_colab_runs: Dict[str, dict] = {}
_bob_colab_cancelled = set()


def _bob_run_event(run_id: str, status: str, **extra):
    record = {
        "run_id": run_id,
        "status": status,
        "updated_at": now_iso(),
        **extra,
    }
    _bob_colab_runs[run_id] = {**_bob_colab_runs.get(run_id, {}), **record}
    return record


def create_colab_app():
    from flask import Flask, Response, jsonify, request, stream_with_context
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)

    def authorized():
        ok, error = _check_bearer_token(request.headers)
        if not ok:
            return None, (jsonify({"error": error}), 401)
        return request.get_json(force=True, silent=True) or {}, None

    @app.get("/")
    @app.get("/health")
    def health():
        return jsonify({
            "ok": True,
            "service": "Bob Colab Model Runtime",
            "contract_version": BOB_COLAB_CONTRACT_VERSION,
            "model": SHARED_MODEL_NAME,
            "gpu_available": bool(torch.cuda.is_available()),
            "shared_model_loaded": _shared_model is not None,
            "streaming": True,
        })

    @app.get("/capabilities")
    def capabilities():
        return jsonify({
            "contract_version": BOB_COLAB_CONTRACT_VERSION,
            "model": SHARED_MODEL_NAME,
            "modes": ["chat", "plan", "agent"],
            "streaming": True,
            "cancellation": True,
            "max_iterations": {"minimum": 1, "maximum": 20, "default": 5},
            "context_modes": ["active", "open", "workspace"],
            "endpoints": {
                "health": "/health",
                "capabilities": "/capabilities",
                "chat": "/chat",
                "plan": "/plan",
                "run": "/run-agent",
                "stream": "/run-agent/stream",
                "status": "/runs/{run_id}",
                "cancel": "/runs/{run_id}/cancel",
            },
        })

    @app.post("/chat")
    def chat():
        payload, error = authorized()
        if error:
            return error
        set_bob_payload_context(payload)
        prompt = payload.get("user_prompt") or payload.get("message") or ""
        system = (
            "You are Bob, a concise coding assistant. Answer questions using the supplied "
            "workspace context. Do not claim to have changed files and do not emit proposals."
        )
        context = get_workspace_tree()
        active = read_file(BOB_ACTIVE_PATH) if BOB_ACTIVE_PATH else ""
        reply = run_shared_generation(
            system,
            f"Workspace:\\n{context}\\n\\nActive file:\\n{active[:12000]}\\n\\nUser:\\n{prompt}",
            max_new_tokens=1200,
        )
        return jsonify({"provider": "colab-qwen", "reply": reply, "run_id": payload.get("run_id")})

    @app.post("/plan")
    def http_plan():
        payload, error = authorized()
        if error:
            return error
        try:
            plan = plan_from_payload(payload)
            return jsonify({"run_id": payload.get("run_id"), "provider": "colab-qwen", "plan": plan})
        except Exception as exc:
            traceback.print_exc()
            return jsonify({"run_id": payload.get("run_id"), "error": str(exc)}), 500

    def execute_agent(payload):
        run_id = payload.get("run_id") or _make_run_id(payload)
        _bob_run_event(run_id, "running")
        if run_id in _bob_colab_cancelled:
            return _bob_run_event(run_id, "cancelled")
        try:
            result = run_agent_from_payload(payload, max_iterations=int(payload.get("max_iterations", 5)))
            if run_id in _bob_colab_cancelled:
                return _bob_run_event(run_id, "cancelled")
            _bob_run_event(run_id, "completed", result=result)
            return result
        except Exception as exc:
            traceback.print_exc()
            _bob_run_event(run_id, "failed", error=str(exc))
            raise

    @app.post("/run-agent")
    def http_run_agent():
        payload, error = authorized()
        if error:
            return error
        try:
            return jsonify(execute_agent(payload))
        except Exception as exc:
            return jsonify({
                "run_id": payload.get("run_id"),
                "provider": "colab-qwen",
                "final_status": "FAIL",
                "error": str(exc),
                "files": {},
            }), 500

    @app.post("/run-agent/stream")
    def http_run_agent_stream():
        payload, error = authorized()
        if error:
            return error
        run_id = payload.get("run_id") or _make_run_id(payload)
        payload["run_id"] = run_id

        @stream_with_context
        def generate():
            yield f"data: {json.dumps(_bob_run_event(run_id, 'queued'))}\\n\\n"
            yield f"data: {json.dumps(_bob_run_event(run_id, 'planning'))}\\n\\n"
            try:
                result = execute_agent(payload)
                status = "cancelled" if result.get("status") == "cancelled" else "completed"
                yield f"data: {json.dumps({'run_id': run_id, 'status': status, 'result': result})}\\n\\n"
            except Exception as exc:
                yield f"data: {json.dumps({'run_id': run_id, 'status': 'failed', 'error': str(exc)})}\\n\\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.get("/runs/<run_id>")
    def run_status(run_id):
        return jsonify(_bob_colab_runs.get(run_id, {"run_id": run_id, "status": "unknown"}))

    @app.post("/runs/<run_id>/cancel")
    def cancel_run(run_id):
        _bob_colab_cancelled.add(run_id)
        return jsonify(_bob_run_event(run_id, "cancelling"))

    return app


print("Bob Colab v2 contract ready:", BOB_COLAB_CONTRACT_VERSION)
print("Run start_colab_http_server() to expose it.")
`;
  notebook.cells.push({
    cell_type: "code",
    execution_count: null,
    metadata: {},
    outputs: [],
    source: source.split(/(?<=\n)/),
  });
  fs.writeFileSync(notebookPath, `${JSON.stringify(notebook, null, 1)}\n`, "utf8");
  console.log("Added Bob Colab v2 contract cell.");
} else {
  console.log("Bob Colab v2 contract cell already present.");
}
