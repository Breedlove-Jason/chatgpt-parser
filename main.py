#!/usr/bin/env python3
"""
ChatGPT Vault Search
- Parses ChatGPT export ZIP or extracted folder.
- Searches conversations and messages for keywords/regex.
- Exports results to JSON/MD/TXT.
- Optionally extracts code blocks to files.

Works with common ChatGPT export layouts containing conversations.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from tqdm import tqdm
except Exception:
    tqdm = None  # fallback: no progress bar


# -----------------------------
# Models
# -----------------------------
@dataclass
class MatchHit:
    conversation_id: str
    conversation_title: str
    conversation_create_time: Optional[str]
    message_id: str
    author_role: str
    message_time: Optional[str]
    snippet: str
    full_text: str
    code_blocks: List[Dict[str, str]]  # [{"language": "...", "code": "..."}]


# -----------------------------
# Helpers
# -----------------------------
def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def iso_from_unix(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return None


def safe_filename(s: str, max_len: int = 90) -> str:
    s = s.strip().replace("/", "_").replace("\\", "_")
    s = re.sub(r"[^a-zA-Z0-9._ -]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        s = "untitled"
    return s[:max_len]


def find_conversations_json_in_folder(folder: str) -> Optional[str]:
    # Typical export: <folder>/conversations.json
    direct = os.path.join(folder, "conversations.json")
    if os.path.isfile(direct):
        return direct

    # Some exports might have nested folders; do a small walk.
    for root, _, files in os.walk(folder):
        if "conversations.json" in files:
            return os.path.join(root, "conversations.json")
    return None


def load_conversations_from_zip(zip_path: str) -> List[Dict[str, Any]]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find conversations.json anywhere inside the zip
        candidates = [n for n in zf.namelist() if n.endswith("conversations.json")]
        if not candidates:
            raise FileNotFoundError("Could not find conversations.json inside the ZIP.")
        # Prefer the shortest path (closest to root)
        candidates.sort(key=lambda x: (x.count("/"), len(x)))
        target = candidates[0]
        with zf.open(target) as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("conversations.json format not recognized (expected a list).")
            return data


def load_conversations(input_path: str) -> List[Dict[str, Any]]:
    if os.path.isfile(input_path) and input_path.lower().endswith(".zip"):
        return load_conversations_from_zip(input_path)

    if os.path.isdir(input_path):
        cj = find_conversations_json_in_folder(input_path)
        if not cj:
            raise FileNotFoundError("Could not find conversations.json in the folder.")
        with open(cj, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("conversations.json format not recognized (expected a list).")
            return data

    # Also accept direct path to conversations.json
    if os.path.isfile(input_path) and os.path.basename(input_path) == "conversations.json":
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("conversations.json format not recognized (expected a list).")
            return data

    raise FileNotFoundError("Input must be a ChatGPT export ZIP, folder, or conversations.json file.")


def iter_messages(conv: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """
    ChatGPT export often stores messages in conv["mapping"] where each node has:
      - "id"
      - "message": { "id", "author": {"role"}, "content": {"parts":[...]}, "create_time": ... }
    """
    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if isinstance(msg, dict):
            yield node_id, msg


def message_text(msg: Dict[str, Any]) -> str:
    content = msg.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    # parts can include strings or other structures; keep strings
    out: List[str] = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
        else:
            # Sometimes structured parts appear; attempt a safe stringify
            try:
                out.append(json.dumps(p, ensure_ascii=False))
            except Exception:
                out.append(str(p))
    return "\n".join(out).strip()


CODE_FENCE_RE = re.compile(
    r"```(?P<lang>[a-zA-Z0-9_+-]*)\n(?P<code>.*?)\n```",
    re.DOTALL,
)


def extract_code_blocks(text: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    for m in CODE_FENCE_RE.finditer(text):
        lang = (m.group("lang") or "").strip() or "text"
        code = m.group("code")
        blocks.append({"language": lang, "code": code})
    return blocks


def make_snippet(text: str, max_len: int = 240) -> str:
    one = re.sub(r"\s+", " ", text).strip()
    if len(one) <= max_len:
        return one
    return one[: max_len - 1] + "…"


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    # Accept YYYY-MM-DD or ISO
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str.strip()):
            return datetime.fromisoformat(date_str.strip()).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(date_str.strip()).astimezone(timezone.utc)
    except Exception:
        return None


def in_date_range(ts_iso: Optional[str], start: Optional[datetime], end: Optional[datetime]) -> bool:
    if not start and not end:
        return True
    if not ts_iso:
        # If unknown timestamp, include it unless user is strict? We'll include it.
        return True
    try:
        t = datetime.fromisoformat(ts_iso).astimezone(timezone.utc)
    except Exception:
        return True
    if start and t < start:
        return False
    if end and t > end:
        return False
    return True


# -----------------------------
# Search Engine
# -----------------------------
def compile_query(query: str, regex: bool, case_sensitive: bool) -> re.Pattern:
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        return re.compile(query, flags=flags)
    # Escape plain text
    return re.compile(re.escape(query), flags=flags)


def search_export(
        conversations: List[Dict[str, Any]],
        query_pat: re.Pattern,
        search_titles: bool,
        search_messages: bool,
        title_filter: Optional[re.Pattern],
        only_with_code: bool,
        start: Optional[datetime],
        end: Optional[datetime],
) -> List[MatchHit]:
    hits: List[MatchHit] = []

    iterator = conversations
    if tqdm is not None:
        iterator = tqdm(conversations, desc="Scanning conversations", unit="conv")

    for conv in iterator:
        conv_id = str(conv.get("id", ""))
        title = str(conv.get("title", "") or "")
        conv_time = iso_from_unix(conv.get("create_time")) if isinstance(conv.get("create_time"), (int, float)) else None

        if title_filter and not title_filter.search(title):
            continue

        # Optional early title match (as a conversation-level hint)
        title_matched = bool(search_titles and query_pat.search(title))

        if search_messages:
            for node_id, msg in iter_messages(conv):
                mid = str(msg.get("id", node_id))
                role = ""
                author = msg.get("author")
                if isinstance(author, dict):
                    role = str(author.get("role", "") or "")
                ts_iso = iso_from_unix(msg.get("create_time")) if isinstance(msg.get("create_time"), (int, float)) else None

                if not in_date_range(ts_iso, start, end):
                    continue

                text = message_text(msg)
                if not text:
                    continue

                text_matched = bool(query_pat.search(text))
                if not (text_matched or title_matched):
                    continue

                blocks = extract_code_blocks(text)
                if only_with_code and not blocks:
                    continue

                hits.append(
                    MatchHit(
                        conversation_id=conv_id,
                        conversation_title=title,
                        conversation_create_time=conv_time,
                        message_id=mid,
                        author_role=role,
                        message_time=ts_iso,
                        snippet=make_snippet(text),
                        full_text=text,
                        code_blocks=blocks,
                    )
                )
        else:
            # Title-only mode
            if title_matched:
                # Create a synthetic hit with no message context
                hits.append(
                    MatchHit(
                        conversation_id=conv_id,
                        conversation_title=title,
                        conversation_create_time=conv_time,
                        message_id="",
                        author_role="",
                        message_time=None,
                        snippet="(title match)",
                        full_text="",
                        code_blocks=[],
                    )
                )

    return hits


# -----------------------------
# Exporters
# -----------------------------
def export_json(hits: List[MatchHit], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(h) for h in hits], f, ensure_ascii=False, indent=2)


def export_txt(hits: List[MatchHit], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, h in enumerate(hits, 1):
            f.write(f"[{i}] {h.conversation_title}\n")
            f.write(f"  conv_id: {h.conversation_id}\n")
            if h.conversation_create_time:
                f.write(f"  conv_time: {h.conversation_create_time}\n")
            if h.message_id:
                f.write(f"  msg_id: {h.message_id} role={h.author_role} time={h.message_time}\n")
                f.write(f"  snippet: {h.snippet}\n")
            f.write("\n")


def export_md(hits: List[MatchHit], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# ChatGPT Vault Search Results\n\n")
        for i, h in enumerate(hits, 1):
            f.write(f"## {i}. {h.conversation_title}\n\n")
            f.write(f"- **Conversation ID:** `{h.conversation_id}`\n")
            if h.conversation_create_time:
                f.write(f"- **Conversation Created:** `{h.conversation_create_time}`\n")
            if h.message_id:
                f.write(f"- **Message ID:** `{h.message_id}`\n")
                f.write(f"- **Author Role:** `{h.author_role}`\n")
                if h.message_time:
                    f.write(f"- **Message Time:** `{h.message_time}`\n")
            f.write("\n")
            if h.full_text:
                f.write("### Matched Message\n\n")
                # Keep it readable
                f.write("```text\n")
                f.write(h.full_text.strip())
                f.write("\n```\n\n")
            if h.code_blocks:
                f.write("### Code Blocks Found\n\n")
                for j, b in enumerate(h.code_blocks, 1):
                    lang = b.get("language", "text")
                    code = b.get("code", "")
                    f.write(f"**Block {j}** ({lang})\n\n")
                    f.write(f"```{lang}\n{code}\n```\n\n")


def extract_code_to_dir(hits: List[MatchHit], code_dir: str) -> int:
    os.makedirs(code_dir, exist_ok=True)
    count = 0
    for h in hits:
        if not h.code_blocks:
            continue
        base = safe_filename(h.conversation_title) + f"__{h.conversation_id[:8]}"
        for idx, b in enumerate(h.code_blocks, 1):
            lang = (b.get("language") or "text").strip()
            ext = {
                "python": "py",
                "py": "py",
                "javascript": "js",
                "js": "js",
                "typescript": "ts",
                "ts": "ts",
                "json": "json",
                "bash": "sh",
                "sh": "sh",
                "zsh": "sh",
                "html": "html",
                "css": "css",
                "sql": "sql",
                "yaml": "yml",
                "yml": "yml",
                "md": "md",
                "markdown": "md",
            }.get(lang.lower(), "txt")

            filename = f"{base}__msg_{h.message_id[:8] if h.message_id else 'nomsg'}__{idx}.{ext}"
            path = os.path.join(code_dir, filename)
            with open(path, "w", encoding="utf-8") as f:
                f.write(b.get("code", ""))
            count += 1
    return count


# -----------------------------
# CLI
# -----------------------------
def cmd_search(args: argparse.Namespace) -> int:
    conversations = load_conversations(args.input)

    query_pat = compile_query(args.query, regex=args.regex, case_sensitive=args.case_sensitive)
    title_filter = compile_query(args.title_contains, regex=False, case_sensitive=False) if args.title_contains else None

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)

    hits = search_export(
        conversations=conversations,
        query_pat=query_pat,
        search_titles=not args.no_titles,
        search_messages=not args.no_messages,
        title_filter=title_filter,
        only_with_code=args.only_with_code,
        start=start,
        end=end,
    )

    # Sort: best-effort by timestamp descending if present, otherwise stable
    def sort_key(h: MatchHit):
        try:
            return datetime.fromisoformat(h.message_time).timestamp() if h.message_time else -1
        except Exception:
            return -1

    hits.sort(key=sort_key, reverse=True)

    # Print summary + top previews
    print(f"\nFound {len(hits)} match(es).\n")
    preview_n = min(args.preview, len(hits))
    for i in range(preview_n):
        h = hits[i]
        when = h.message_time or h.conversation_create_time or "unknown-time"
        who = h.author_role or "unknown-role"
        print(f"[{i+1}] {h.conversation_title}  ({when}, {who})")
        print(f"     conv_id={h.conversation_id} msg_id={h.message_id}")
        print(f"     {h.snippet}\n")

    if args.export:
        fmt = args.format.lower()
        if fmt == "json":
            export_json(hits, args.export)
        elif fmt == "md":
            export_md(hits, args.export)
        elif fmt == "txt":
            export_txt(hits, args.export)
        else:
            raise ValueError("Unsupported export format. Use: json, md, txt")
        print(f"Exported results to: {args.export}")

    if args.extract_code:
        code_dir = args.code_dir or "recovered_code"
        n = extract_code_to_dir(hits, code_dir)
        print(f"Extracted {n} code block file(s) into: {code_dir}")

    # Optional: dump a chosen match to stdout fully
    if args.show:
        idx = args.show - 1
        if 0 <= idx < len(hits):
            h = hits[idx]
            print("\n" + "=" * 80)
            print(f"FULL MESSAGE [{args.show}] - {h.conversation_title}")
            print("=" * 80 + "\n")
            print(h.full_text)
            print("\n" + "=" * 80)

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chatgpt_vault_search",
        description="Search and recover content from a ChatGPT data export (ZIP/folder).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              python chatgpt_vault_search.py export.zip search "safe date"
              python chatgpt_vault_search.py export.zip search "safe.*date" --regex
              python chatgpt_vault_search.py export.zip search "safe date program" --export out.md --format md --extract-code
            """
        ),
    )
    p.add_argument("input", help="Path to ChatGPT export ZIP, extracted folder, or conversations.json")

    sub = p.add_subparsers(dest="cmd", required=False)

    s = sub.add_parser("search", help="Search titles/messages for a query.")
    s.add_argument("query", help="Search query (plain text by default; use --regex for regex).")

    s.add_argument("--regex", action="store_true", help="Treat query as regex.")
    s.add_argument("--case-sensitive", action="store_true", help="Case-sensitive matching.")

    s.add_argument("--no-titles", action="store_true", help="Do not search conversation titles.")
    s.add_argument("--no-messages", action="store_true", help="Do not search message bodies.")

    s.add_argument("--title-contains", default=None, help="Filter conversations where title contains this (plain text).")
    s.add_argument("--only-with-code", action="store_true", help="Only return hits that contain fenced code blocks.")

    s.add_argument("--start-date", default=None, help="Filter messages after this date (YYYY-MM-DD or ISO).")
    s.add_argument("--end-date", default=None, help="Filter messages before this date (YYYY-MM-DD or ISO).")

    s.add_argument("--preview", type=int, default=10, help="How many hits to preview in terminal (default: 10).")
    s.add_argument("--show", type=int, default=None, help="Print the full text of hit N to stdout.")

    s.add_argument("--export", default=None, help="Export hits to a file.")
    s.add_argument("--format", default="md", choices=["md", "json", "txt"], help="Export format (default: md).")

    s.add_argument("--extract-code", action="store_true", help="Extract fenced code blocks into files.")
    s.add_argument("--code-dir", default=None, help="Directory for extracted code (default: recovered_code).")

    s.set_defaults(func=cmd_search)
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        eprint("\nInterrupted.")
        return 130
    except Exception as ex:
        eprint(f"\nError: {ex}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())