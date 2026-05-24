import hashlib
import re
from pathlib import Path
from .frontmatter import parse_frontmatter,format_frontmatter

def build_memory_prompt_section() -> str:
    index = load_memory_index()
    memory_dir = str(get_memory_dir())

    memory_prompt= f"""# Memory System

            You have a persistent, file-based memory system at `{memory_dir}`.

            ## Memory Types
            - **user**: User's role, preferences, knowledge level
            - **feedback**: Corrections and guidance from the user
            - **project**: Ongoing work, goals, deadlines, decisions
            - **reference**: Pointers to external resources

            ## How to Save Memories
            Use the write_file tool to create a memory file with YAML frontmatter:
            ...
            Save to: `{memory_dir}/`
            Filename format: `{{type}}_{{slugified_name}}.md`

            ## What NOT to Save
            - Code patterns or architecture (read the code instead)
            - Git history (use git log)
            - Anything already in CLAUDE.md
            - Ephemeral task details

            {"## Current Memory Index" + chr(10) + index if index else "(No memories saved yet.)"}"""
    return memory_prompt

# --------------------------Paths--------------------------
def _project_hash() -> str:
    return hashlib.sha256(str(Path.cwd()).encode()).hexdigest()[:16]

def get_memory_dir() -> Path:
    d = Path.home() / ".Phorni" / "projects" / _project_hash() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _get_index_path() -> Path:
    return get_memory_dir() / "MEMORY.md"
#---------------------------Save-------------------------------
def save_memory(name:str,description:str,type:str,content:str)->str:
    d = get_memory_dir()
    filename = f"{type}_{_slugify(name)}.md"
    text = format_frontmatter(
        {"name": name, "description": description, "type": type}, content
    )
    (d / filename).write_text(text)
    _update_memory_index()
    return filename

def _update_memory_index() -> None:
    memories = list_memories()
    lines = ["# Memory Index", ""]
    for m in memories:
        lines.append(f"- **[{m.name}]({m.filename})** ({m.type}) — {m.description}")
    _get_index_path().write_text("\n".join(lines))
#--------------------------load---------------------------------
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25000

def load_memory_index() -> str:
    index_path = _get_index_path()
    if not index_path.exists():
        return ""
    content = index_path.read_text()
    lines = content.split("\n")
    if len(lines) > MAX_INDEX_LINES:
        content = "\n".join(lines[:MAX_INDEX_LINES]) + "\n\n[... truncated, too many memory entries ...]"
    if len(content.encode()) > MAX_INDEX_BYTES:
        content = content[:MAX_INDEX_BYTES] + "\n\n[... truncated, index too large ...]"
    return content

already_surfaced=set()
SELECT_MEMORY_PROMPT="""
You are selecting memories that will be useful to an AI coding assistant as it processes a user's query. You will be given the user's query and a list of available memory files with their filenames and descriptions.

Return a JSON object with a "selected_memories" array of filenames for the memories that will clearly be useful (up to 5). Only include memories that you are certain will be helpful based on their name and description.
- If you are unsure if a memory will be useful, do not include it.
- If no memories would clearly be useful, return an empty array.
"""

def select_relevant_memory(query:str)->list[str]:
    pass
#--------------------------tools--------------------------------
def list_memories()->list[dict[str,str]]:
    memories:list[dict[str,str]]=[]
    d=get_memory_dir()
    for file in d.glob("*.md"):
        if file.name=="MEMORY.md":
            continue
        content=file.read_text(encoding="utf-8")
        m=parse_frontmatter(content)
        if m:
            memories.append(m)
    return memories

def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower())
    s = s.strip("_")
    return s[:40]