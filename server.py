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

def _is_meaningful_text(text: str) -> bool:
    """Check if extracted text is meaningful content (not binary noise)."""
    if len(text) < 2:
        return False
    if all(c in "0123456789abcdefABCDEF#.,;: ()" for c in text):
        return False
    has_cjk = any(
        0x3000 <= ord(c) <= 0x9FFF
        or 0xF900 <= ord(c) <= 0xFAFF
        or 0xFF00 <= ord(c) <= 0xFFEF
        or 0xAC00 <= ord(c) <= 0xD7AF  # Korean
        for c in text
    )
    has_meaningful_ascii = len(text) >= 5 and any(c.isalpha() for c in text)
    return has_cjk or has_meaningful_ascii


def extract_text_from_page_bin(data: bytes) -> list[str]:
    """Extract text nodes from EdrawMind page.bin binary format (legacy)."""
    texts = []
    i = 0
    while i < len(data):
        if data[i] >= 0x80 or (0x20 <= data[i] < 0x7F):
            for end in range(min(i + 2000, len(data)), i + 1, -1):
                try:
                    s = data[i:end].decode("utf-8")
                    clean = "".join(c for c in s if ord(c) >= 32)
                    if _is_meaningful_text(clean):
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


def extract_structured_nodes(data: bytes) -> list[dict]:
    """Extract structured node data from page.bin including labels and notes.

    Field numbers vary by theme, but follow a consistent pattern:
    - Root label: fields 122-123
    - Branch/leaf labels: fields 126-131
    - Note/annotation text: fields 132-134
    - Floating topics / note refs: field 135
    - Hyperlinks detected by 'http' prefix
    """
    nodes = []
    current_node = None

    # Known label fields (vary by theme/version offset)
    LABEL_FIELDS = {122, 123, 126, 128, 131}
    NOTE_FIELDS = {132, 134}
    REF_FIELDS = {135}
    ALL_FIELDS = LABEL_FIELDS | NOTE_FIELDS | REF_FIELDS

    i = 0
    while i < len(data) - 4:
        if data[i] == 0x04 and i >= 3:
            field_num = None

            if data[i - 2] == 0x02:
                field_num = data[i - 1]
            elif i >= 4 and data[i - 3] == 0x02:
                field_num = (data[i - 2] & 0x7F) | (data[i - 1] << 7)

            if field_num is not None and field_num in ALL_FIELDS:
                end = data.find(b"\x00", i + 1)
                if end > i + 1 and end - i < 5000:
                    try:
                        text = data[i + 1 : end].decode("utf-8")
                        clean = "".join(c for c in text if ord(c) >= 32).strip()
                    except Exception:
                        i += 1
                        continue

                    if not clean:
                        i = end + 1
                        continue

                    if field_num in LABEL_FIELDS and _is_meaningful_text(clean):
                        current_node = {"label": clean, "type": "node", "notes": [], "links": []}
                        nodes.append(current_node)
                    elif field_num in NOTE_FIELDS and current_node and _is_meaningful_text(clean):
                        current_node["notes"].append(clean)
                    elif field_num in REF_FIELDS:
                        if clean.startswith("http") and current_node:
                            current_node["links"].append(clean)
                        elif _is_meaningful_text(clean):
                            current_node = {"label": clean, "type": "node", "notes": [], "links": []}
                            nodes.append(current_node)
                    elif clean.startswith("http") and current_node:
                        current_node["links"].append(clean)

                    i = end + 1
                    continue
        i += 1

    return nodes


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

                # Structured extraction (with notes, links)
                structured = extract_structured_nodes(page_data)
                if structured:
                    result["pages"].append({"file": pf, "structured_nodes": structured})
                else:
                    # Fallback to legacy text extraction
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
        if "structured_nodes" in page:
            for node in page["structured_nodes"]:
                label = node["label"]
                ntype = node.get("type", "")
                prefix = {"root": "# ", "branch": "## ", "leaf": "- ", "node": "- "}.get(ntype, "- ")
                output.append(f"{prefix}{label}")
                for note in node.get("notes", []):
                    output.append(f"  > {note}")
                for link in node.get("links", []):
                    output.append(f"  [link]({link})")
        else:
            for node in page.get("nodes", []):
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


