import fnmatch
import json
import re
import subprocess
from pathlib import Path

ToolDef = dict

PermissionMode = str  # "default" | "plan" | "acceptEdits" | "bypassPermissions" | "dontAsk"

tool_definitions: list[ToolDef] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Returns the file content with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The path to the file to read"},
                },
                "required": ["file_path"],
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The path to the file to write"},
                    "content": {"type": "string", "description": "The content to write to the file"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file by replacing an exact string match with new content. The old_string must match exactly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The path to the file to edit"},
                    "old_string": {"type": "string", "description": "The exact string to find and replace"},
                    "new_string": {"type": "string", "description": "The string to replace it with"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory. Supports glob patterns for filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The directory to list"},
                    "pattern": {"type": "string", "description": "Optional glob pattern to filter (e.g. '**/*.py')"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search file contents with regex patterns. Returns matching lines with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "The regex pattern to search for"},
                    "file_path": {"type": "string", "description": "File or directory to search in. Defaults to current directory"},
                    "include": {"type": "string", "description": "Optional glob pattern to filter files (e.g. '*.py')"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Execute a shell command. Returns stdout and stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return its content as text. For HTML pages, tags are stripped.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                    "max_length": {"type": "number", "description": "Maximum content length (default 50000)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enter_plan_mode",
            "description": "Enter plan mode to switch to a read-only planning phase. In plan mode, you can only read files and write to the plan file.",
            "parameters": {"type": "object", "properties": {
                "plan_file_path": {"type": "string", "description": "Optional path to the plan file. If not specified, one will be generated automatically."},
            }},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exit_plan_mode",
            "description": "Exit plan mode after you have finished writing your plan to the plan file.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

PLAN_MODE_TOOLS = {"enter_plan_mode", "exit_plan_mode"}

CONCURRENCY_SAFE_TOOLS = {"read_file", "list_files", "grep_search", "web_fetch"}

READ_TOOLS = {"read_file", "list_files", "grep_search", "web_fetch"}
EDIT_TOOLS = {"write_file", "edit_file"}

#-----------------------------safety--------------------------------
DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s"),
    re.compile(r"\bgit\s+(push|reset|clean|checkout\s+\.)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bkill\b"),
    re.compile(r"\bpkill\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\bdel\s", re.IGNORECASE),
    re.compile(r"\brmdir\s", re.IGNORECASE),
    re.compile(r"\bformat\s", re.IGNORECASE),
    re.compile(r"\btaskkill\s", re.IGNORECASE),
    re.compile(r"\bRemove-Item\s", re.IGNORECASE),
    re.compile(r"\bStop-Process\s", re.IGNORECASE),
]

def is_dangerous(command: str) -> bool:
    return any(p.search(command) for p in DANGEROUS_PATTERNS)

def _parse_rule(rule: str) -> dict:
    m = re.match(r"^([a-z_]+)\((.+)\)$", rule)
    if m:
        return {"tool": m.group(1), "pattern": m.group(2)}
    return {"tool": rule, "pattern": None}

_cached_rules: dict | None = None

def load_permission_rules() -> dict:
    global _cached_rules
    if _cached_rules is not None:
        return _cached_rules

    allow: list[dict] = []
    deny: list[dict] = []

    settings_paths = [
        Path.home() / ".phorni" / "settings.json",
        Path.cwd() / ".phorni" / "settings.json",
    ]

    for settings_path in settings_paths:
        try:
            with open(settings_path) as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            continue

        if not settings or "permissions" not in settings:
            continue
        perms = settings["permissions"]
        for r in perms.get("allow", []):
            allow.append(_parse_rule(r))
        for r in perms.get("deny", []):
            deny.append(_parse_rule(r))

    _cached_rules = {"allow": allow, "deny": deny}
    return _cached_rules

def _matches_rule(rule: dict, tool_name: str, inp: dict) -> bool:
    if rule["tool"] != tool_name:
        return False
    if rule["pattern"] is None:
        return True

    value = ""
    if tool_name == "run_shell":
        value = inp.get("command", "")
    elif "file_path" in inp:
        value = inp["file_path"]
    else:
        return True

    pattern = rule["pattern"]
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return value == pattern

def _check_permission_rules(tool_name: str, inp: dict) -> str | None:
    rules = load_permission_rules()

    for rule in rules["deny"]:
        if _matches_rule(rule, tool_name, inp):
            return "deny"
    for rule in rules["allow"]:
        if _matches_rule(rule, tool_name, inp):
            return "allow"
    return None

def check_permission(
    tool_name: str,
    inp: dict,
    mode: str = "default",
    plan_file_path: str | None = None,
) -> dict:
    """Returns {"action": "allow"|"deny"|"confirm", "message": ...}"""
    if mode == "bypassPermissions":
        return {"action": "allow"}

    # Layer 1: 配置文件规则（deny 优先）
    rule_result = _check_permission_rules(tool_name, inp)
    if rule_result == "deny":
        return {"action": "deny", "message": f"Denied by permission rule for {tool_name}"}
    if rule_result == "allow":
        return {"action": "allow"}

    # 读工具永远安全
    if tool_name in READ_TOOLS:
        return {"action": "allow"}

    # plan 模式工具始终允许（agent 层拦截处理状态切换）
    if tool_name in PLAN_MODE_TOOLS:
        return {"action": "allow"}

    # 权限模式检查
    if mode == "plan":
        if tool_name in EDIT_TOOLS:
            file_path = inp.get("file_path")
            if plan_file_path and file_path == plan_file_path:
                return {"action": "allow"}
            return {"action": "deny", "message": f"Blocked in plan mode: {tool_name}"}
        if tool_name == "run_shell":
            return {"action": "deny", "message": "Shell commands blocked in plan mode"}

    if mode == "acceptEdits" and tool_name in EDIT_TOOLS:
        return {"action": "allow"}

    # Layer 2: 内置危险模式检查
    needs_confirm = False
    confirm_message = ""

    if tool_name == "run_shell" and is_dangerous(inp.get("command", "")):
        needs_confirm = True
        confirm_message = inp.get("command", "")
    elif tool_name == "write_file" and not Path(inp.get("file_path", "")).exists():
        needs_confirm = True
        confirm_message = f"write new file: {inp.get('file_path', '')}"
    elif tool_name == "edit_file" and not Path(inp.get("file_path", "")).exists():
        needs_confirm = True
        confirm_message = f"edit non-existent file: {inp.get('file_path', '')}"

    if needs_confirm:
        if mode == "dontAsk":
            return {"action": "deny", "message": f"Auto-denied (dontAsk mode): {confirm_message}"}
        return {"action": "confirm", "message": confirm_message}

    return {"action": "allow"}
#-----------------------------execution--------------------------------
async def execute_tool(name: str, inp: dict) -> str:
    handlers = {
        "read_file": _read_file,
        "write_file": _write_file,
        "edit_file": _edit_file,
        "list_files": _list_files,
        "grep_search": _grep_search,
        "run_shell": _run_shell,
        "web_fetch": _web_fetch,
    }
    handler = handlers.get(name)
    if not handler:
        return f"Unknown tool: {name}"
    return _truncate_result(handler(inp))

def _read_file(inp: dict) -> str:
    try:
        path = Path(inp["file_path"])
        content = path.read_text(encoding="utf-8")
        lines=content.split("\n")
        numbered="\n".join(f"{i+1:4d}|{line}" for i,line in enumerate(lines))   #行号用于定位，匹配时使用字符串
        return numbered
    except Exception as e:
        return f"Error reading file: {e}"

def _list_files(inp: dict) -> str:
    try:
        path = Path(inp.get("file_path") or ".")
        pattern = inp.get("pattern")
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        if pattern:
            entries = [e for e in entries if fnmatch.fnmatch(e.name, pattern)]
        lines = []
        for e in entries[:200]:
            suffix = "/" if e.is_dir() else ""
            lines.append(e.name + suffix)
        output = "\n".join(lines)
        if len(entries) > 200:
            output += f"\n... and {len(entries) - 200} more entries"
        return output or "(empty directory)"
    except Exception as e:
        return f"Error listing files: {e}"

def _edit_file(inp:dict)->str:
    try:
        path=Path(inp["file_path"])
        content=path.read_text(encoding="utf-8")

        actual=_find_actual_string(content,inp["old_string"])
        if not actual:  #无匹配内容，模型幻觉
            return f"Error:old_string not found in {inp["file_path"]}"
        
        count=content.count(actual)
        if count>1:     #匹配内容过多，修改对象不够准确
            return f"Error:old_string found {count} times in {inp["file_path"]}.Must be unique"
        
        new_content=content.replace(actual,inp["new_string"])
        path.write_text(new_content, encoding="utf-8")

        #diff=_generate_diff(content,actual,inp["new_string"])
        quote_note=" (matched via quote normalization)" if actual != inp["old_string"] else ""
        return f"Successfully edited {inp['file_path']}{quote_note}"
    except Exception as e:
        return f"Error editing file: {e}"
    
def _write_file(inp:dict)->str:
    try:
        path=Path(inp["file_path"])
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(inp["content"], encoding="utf-8")
        lines=inp["content"].split("\n")
        line_count=len(lines)
        preview="\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines[:30]))
        trunc=trunc = f"\n  ... ({line_count} lines total)" if line_count > 30 else ""
        return f"Successfully wrote to {inp["file_path"]}({line_count}lines)\n\n{preview}{trunc}"
    except Exception as e:
        return f"Error writing file: {e}"
    
def _grep_search(inp:dict)->str:
    pattern=inp["pattern"]
    path=inp.get("file_path")or"."
    include=inp.get("include")

    try:
        args = ["grep", "--line-number", "--color=never", "-r"]
        if include:
            args.append(f"--include={include}")
        args.extend(["--",pattern,path])
        result=subprocess.run(args,capture_output=True,text=True,timeout=10,encoding="utf-8",errors="replace")
        if result.returncode==1:
            return "No matches found."
        if result.returncode!=0:
            return f"Error:{result.stderr}"
        lines=[l for l in result.stdout.split("\n")if l]
        output="\n".join(lines[:100])
        if len(lines)>100:
            output+=f"\n... and {len(lines)-100} more matches"  #提示应该优化搜索范围
        return output
    except Exception as e:
        return f"Error: {e}"
    
def _run_shell(inp: dict) -> str:
    try:
        timeout = inp.get("timeout", 30)
        result = subprocess.run(
            inp["command"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=inp.get("_cwd"),
            encoding="utf-8", errors="replace",
        )
        if result.returncode!=0:
            stderr=f"\nStderr:{result.stderr}" if result.stderr else ""
            stdout=f"\nStdout:{result.stdout}" if result.stdout else ""
            return f"Command failed (exit code {result.returncode}){stdout}{stderr}"
        return result.stdout or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
    
def _web_fetch(inp: dict) -> str:
    import urllib.request
    import urllib.error

    url = inp["url"]
    max_length = inp.get("max_length") or 50000

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "phorni/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return f"HTTP error: {e.code} {e.reason}"
    except Exception as e:
        return f"Error fetching {url}: {e}"

    if "html" in content_type.lower():
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]*>", " ", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > max_length:
        text = text[:max_length] + f"\n\n[... truncated at {max_length} characters]"

    return text or "(empty response)"
#-----------------------------tools--------------------------------
def _normalize_quotes(s: str) -> str:
    s = re.sub("[\u2018\u2019\u2032]", "'", s)
    s = re.sub('[\u201c\u201d\u2033]', '"', s)
    return s

def _find_actual_string(file_content: str, search_string: str) -> str | None:
    if search_string in file_content:
        return search_string
    norm_search = _normalize_quotes(search_string)
    norm_file = _normalize_quotes(file_content)
    idx = norm_file.find(norm_search)   #标准化后模糊匹配
    if idx != -1:
        return file_content[idx:idx + len(search_string)]   #返回标准化前内容
    return None
#-----------------------------compact--------------------------------
MAX_RESULT_CHARS=50000

def _truncate_result(result:str)->str:
    if len(result)<=MAX_RESULT_CHARS:
        return result
    keep_each=(MAX_RESULT_CHARS-60)//2
    return (
        result[:keep_each]
        + f"\n\n[... truncated {len(result) - keep_each * 2} chars ...]\n\n"
        + result[-keep_each:]
    )