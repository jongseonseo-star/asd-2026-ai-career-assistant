# Shared local AI services

These services are intentionally non-containerized. Install dependencies once with `python -m pip install -r ai-services/requirements.txt` (the MCP implementation uses the standalone `fastmcp` package), then run each service from the repository root in separate terminals:

```text
python ai-services/mcp_server.py --transport streamable-http
python ai-services/rag_server.py
```

Enable them for a local feature backend with `AI_SERVICES_ENABLED=true`. Student-3 uses `MCP_BASE_URL=http://127.0.0.1:8765` and `RAG_BASE_URL=http://127.0.0.1:8766` by default. The feature Docker Compose files do not include these services.

Validate the shared modes with `python ai-services/agentic_loop.py --mode mcp`, `--mode rag`, or `--mode all`. MCP validation uses the real MCP protocol to discover and call the registered tool. Add `--evidence-file docs/release-1/student-3/evidence/ai-validation.json` to capture JSON evidence.

The RAG pipeline explicitly reports `refresh`, `retrieve`, `answer`, `validate`, `review`, and `improve` phases. It includes retrieved text, `shared://` source identifiers, and a `low`, `medium`, or `high` confidence category.