def handle_generate_plan(args: dict) -> str:
    period = args.get("period", "weekly")
    source = args.get("source", "")
    tasks_json = args.get("tasks", "")
    open_in_app = args.get("open_in_app", True)

    # Determine period label and date range
    now = datetime.now()
    if period == "monthly":
        period_label = now.strftime("%Y年%m月")
        safe_name = now.strftime("%Y%m_plan")
    else:
        # Weekly: Monday to Sunday
        from datetime import timedelta
        monday = now - timedelta(days=now.weekday())
        sunday = monday + timedelta(days=6)
        period_label = f"{monday.strftime('%m/%d')}〜{sunday.strftime('%m/%d')}"
        safe_name = monday.strftime("%Y%m%d_weekly")

    # If source mindmap specified, read it (using clean text extraction)
    source_nodes = []
    source_name = ""
    if source:
        for f in find_emmx_files():
            if source.lower() in f["name"].lower():
                source_name = f["name"]
                result = read_emmx(f["path"])
                if "error" not in result:
                    for page in result.get("pages", []):
                        for node in page["nodes"]:
                            # Filter out binary noise
                            clean = node.strip()
                            if len(clean) >= 2 and any(
                                '\u3000' <= c <= '\u9fff' or c.isalpha() for c in clean
                            ):
                                source_nodes.append(clean)
                break

    # Parse tasks JSON if provided
    categories: dict[str, list[dict]] = {}
    if tasks_json:
        try:
            tasks = json.loads(tasks_json) if isinstance(tasks_json, str) else tasks_json
            for task in tasks:
                cat = task.get("category", "その他")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(task)
        except (json.JSONDecodeError, TypeError):
            pass

    # Build markdown with template structure
    lines = [f"# {period_label} プラン"]

    if categories:
        for cat, tasks in categories.items():
            lines.append(f"## {cat}")
            for task in tasks:
                name = task.get("name", "")
                deadline = task.get("deadline", "")
                priority = task.get("priority", "")
                notes = task.get("notes", "")

                # Build task line with deadline and priority markers
                task_line = f"### {name}"
                lines.append(task_line)

                if deadline:
                    lines.append(f"#### 〆 {deadline}")
                if priority:
                    priority_mark = {"high": "優先度：高", "medium": "優先度：中", "low": "優先度：低"}.get(priority, priority)
                    lines.append(f"#### {priority_mark}")
                if notes:
                    lines.append(f"#### {notes}")
    else:
        # Empty template
        lines.extend([
            "## 最優先（今すぐ）",
            "### タスク名",
            "#### 〆 MM/DD",
            "## プロジェクトA",
            "### タスク名",
            "#### 〆 MM/DD",
            "#### メモ",
            "## プロジェクトB",
            "### タスク名",
            "## 今期中にやりたい",
            "### タスク名",
        ])

    if source_nodes:
        lines.extend(["", f"## 元データ（{source_name}）"])
        for node in source_nodes[:30]:
            lines.append(f"### {node}")

    markdown = "\n".join(lines)
    md_path = os.path.join(tempfile.gettempdir(), f"{safe_name}.md")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    result_lines = [
        f"Generated {period} plan: {period_label}",
        f"Markdown saved to: {md_path}",
    ]

    if open_in_app:
        if _open_in_edrawmind(md_path):
            result_lines.append("EdrawMind is opening the plan.")
        else:
            result_lines.append("Please open this file manually in EdrawMind.")

    if source_nodes:
        result_lines.append(f"\nSource mind map '{source_name}' content was included for reference.")

    return "\n".join(result_lines)


TOOL_HANDLERS = {
    "list_mindmaps": handle_list_mindmaps,
    "read_mindmap": handle_read_mindmap,
    "search_mindmaps": handle_search_mindmaps,
    "create_mindmap": handle_create_mindmap,
    "add_to_mindmap": handle_add_to_mindmap,
    "generate_plan": handle_generate_plan,
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
    {
        "name": "generate_plan",
        "description": "Generate a weekly or monthly plan mind map with structured categories, deadlines, and priorities. Can read an existing mind map as source and reorganize it. Tasks are provided as a JSON array with fields: name, category, deadline, priority (high/medium/low), notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["weekly", "monthly"],
                    "description": "Plan period: weekly or monthly",
                },
                "source": {
                    "type": "string",
                    "description": "Optional: existing mind map name to read and reorganize",
                },
                "tasks": {
                    "type": "string",
                    "description": 'JSON array of tasks. Each task: {"name": "...", "category": "...", "deadline": "MM/DD", "priority": "high|medium|low", "notes": "..."}',
                },
                "open_in_app": {
                    "type": "boolean",
                    "description": "Open in EdrawMind (default: true)",
                },
            },
            "required": ["period"],
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
