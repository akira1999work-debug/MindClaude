#!/usr/bin/env python3
"""MindClaude Web App - Browser-based mind map viewer/editor."""

import argparse
import json
import os
import sys
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Import from existing MCP server
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import read_emmx, find_emmx_files, extract_structured_nodes

MAPS_DIR = Path.home() / ".mindclaude" / "maps"
INDEX_HTML = Path(__file__).parent / "index.html"


def emmx_to_mindmap(filepath: str) -> dict:
    """Convert .emmx file to MindClaude JSON format with hierarchy recovery.

    EdrawMind's page.bin stores nodes in document order. The first node is the
    root, and subsequent nodes are branches/leaves. Since the binary format
    doesn't encode parent-child relationships explicitly, we use heuristics:
    - Field 122-123 = root label
    - Field 126-131 = branch/leaf labels (depth not encoded)

    Strategy: treat the first node as root, and group subsequent nodes into
    branches. When a node's label looks like a main topic (short, no notes),
    start a new branch. Nodes with notes or longer labels become children
    of the current branch.
    """
    result = read_emmx(filepath)
    if "error" in result:
        return {"error": result["error"]}

    nodes = {}
    all_items = []  # (nid, label, note_text)

    for page in result.get("pages", []):
        structured = page.get("structured_nodes", [])
        if not structured:
            # Fallback: use flat node list
            for text in page.get("nodes", []):
                nid = str(uuid.uuid4())[:8]
                note_text = ""
                nodes[nid] = {
                    "id": nid, "label": text, "note": note_text,
                    "children": [], "collapsed": False,
                }
                all_items.append((nid, text, note_text))
            continue

        for sn in structured:
            nid = str(uuid.uuid4())[:8]
            note_text = "\n".join(sn.get("notes", []))
            links = sn.get("links", [])
            if links:
                note_text += ("\n\n" if note_text else "") + "\n".join(links)
            nodes[nid] = {
                "id": nid, "label": sn["label"], "note": note_text,
                "children": [], "collapsed": False,
            }
            all_items.append((nid, sn["label"], note_text))

    if not all_items:
        root_id = str(uuid.uuid4())[:8]
        nodes[root_id] = {
            "id": root_id, "label": Path(filepath).stem, "note": "",
            "children": [], "collapsed": False,
        }
        return {"version": 1, "title": Path(filepath).stem, "nodes": nodes, "rootId": root_id}

    # First node = root
    root_id = all_items[0][0]

    if len(all_items) <= 1:
        return {"version": 1, "title": Path(filepath).stem, "nodes": nodes, "rootId": root_id}

    # Heuristic hierarchy: short labels without notes = branch topics,
    # longer labels or labels with notes = children of current branch
    remaining = all_items[1:]

    # Calculate average label length to detect "branch-level" vs "leaf-level"
    avg_len = sum(len(item[1]) for item in remaining) / len(remaining) if remaining else 10

    current_branch_id = None
    for nid, label, note_text in remaining:
        is_branch = (
            len(label) <= max(avg_len * 0.7, 15)
            and not note_text
            and current_branch_id is not None  # first non-root always becomes branch
        ) or current_branch_id is None

        if is_branch or current_branch_id is None:
            # This is a main branch
            nodes[root_id]["children"].append(nid)
            current_branch_id = nid
        else:
            # This is a child of the current branch
            nodes[current_branch_id]["children"].append(nid)

    return {
        "version": 1,
        "title": Path(filepath).stem,
        "nodes": nodes,
        "rootId": root_id,
    }


class MindMapHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path):
        try:
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/":
            self._send_html(INDEX_HTML)

        elif path == "/api/emmx/list":
            files = find_emmx_files()
            self._send_json(files)

        elif path == "/api/emmx/read":
            filepath = params.get("path", [None])[0]
            if not filepath:
                self._send_json({"error": "path parameter required"}, 400)
                return
            result = emmx_to_mindmap(filepath)
            self._send_json(result)

        elif path == "/api/maps":
            maps = []
            if MAPS_DIR.exists():
                for f in sorted(MAPS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                    try:
                        data = json.loads(f.read_text("utf-8"))
                        maps.append({"id": f.stem, "title": data.get("title", f.stem)})
                    except Exception:
                        pass
            self._send_json(maps)

        elif path.startswith("/api/maps/"):
            map_id = path.split("/")[-1]
            map_file = MAPS_DIR / f"{map_id}.json"
            if map_file.exists():
                data = json.loads(map_file.read_text("utf-8"))
                self._send_json(data)
            else:
                self._send_json({"error": "not found"}, 404)

        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/maps":
            body = json.loads(self._read_body())
            MAPS_DIR.mkdir(parents=True, exist_ok=True)
            map_id = body.get("id") or str(uuid.uuid4())[:8]
            body["id"] = map_id
            (MAPS_DIR / f"{map_id}.json").write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._send_json({"id": map_id, "status": "saved"})

        elif path.startswith("/api/maps/"):
            map_id = path.split("/")[-1]
            body = json.loads(self._read_body())
            MAPS_DIR.mkdir(parents=True, exist_ok=True)
            body["id"] = map_id
            (MAPS_DIR / f"{map_id}.json").write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._send_json({"id": map_id, "status": "saved"})

        else:
            self.send_error(404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/maps/"):
            map_id = path.split("/")[-1]
            map_file = MAPS_DIR / f"{map_id}.json"
            if map_file.exists():
                map_file.unlink()
                self._send_json({"status": "deleted"})
            else:
                self._send_json({"error": "not found"}, 404)
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="MindClaude Web App")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    server = HTTPServer(("localhost", args.port), MindMapHandler)
    print(f"MindClaude running at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
