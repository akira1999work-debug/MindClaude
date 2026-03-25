#!/usr/bin/env python3
"""EdrawMind MCP Server - Read and write mind maps via Claude Code.

A Model Context Protocol (MCP) server that integrates EdrawMind with Claude Code.
Claude can read existing mind maps, search across them, create new ones,
and add content to existing ones — all through natural conversation.

Works on macOS, Windows, and Linux. No external dependencies required.
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# --- Platform detection ---

SYSTEM = platform.system()
HOME = Path.home()


def _get_edrawmind_paths() -> dict:
    """Return platform-specific EdrawMind data paths."""
    if SYSTEM == "Darwin":
        base = HOME / "Library" / "Edraw" / "EdrawMind"
    elif SYSTEM == "Windows":
        appdata = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
        base = appdata / "Edraw" / "EdrawMind"
    else:  # Linux
        base = HOME / ".config" / "Edraw" / "EdrawMind"
        if not base.exists():
            base = HOME / ".local" / "share" / "Edraw" / "EdrawMind"

    return {
        "base": base,
        "tempfile": base / "tempFile",
        "autosave": base / "autosave",
        "recent_xml": base / "RecentFiles.xml",
    }


def _open_in_edrawmind(filepath: str) -> bool:
    """Open a file in EdrawMind using the platform-appropriate method."""
    try:
        if SYSTEM == "Darwin":
            subprocess.Popen(["open", "-a", "EdrawMind", filepath])
        elif SYSTEM == "Windows":
            os.startfile(filepath)
        else:  # Linux
            subprocess.Popen(["xdg-open", filepath])
        return True
    except Exception:
        return False


PATHS = _get_edrawmind_paths()

# --- Common search directories for .emmx files ---

SEARCH_DIRS = [
    HOME,
    HOME / "Documents",
    HOME / "Desktop",
    HOME / "Downloads",
]


# --- MCP protocol helpers ---

def send_response(req_id, result):
    msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
    sys.stdout.write(f"Content-Length: {len(msg.encode())}\r\n\r\n{msg}")
    sys.stdout.flush()


def send_error(req_id, code, message):
    msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})
    sys.stdout.write(f"Content-Length: {len(msg.encode())}\r\n\r\n{msg}")
    sys.stdout.flush()


# --- .emmx parser ---

def extract_text_from_page_bin(data: bytes) -> list[str]:
    """Extract text nodes from EdrawMind page.bin binary format.

    The page.bin file uses a custom binary format. Text content is stored as
    UTF-8 strings, which we extract by scanning for valid UTF-8 sequences
    that contain meaningful characters (CJK, Latin, etc.).
    """
    texts = []
    i = 0
    while i < len(data):
        if data[i] >= 0x80 or (0x20 <= data[i] < 0x7F):
            for end in range(min(i + 1000, len(data)), i + 1, -1):
                try:
                    s = data[i:end].decode("utf-8")
                    clean = "".join(c for c in s if ord(c) >= 32)
                    has_cjk = any(
                        0x3000 <= ord(c) <= 0x9FFF
                        or 0xF900 <= ord(c) <= 0xFAFF
                        or 0xFF00 <= ord(c) <= 0xFFEF
                        or 0xAC00 <= ord(c) <= 0xD7AF  # Korean
                        for c in clean
                    )
                    has_meaningful_ascii = len(clean) >= 5 and any(c.isalpha() for c in clean)
                    if (has_cjk or has_meaningful_ascii) and len(clean) >= 2:
                        if not all(c in "0123456789abcdefABCDEF#.,;: ()" for c in clean):
                            texts.append(clean.strip())
                        i = end
                        break
                except Exception:
                    continue
            else:
                i += 1
        else:
            i += 1
    return texts


def read_emmx(filepath: str) -> dict:
    """Read an .emmx file and extract mind map content.

    .emmx files are ZIP archives containing:
    - document.xml: metadata (version, creator, dates)
    - mmpage/page.bin: mind map node data (custom binary)
    - theme.xml: visual theme
    - media/: embedded images
    - rels/: resource relationships
    """
    if not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    result = {
        "file": filepath,
        "modified": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
        "pages": [],
    }

    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            names = zf.namelist()

            if "document.xml" in names:
                result["document_xml"] = zf.read("document.xml").decode("utf-8")

            for pf in (n for n in names if n.endswith("page.bin")):
                page_data = zf.read(pf)
                texts = extract_text_from_page_bin(page_data)
                clean_texts = []
                for t in texts:
                    t = t.strip()
                    while t and t[0] in '#!$=<>|\\':
                        t = t[1:]
                    t = t.strip()
                    if len(t) >= 2:
                        clean_texts.append(t)
                result["pages"].append({"file": pf, "nodes": clean_texts})

            media = [n for n in names if n.startswith("media/")]
            if media:
                result["media_files"] = media

    except Exception as e:
        result["error"] = str(e)

    return result


# --- File discovery ---

def find_emmx_files() -> list[dict]:
    """Find all accessible .emmx files across local, cloud cache, and autosave."""
    seen: dict[str, dict] = {}

    def _register(emmx_path: Path, source: str):
        name = emmx_path.stem
        if name.endswith("_backup"):
            name = name[:-7]
        if "_backup_" in name:
            name = name[: name.index("_backup_")]
        mtime = emmx_path.stat().st_mtime
        if name not in seen or mtime > seen[name]["mtime"]:
            seen[name] = {
                "name": name,
                "path": str(emmx_path),
                "mtime": mtime,
                "modified": datetime.fromtimestamp(mtime).isoformat(),
                "source": source,
            }

    # Cloud cache
    if PATHS["tempfile"].exists():
        for emmx in PATHS["tempfile"].rglob("*.emmx"):
            _register(emmx, "cloud_cache")

    # Autosave
    if PATHS["autosave"].exists():
        for emmx in PATHS["autosave"].glob("*.emmx"):
            _register(emmx, "autosave")

    # Common directories
    for d in SEARCH_DIRS:
        if d.exists():
            for emmx in d.glob("*.emmx"):
                _register(emmx, "local")

    # Directories from RecentFiles.xml
    if PATHS["recent_xml"].exists():
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(PATHS["recent_xml"])
            for folder in tree.iter("RecentFolder"):
                folder_path = folder.get("V", "")
                if folder_path and os.path.isdir(folder_path):
                    for emmx in Path(folder_path).glob("*.emmx"):
                        _register(emmx, "local")
        except Exception:
            pass

    files = sorted(seen.values(), key=lambda x: x["mtime"], reverse=True)
    for f in files:
        del f["mtime"]
    return files


# --- Tool handlers ---

def handle_list_mindmaps(_args: dict) -> str:
    files = find_emmx_files()
    if not files:
        return "No EdrawMind files found."
    lines = ["Available mind maps:\n"]
    for f in files:
        lines.append(f"- **{f['name']}** ({f['source']}, modified: {f['modified']})")
        lines.append(f"  Path: {f['path']}")
    return "\n".join(lines)


def handle_read_mindmap(args: dict) -> str:
    target = args.get("name") or args.get("path", "")
    if not target:
        return "Error: Please provide a mind map name or path."

    filepath = None
    if target.endswith(".emmx") and os.path.exists(target):
        filepath = target
    else:
        for f in find_emmx_files():
            if target.lower() in f["name"].lower():
                filepath = f["path"]
                break

    if not filepath:
        return f"Mind map '{target}' not found. Use list_mindmaps to see available files."

    result = read_emmx(filepath)
    if "error" in result:
        return f"Error reading {filepath}: {result['error']}"

    output = [
        f"# Mind Map: {Path(filepath).stem}",
        f"File: {result['file']}",
        f"Last modified: {result['modified']}",
        "",
    ]
    for page in result["pages"]:
        output.append("## Content")
        for node in page["nodes"]:
            output.append(f"- {node}")
    if result.get("media_files"):
        output.append(f"\n## Media: {len(result['media_files'])} embedded images")
    return "\n".join(output)


def handle_search_mindmaps(args: dict) -> str:
    query = args.get("query", "").lower()
    if not query:
        return "Error: Please provide a search query."

    results = []
    for f in find_emmx_files():
        content = read_emmx(f["path"])
        if "error" in content:
            continue
        for page in content.get("pages", []):
            matches = [n for n in page["nodes"] if query in n.lower()]
            if matches:
                results.append({"name": f["name"], "path": f["path"], "matches": matches})

    if not results:
        return f"No matches found for '{query}'."

    output = [f"Search results for '{query}':\n"]
    for r in results:
        output.append(f"### {r['name']}")
        output.append(f"Path: {r['path']}")
        for m in r["matches"][:10]:
            output.append(f"  - {m}")
        output.append("")
    return "\n".join(output)


def handle_create_mindmap(args: dict) -> str:
    title = args.get("title", "New Mind Map")
    markdown = args.get("markdown", "")
    open_in_app = args.get("open_in_app", True)

    if not markdown:
        return "Error: Please provide markdown content for the mind map."

    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "mindmap"
    md_path = os.path.join(tempfile.gettempdir(), f"{safe_title}.md")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    lines = [f"Markdown saved to: {md_path}"]
    if open_in_app:
        if _open_in_edrawmind(md_path):
            lines.append("EdrawMind is opening the file as a new mind map.")
            lines.append("Save it from EdrawMind to keep it as .emmx.")
        else:
            lines.append("Could not open EdrawMind automatically.")
            lines.append(f"Please open this file manually in EdrawMind: {md_path}")
    return "\n".join(lines)


def handle_add_to_mindmap(args: dict) -> str:
    target = args.get("name", "")
    markdown = args.get("markdown", "")

    if not target or not markdown:
        return "Error: Please provide both a mind map name and markdown content."

    lines = []
    for f in find_emmx_files():
        if target.lower() in f["name"].lower():
            lines.append(f"Read existing mind map '{f['name']}'.")
            lines.append("Creating updated version as a new mind map.\n")
            break

    safe_title = "".join(c for c in target if c.isalnum() or c in " _-").strip() or "updated"
    md_path = os.path.join(tempfile.gettempdir(), f"{safe_title}_updated.md")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    if _open_in_edrawmind(md_path):
        lines.append(f"Markdown saved to: {md_path}")
        lines.append("EdrawMind is opening the updated content.")
    else:
        lines.append(f"Markdown saved to: {md_path}")
        lines.append("Please open this file manually in EdrawMind.")
    return "\n".join(lines)


TOOL_HANDLERS = {
    "list_mindmaps": handle_list_mindmaps,
    "read_mindmap": handle_read_mindmap,
    "search_mindmaps": handle_search_mindmaps,
    "create_mindmap": handle_create_mindmap,
    "add_to_mindmap": handle_add_to_mindmap,
}

TOOL_DEFINITIONS = [
    {
        "name": "list_mindmaps",
        "description": "List all available EdrawMind mind map files (local, cloud cache, autosave)",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_mindmap",
        "description": "Read and extract content from an EdrawMind mind map (.emmx file). Accepts a name (partial match) or full file path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Mind map name (partial match) or full file path"}
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_mindmaps",
        "description": "Search across all mind maps for a keyword. Returns matching nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_mindmap",
        "description": "Create a new mind map from Markdown and open it in EdrawMind. Use heading levels (# ## ###) for tree structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title for the mind map"},
                "markdown": {"type": "string", "description": "Markdown content with headings for tree structure"},
                "open_in_app": {"type": "boolean", "description": "Open in EdrawMind (default: true)"},
            },
            "required": ["title", "markdown"],
        },
    },
    {
        "name": "add_to_mindmap",
        "description": "Read an existing mind map, merge new content, and open the result in EdrawMind.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Existing mind map name (partial match)"},
                "markdown": {"type": "string", "description": "Full merged markdown content"},
            },
            "required": ["name", "markdown"],
        },
    },
]


# --- MCP server main loop ---

def main():
    while True:
        header = ""
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            header += line
            if header.endswith("\r\n\r\n") or header.endswith("\n\n"):
                break

        content_length = 0
        for line in header.strip().split("\n"):
            if line.strip().lower().startswith("content-length:"):
                content_length = int(line.split(":")[1].strip())
                break

        if content_length == 0:
            continue

        body = sys.stdin.read(content_length)
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            send_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mindclaude", "version": "1.0.0"},
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send_response(req_id, {"tools": TOOL_DEFINITIONS})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            handler = TOOL_HANDLERS.get(tool_name)
            if handler:
                try:
                    text = handler(tool_args)
                    send_response(req_id, {"content": [{"type": "text", "text": text}]})
                except Exception as e:
                    send_response(req_id, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
            else:
                send_response(req_id, {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True})
        elif method == "ping":
            send_response(req_id, {})
        elif req_id is not None:
            send_error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
