#!/usr/bin/env python3
"""
semantic_memory.py — Semantic memory search + embedding generator
Usage:
  python3 semantic_memory.py embed          # Generate embeddings untuk semua memory yang belum punya
  python3 semantic_memory.py search "query" # Semantic search
  python3 semantic_memory.py save "content" [scope] # Save + embed memory baru
  python3 semantic_memory.py relevant "keyword1,keyword2" # Search only if topic is specific (skip small talk)
"""

import sys
import json
import os
import urllib.request
import urllib.parse
from pathlib import Path

# Load .env
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SERVICE_KEY = os.environ.get("SUPABASE_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_EMBED_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={GEMINI_API_KEY}"

HEADERS = {
    "Authorization": f"Bearer {SERVICE_KEY}",
    "apikey": SERVICE_KEY,
    "Content-Type": "application/json"
}

def supabase_get(path):
    req = urllib.request.Request(f"{SUPABASE_URL}{path}", headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def supabase_patch(path, data):
    req = urllib.request.Request(
        f"{SUPABASE_URL}{path}",
        data=json.dumps(data).encode(),
        headers={**HEADERS, "Prefer": "return=minimal"},
        method="PATCH"
    )
    with urllib.request.urlopen(req) as r:
        return r.status

def supabase_post(path, data):
    req = urllib.request.Request(
        f"{SUPABASE_URL}{path}",
        data=json.dumps(data).encode(),
        headers={**HEADERS, "Prefer": "return=representation"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def get_embedding(text):
    """Generate embedding vector dari Gemini gemini-embedding-001 (768 dim)"""
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": 768
    }
    req = urllib.request.Request(
        GEMINI_EMBED_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        return result["embedding"]["values"]

def cosine_similarity(a, b):
    """Hitung cosine similarity antara dua vector"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x**2 for x in a) ** 0.5
    norm_b = sum(x**2 for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0
    return dot / (norm_a * norm_b)

def cmd_embed():
    """Generate embeddings untuk semua memory yang belum punya"""
    memories = supabase_get("/rest/v1/agent_memories?embedding=is.null&select=id,content&limit=100")
    print(f"Found {len(memories)} memories without embeddings")
    
    for m in memories:
        try:
            emb = get_embedding(m["content"])
            supabase_patch(f"/rest/v1/agent_memories?id=eq.{m['id']}", {"embedding": emb})
            print(f"  ✅ {m['content'][:50]}...")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    print("Done!")

def cmd_search(query, top_k=5):
    """Semantic search — ambil top-k memory yang paling relevan"""
    # Generate embedding untuk query
    query_emb = get_embedding(query)
    
    # Ambil semua memory yang punya embedding
    memories = supabase_get("/rest/v1/agent_memories?embedding=not.is.null&select=id,content,scope,embedding&limit=500")
    
    if not memories:
        print("No memories with embeddings found. Run: python3 semantic_memory.py embed")
        return []
    
    # Hitung similarity
    scored = []
    for m in memories:
        emb = m["embedding"]
        # Supabase returns vector as string like "[0.1,0.2,...]"
        if isinstance(emb, str):
            emb = [float(x) for x in emb.strip("[]").split(",")]
        sim = cosine_similarity(query_emb, emb)
        scored.append((sim, m["content"], m["scope"]))
    
    # Sort by similarity
    scored.sort(reverse=True)
    results = scored[:top_k]
    
    print(f"\n🔍 Semantic search: '{query}'")
    print(f"Top {top_k} results:\n")
    for i, (sim, content, scope) in enumerate(results, 1):
        print(f"{i}. [{scope}] (score: {sim:.3f})")
        print(f"   {content[:150]}")
        print()
    
    return results

def cmd_save(content, scope="core"):
    """Save memory baru dengan embedding"""
    emb = get_embedding(content)
    result = supabase_post("/rest/v1/agent_memories", {
        "content": content,
        "scope": scope,
        "embedding": emb
    })
    print(f"✅ Saved: {content[:80]}...")
    return result


# ---------------------------------------------------------------------------
# search_if_relevant() — Smart topic gate to avoid unnecessary embedding calls
# ---------------------------------------------------------------------------

# Small talk / generic phrases that don't need memory search
SMALL_TALK_PATTERNS = [
    "halo", "hai", "hi", "hello", "hey",
    "apa kabar", "how are you", "gimana",
    "terima kasih", "thanks", "thank you", "makasih",
    "oke", "ok", "okay", "sip", "siap",
    "ya", "iya", "yes", "no", "tidak", "nggak",
    "lol", "haha", "wkwk", "😂", "🤣",
    "good morning", "good night", "selamat pagi", "selamat malam",
    "mantap", "nice", "keren",
    "bye", "dadah", "sampai jumpa",
]

# Project names, client names, and technical terms that warrant a memory search
SPECIFIC_TERM_PATTERNS = [
    # Projects & products
    "autofint", "djeonail", "satu crm", "djeon lms",
    # Clients
    "ricky", "rototama", "paradyse", "frx", "kenny", "puddinge",
    "naserullah", "iqbal", "nilaigizi", "turrima",
    # Tech stack
    "n8n", "supabase", "hubspot", "waha", "infobip", "repliz",
    "notion", "gemini", "openai", "lovable",
    # Agents
    "nara", "tania", "lyra", "rina", "deva", "fana", "aria",
    # Specific workflows
    "approval", "carousel", "template", "webhook", "cron",
    # Finance
    "payment", "invoice", "bayar", "revenue", "budget",
    # Content/brand
    "hashtag", "caption", "reels", "instagram", "konten", "content",
]

def is_specific_topic(topic_keywords: list[str]) -> tuple[bool, str]:
    """
    Determine if topic keywords are specific enough to warrant a memory search.
    
    Returns:
        (should_search: bool, reason: str)
    
    Logic:
    - If any keyword matches a known specific term → search
    - If all keywords are small talk patterns → skip
    - If keywords are generic but non-trivial → search (benefit of doubt)
    - Short single-word generic inputs → skip
    """
    if not topic_keywords:
        return False, "no keywords provided"
    
    keywords_lower = [kw.strip().lower() for kw in topic_keywords if kw.strip()]
    
    if not keywords_lower:
        return False, "empty keywords after stripping"
    
    # Check for specific terms — immediate yes (whole-word match only)
    for kw in keywords_lower:
        for pattern in SPECIFIC_TERM_PATTERNS:
            # Exact match or kw starts/ends with pattern (avoid substring false positives)
            if kw == pattern or kw.startswith(pattern + " ") or kw.endswith(" " + pattern):
                return True, f"specific term matched: '{pattern}'"
            # Pattern is a multi-word phrase and is fully contained in kw
            if " " in pattern and pattern in kw:
                return True, f"specific term matched: '{pattern}'"
            # kw is fully contained in pattern (e.g. user typed "autofint")
            if len(kw) >= 4 and kw == pattern:
                return True, f"specific term matched: '{pattern}'"
    
    # Check if all keywords are pure small talk
    small_talk_count = 0
    for kw in keywords_lower:
        for pattern in SMALL_TALK_PATTERNS:
            if kw == pattern or kw.startswith(pattern):
                small_talk_count += 1
                break
    
    if small_talk_count == len(keywords_lower):
        return False, f"all keywords are small talk: {keywords_lower}"
    
    # Keywords longer than 4 chars that aren't small talk → probably specific
    meaningful = [kw for kw in keywords_lower if len(kw) > 4]
    if meaningful:
        return True, f"meaningful non-trivial keywords: {meaningful}"
    
    # Very short generic single keyword → skip
    if len(keywords_lower) == 1 and len(keywords_lower[0]) <= 4:
        return False, f"short generic keyword: '{keywords_lower[0]}'"
    
    return True, "keywords pass specificity check"


def search_if_relevant(topic_keywords: list[str], top_k: int = 5, verbose: bool = True) -> list:
    """
    Smart semantic search gate — only runs full embedding search if topic is specific.
    
    Use this instead of cmd_search() when you're not sure if search is needed,
    e.g., during heartbeats or when deciding whether to query memory for a new message.
    
    Args:
        topic_keywords: List of keywords extracted from the conversation topic
        top_k: Number of results to return if search runs
        verbose: Print decision reasoning (set False for silent mode)
    
    Returns:
        List of (similarity, content, scope) tuples, or [] if search was skipped
    
    Examples:
        # Will search — project name
        results = search_if_relevant(["autofint", "pricing"])
        
        # Will search — client name  
        results = search_if_relevant(["ricky", "rototama", "invoice"])
        
        # Will skip — small talk
        results = search_if_relevant(["halo", "apa kabar"])
        
        # Will skip — too generic
        results = search_if_relevant(["ok"])
    """
    should_search, reason = is_specific_topic(topic_keywords)
    
    if verbose:
        kw_str = ", ".join(topic_keywords)
        if should_search:
            print(f"🔍 Memory search triggered for: [{kw_str}]")
            print(f"   Reason: {reason}")
        else:
            print(f"⏭️  Memory search skipped for: [{kw_str}]")
            print(f"   Reason: {reason}")
            return []
    elif not should_search:
        return []
    
    # Run the actual search using combined keywords as query
    query = " ".join(topic_keywords)
    return cmd_search(query, top_k=top_k)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    
    if cmd == "embed":
        cmd_embed()
    elif cmd == "search":
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if not query:
            print("Usage: python3 semantic_memory.py search 'your query'")
        else:
            cmd_search(query)
    elif cmd == "save":
        content = sys.argv[2] if len(sys.argv) > 2 else ""
        scope = sys.argv[3] if len(sys.argv) > 3 else "core"
        if not content:
            print("Usage: python3 semantic_memory.py save 'content' [scope]")
        else:
            cmd_save(content, scope)
    elif cmd == "relevant":
        # Usage: python3 semantic_memory.py relevant "keyword1,keyword2"
        raw = sys.argv[2] if len(sys.argv) > 2 else ""
        if not raw:
            print("Usage: python3 semantic_memory.py relevant 'keyword1,keyword2'")
            print("Example: python3 semantic_memory.py relevant 'autofint,pricing'")
        else:
            keywords = [k.strip() for k in raw.split(",") if k.strip()]
            search_if_relevant(keywords)
    else:
        print("Commands: embed | search 'query' | save 'content' [scope] | relevant 'kw1,kw2'")
