import fnmatch
import json
import re
import subprocess
from pathlib import Path

ToolDef = dict

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
                    "path": {"type": "string", "description": "The directory to list"},
                    "pattern": {"type": "string", "description": "Optional glob pattern to filter (e.g. '**/*.py')"},
                },
                "required": ["path"],
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
                    "path": {"type": "string", "description": "File or directory to search in. Defaults to current directory"},
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
]

async def execute_tool(name:str,inp:dict)->str:
    handlers={
        "read_file": _read_file,
        "write_file": _write_file,
        "edit_file": _edit_file,
        "list_files": _list_files,
        "grep_search": _grep_search,
        "run_shell": _run_shell,
    }
    handler=handlers.get(name)
    if not handler:
        return f"Unknown tool:{name}"
    return _truncate_result(handler(inp))

def _read_file(inp:dict)->str:
    try:
        content=Path(inp["file_path"]).read_text()
        lines=content.split("\n")
        numbered="\n".join(f"{i+1:4d}|{line}" for i,line in enumerate(lines))   #行号用于定位，匹配时使用字符串
        return numbered
    except Exception as e:
        return f"Error reading file: {e}"

def _list_files(inp: dict) -> str:
    try:
        path = Path(inp.get("path") or ".")
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
        content=path.read_text()

        actual=_find_actual_string(content,inp["old_string"])
        if not actual:  #无匹配内容，模型幻觉
            return f"Error:old_string not found in {inp["file_path"]}"
        
        count=content.count(actual)
        if count>1:     #匹配内容过多，修改对象不够准确
            return f"Error:old_string found {count} times in {inp["file_path"]}.Must be unique"
        
        new_content=content.replace(actual,inp["new_string"])
        path.write_text(new_content)

        #diff=_generate_diff(content,actual,inp["new_string"])
        quote_note=" (matched via quote normalization)" if actual != inp["old_string"] else ""
        return f"Successfully edited {inp['file_path']}{quote_note}"
    except Exception as e:
        return f"Error editing file: {e}"
    
def _write_file(inp:dict)->str:
    try:
        path=Path(inp["file_path"])
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(inp["content"])
        lines=inp["content"].split("\n")
        line_count=len(lines)
        preview="\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines[:30]))
        trunc=trunc = f"\n  ... ({line_count} lines total)" if line_count > 30 else ""
        return f"Successfully wrote to {inp["file_path"]}({line_count}lines)\n\n{preview}{trunc}"
    except Exception as e:
        return f"Error writing file: {e}"
    
def _grep_search(inp:dict)->str:
    pattern=inp["pattern"]
    path=inp.get("path")or"."   #inp.get("path",".")无法正确处理None或空值情况
    include=inp.get("include")

    try:
        args=["grep,""--line-number","--color=never","-r"]
        if include:
            args.append(f"--include={include}")
        args.extend(["--",pattern,path])
        result=subprocess.run(args,capture_output=True,text=True,timeout=10)
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
    
def _run_shell(inp:dict)->str:
    try:
        timeout=inp.get("timeout",30)
        result=subprocess.run(
            inp["command"],
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
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