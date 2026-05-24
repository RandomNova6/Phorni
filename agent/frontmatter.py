from dataclasses import dataclass, field

@dataclass
class FrontmatterResult:
    meta: dict[str, str] = field(default_factory=dict)
    body: str = ""

def parse_frontmatter(content:str)->FrontmatterResult:
    lines=content.split('\n')
    if not lines or lines[0].strip()!="---":
        return FrontmatterResult(body=content)
    
    end_idx=-1
    for line in lines[1:]:
        if line.strip()=="---":
            end_idx=lines.index(line)
            break
    if end_idx==-1:
        return FrontmatterResult(body=content)

    meta:dict[str,str]={}
    for line in lines[1:end_idx]:
        key,value=line.split(":",1)
        if key and value:
            meta[key.strip()]=value.strip()
    
    body = "\n".join(lines[end_idx + 1:]).strip()
    return FrontmatterResult(meta=meta, body=body)

def format_frontmatter(meta:dict[str,str], content:str)->str:
    meta = f"""---
            name: {meta.get("name", "")}
            description: {meta.get("description", "")}
            type: {meta.get("type", "")}
            ---
            """
    return meta + content