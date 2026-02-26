#!/usr/bin/env python3
"""
RAG Indexer - Indexes Ubuntu documentation and man pages for retrieval

Man-page resolution order
─────────────────────────
1. /usr/share/man/  (host files via system-packages-doc interface, fastest)
2. Disk cache       ($SNAP_USER_COMMON/cache/manpages/ or ~/.cache/ask-ubuntu/manpages/)
3. manpages.ubuntu.com  (fetched on first miss, then stored in the disk cache)

Help-file resolution order
──────────────────────────
1. /usr/share/help/ (host files via system-packages-doc interface)
2. Disk cache       ($SNAP_USER_COMMON/cache/helppages/ or ~/.cache/ask-ubuntu/helppages/)
3. help.ubuntu.com  (BFS crawl on first miss, then stored in disk cache)

Index/docs are cached in $SNAP_USER_COMMON/cache/ (or ~/.cache/ask-ubuntu/).
"""

import gzip
import os
import pickle
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET
import requests
from openai import OpenAI
import faiss
import numpy as np
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()

EMBED_BATCH_SIZE = 32
EMBED_MAX_RETRIES = 3
EMBED_RETRY_DELAY = 3  # seconds — gives Lemonade time to swap models
MAX_DOC_CHARS = 800    # nomic-embed-text-v1-GGUF context window ~512 tokens


# ── Snap-aware paths ───────────────────────────────────────────────────────────

def _snap_cache_dir() -> Path:
    """Return snap-aware cache directory ($SNAP_USER_COMMON/cache or ~/.cache/ask-ubuntu)."""
    snap_common = os.environ.get("SNAP_USER_COMMON")
    if snap_common:
        d = Path(snap_common) / "cache"
    else:
        d = Path.home() / ".cache" / "ask-ubuntu"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── nroff → plain text conversion ─────────────────────────────────────────────

def _nroff_to_text(nroff: str) -> str:
    """
    Convert nroff/troff man page source to readable plain text.
    Strips control lines and inline escape sequences.
    """
    result: List[str] = []
    for line in nroff.split("\n"):
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        # Control lines start with '.' or "'"
        if stripped[0] in (".", "'"):
            parts = stripped.split(None, 1)
            cmd = parts[0][1:]            # strip leading . or '
            rest = parts[1].strip('"') if len(parts) > 1 else ""
            if cmd in ("SH", "SS"):
                result.append(f"\n{rest}")
            elif cmd == "TH":
                title_parts = rest.split()
                if title_parts:
                    result.append(title_parts[0])
            elif cmd in ("PP", "LP", "P", "br", "sp", "TP", "IP"):
                result.append("")
            # other control lines are silently dropped
            continue

        # Regular text — strip inline nroff/groff escapes
        line = re.sub(r"\\f[BIPRW0-9]", "", line)    # font changes
        line = re.sub(r"\\s[+-]?\d*", "", line)        # size changes
        line = re.sub(r"\\\*\[.*?\]", "", line)         # string registers
        line = re.sub(r'\\-', "-", line)                # non-breaking hyphen
        line = re.sub(r'\\".*', "", line)               # groff comments
        line = re.sub(r"\\&", "", line)                 # zero-width non-print
        line = re.sub(r"\\.", "", line)                 # other escapes (catch-all)
        line = line.strip()
        if line:
            result.append(line)

    text = "\n".join(result)
    text = re.sub(r"\n{3,}", "\n\n", text)             # collapse excess blank lines
    return text.strip()


def _os_release_path() -> str:
    """Return the correct os-release path: host's when in a snap, otherwise /etc."""
    if os.environ.get("SNAP"):
        return "/var/lib/snapd/hostfs/etc/os-release"
    return "/etc/os-release"


def _ubuntu_codename() -> str:
    """Read the Ubuntu release codename from os-release."""
    try:
        with open(_os_release_path()) as f:
            for line in f:
                if line.startswith("VERSION_CODENAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "noble"   # safe default: Ubuntu 24.04 LTS


def _ubuntu_version_id() -> str:
    """Read VERSION_ID from os-release (e.g. '24.04'). Used for help.ubuntu.com URLs."""
    try:
        with open(_os_release_path()) as f:
            for line in f:
                if line.startswith("VERSION_ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return "lts"   # safe fallback — always available on help.ubuntu.com


# URL template for manpages.ubuntu.com — note the "manpages.gz" path prefix
_MANPAGES_URL = "https://manpages.ubuntu.com/manpages.gz/{codename}/man{section}/{cmd}.{section}.gz"

# URL base for help.ubuntu.com desktop guide
_HELP_BASE_URL = "https://help.ubuntu.com/{version}/ubuntu-help"
_HELP_FALLBACK_VERSION = "lts"   # Ubuntu LTS page — always available


def _fetch_man_page_online(cmd: str, codename: str) -> Optional[str]:
    """
    Download a man page from manpages.ubuntu.com and return plain text.
    Tries sections 1, 8, 6, 5, 4, 3, 2, 7 in order (most common first).
    If the running release isn't published yet, falls back to the previous
    LTS (noble / 24.04).
    Returns None if the page cannot be fetched for any reason.
    """
    _FALLBACK_CODENAME = "noble"   # Ubuntu 24.04 LTS — always available

    for release in dict.fromkeys((codename, _FALLBACK_CODENAME)):  # deduplicate
        for section in ("1", "8", "6", "5", "4", "3", "2", "7"):
            url = _MANPAGES_URL.format(codename=release, section=section, cmd=cmd)
            try:
                response = requests.get(url, timeout=10,
                                        headers={"User-Agent": "ask-ubuntu/1.0"})
                if response.status_code != 200:
                    continue
                raw = gzip.decompress(response.content).decode("utf-8", errors="ignore")
                text = _nroff_to_text(raw)
                if text and text.strip():
                    return text
            except Exception:
                pass
    return None


def _html_to_text(html: str) -> str:
    """
    Extract plain text from an Ubuntu help HTML page.
    Strips navigation chrome and collects heading/paragraph/list content
    that appears after the first <h1> tag (where real content begins).
    """
    # Remove script and style blocks wholesale
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'\s+', ' ', html)   # collapse all whitespace to single spaces

    # Skip everything before the first <h1> (nav bar, breadcrumbs, etc.)
    m = re.search(r'<h1[\s>]', html, re.IGNORECASE)
    if m:
        html = html[m.start():]

    # Extract text from content tags in document order
    parts: List[str] = []
    for m in re.finditer(r'<(h[1-3]|p|li)(?:\s[^>]*)?>(.+?)</\1>', html,
                         re.IGNORECASE | re.DOTALL):
        inner = re.sub(r'<[^>]+>', ' ', m.group(2))
        text = re.sub(r'\s+', ' ', inner).strip()
        if text and len(text) > 5:
            # Stop before footer / license boilerplate
            if any(s in text.lower() for s in ('material in this document', 'creative commons')):
                break
            parts.append(text)

    return '\n'.join(parts).strip()


def _fetch_help_page_online(slug: str, version: str) -> Optional[str]:
    """
    Download a single Ubuntu help page and return plain text.
    Falls back to 'lts' if the requested version is not published yet.
    Returns None if the page cannot be fetched for any reason.
    """
    for ver in dict.fromkeys((version, _HELP_FALLBACK_VERSION)):
        url = f"{_HELP_BASE_URL.format(version=ver)}/{slug}.html.en"
        try:
            response = requests.get(url, timeout=10,
                                    headers={"User-Agent": "ask-ubuntu/1.0"})
            if response.status_code != 200:
                continue
            text = _html_to_text(response.text)
            if text and text.strip():
                return text
        except Exception:
            pass
    return None


def _probe_man_read(man_base: Path) -> None:
    """
    Try to open (not just stat) the first regular file found under man_base.
    Raises PermissionError if file reads are blocked by AppArmor even though
    directory listing is permitted.
    """
    for subdir in man_base.iterdir():
        if not subdir.is_dir():
            continue
        for entry in subdir.iterdir():
            if entry.is_file():
                entry.open("rb").close()   # raises PermissionError if blocked
                return                     # success — at least one file is readable
    # No files found (empty tree) — not a permission issue, just return


def _read_man_page(man_base: Path, cmd: str) -> Optional[str]:
    """
    Read a man page directly from /usr/share/man/ and return plain text.
    Tries sections 1, 8, 6, 5, 4, 3, 2, 7 in order.
    Handles both gzip-compressed (.gz) and uncompressed files.
    """
    for section in ("1", "8", "6", "5", "4", "3", "2", "7"):
        candidates = [
            man_base / f"man{section}" / f"{cmd}.{section}.gz",
            man_base / f"man{section}" / f"{cmd}.{section}",
            man_base / f"man{section}" / f"{cmd}.gz",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                if path.suffix == ".gz":
                    with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
                        raw = f.read()
                else:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        raw = f.read()
                text = _nroff_to_text(raw)
                if text:
                    return text
            except PermissionError:
                raise   # propagate so caller can warn and abort
            except Exception:
                pass    # bad format, encoding issues etc. — try next candidate
    return None


class Document:
    """Represents a documentation chunk"""
    def __init__(self, content: str, source: str, title: str = ""):
        self.content = content
        self.source = source
        self.title = title

    def __repr__(self):
        return f"Document(title={self.title}, source={self.source})"


class RAGIndexer:
    """Indexes and retrieves Ubuntu documentation"""

    def __init__(
        self,
        cache_dir: Path = None,
        base_url: str = "http://localhost:8000/api/v1",
        embed_model: str = "nomic-embed-text-v1-GGUF",
    ):
        self.cache_dir = cache_dir or _snap_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model
        self.client = OpenAI(base_url=base_url, api_key="lemonade")

        safe_name = embed_model.replace("/", "_").replace(":", "_")
        self.index_path  = self.cache_dir / f"faiss_index_{safe_name}"
        self.docs_path   = self.cache_dir / f"documents_{safe_name}.pkl"
        self.manpage_dir  = self.cache_dir / "manpages"   # disk cache for downloaded man pages
        self.helppage_dir = self.cache_dir / "helppages"  # disk cache for downloaded help pages

        self.codename       = _ubuntu_codename()    # e.g. "noble"   — used for manpages.ubuntu.com
        self.ubuntu_version = _ubuntu_version_id()  # e.g. "24.04"   — used for help.ubuntu.com
        self.index = None
        self.documents: List[Document] = []

    def _load_cached_manpage(self, cmd: str) -> Optional[str]:
        """
        Return previously downloaded man page text, or None if not cached.
        An empty .txt file is a negative-cache sentinel (no page exists online).
        """
        path = self.manpage_dir / f"{cmd}.txt"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                return text if text else None   # empty = known miss
            except Exception:
                pass
        return None

    def _is_cached_manpage(self, cmd: str) -> bool:
        """Return True if this command has already been looked up (hit or miss)."""
        return (self.manpage_dir / f"{cmd}.txt").exists()

    def _save_cached_manpage(self, cmd: str, content: Optional[str]) -> None:
        """
        Persist a downloaded man page to disk.
        Pass content=None to write a negative-cache sentinel (empty file).
        """
        try:
            self.manpage_dir.mkdir(parents=True, exist_ok=True)
            path = self.manpage_dir / f"{cmd}.txt"
            path.write_text(content or "", encoding="utf-8")
        except Exception:
            pass

    # ── Help-page disk cache ───────────────────────────────────────────────────

    def _is_cached_helppage(self, slug: str) -> bool:
        """Return True if this help page slug has been looked up before (hit or miss)."""
        return (self.helppage_dir / f"{slug}.txt").exists()

    def _load_cached_helppage(self, slug: str) -> Optional[str]:
        """
        Return previously cached help page text, or None if not cached.
        An empty .txt file is a negative-cache sentinel (page doesn't exist online).
        """
        path = self.helppage_dir / f"{slug}.txt"
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8")
                return text if text else None   # empty = known miss
            except Exception:
                pass
        return None

    def _save_cached_helppage(self, slug: str, content: Optional[str]) -> None:
        """
        Persist a downloaded help page to disk.
        Pass content=None to write a negative-cache sentinel (empty file).
        """
        try:
            self.helppage_dir.mkdir(parents=True, exist_ok=True)
            (self.helppage_dir / f"{slug}.txt").write_text(content or "", encoding="utf-8")
        except Exception:
            pass

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        """Embed a single batch with retries to handle model swap delay."""
        last_exc = None
        for attempt in range(EMBED_MAX_RETRIES):
            try:
                response = self.client.embeddings.create(
                    model=self.embed_model, input=batch, timeout=30
                )
                if not response.data:
                    raise ValueError("Empty embeddings response from Lemonade")
                return [item.embedding for item in response.data]
            except Exception as e:
                last_exc = e
                if attempt < EMBED_MAX_RETRIES - 1:
                    time.sleep(EMBED_RETRY_DELAY)
        raise last_exc

    def _embed(self, texts: List[str]) -> np.ndarray:
        """Get embeddings from Lemonade in batches."""
        all_embeddings = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            all_embeddings.extend(self._embed_batch(batch))
        return np.array(all_embeddings, dtype="float32")

    def load_or_create_index(self) -> bool:
        """Load existing index or create new one"""
        if self.index_path.exists() and self.docs_path.exists():
            console.print("📚 Loading existing documentation index...", style="#E95420")
            try:
                self.index = faiss.read_index(str(self.index_path))
                with open(self.docs_path, "rb") as f:
                    self.documents = pickle.load(f)
                console.print(f"✓ Loaded {len(self.documents)} documents", style="green")
                return True
            except Exception as e:
                console.print(f"⚠️  Failed to load index: {e}", style="yellow")
                console.print("   Creating new index...", style="yellow")

        return self.create_index()

    def create_index(self) -> bool:
        """Create a new documentation index"""
        console.print("\n🔨 Building documentation index...", style="#E95420 bold")
        console.print("   This may take a few minutes on first run.\n", style="yellow")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Indexing man pages...", total=None)
            man_docs = self._index_man_pages()
            self.documents.extend(man_docs)
            progress.update(
                task, completed=True, description=f"Indexed {len(man_docs)} man pages"
            )

            task = progress.add_task("Indexing help documentation...", total=None)
            help_docs = self._index_help_files()
            self.documents.extend(help_docs)
            progress.update(
                task, completed=True, description=f"Indexed {len(help_docs)} help files"
            )

            if not self.documents:
                console.print(
                    "⚠️  No documents indexed — RAG disabled. "
                    "Check network access to manpages.ubuntu.com or connect "
                    "system-packages-doc for local man pages.",
                    style="yellow",
                )
                return False

            task = progress.add_task(
                f"Creating embeddings for {len(self.documents)} documents...", total=None
            )
            texts = [doc.content for doc in self.documents]
            embeddings = self._embed(texts)
            progress.update(task, completed=True)

            task = progress.add_task("Building vector index...", total=None)
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension)
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings)
            progress.update(task, completed=True)

            task = progress.add_task("Saving index to disk...", total=None)
            faiss.write_index(self.index, str(self.index_path))
            with open(self.docs_path, "wb") as f:
                pickle.dump(self.documents, f)
            progress.update(task, completed=True)

        console.print(
            f"\n✓ Index created with {len(self.documents)} documents!", style="green bold"
        )
        return True

    def _index_man_pages(self, max_pages: int = 500) -> List[Document]:
        """
        Index man pages using a three-tier lookup:
          1. /usr/share/man/ via system-packages-doc interface (fastest, always current)
          2. Disk cache     ($SNAP_USER_COMMON/cache/manpages/) from a prior download
          3. manpages.ubuntu.com (fetched once, then stored in the disk cache)

        When local man pages are readable, all available pages in sections 1 and 8
        are enumerated (beyond the priority list) up to max_pages.
        """
        docs: List[Document] = []
        priority_commands = [
            "apt", "apt-get", "dpkg", "snap", "systemctl", "ufw", "ls", "cd", "grep",
            "find", "chmod", "chown", "sudo", "ssh", "scp", "tar", "wget", "curl",
            "docker", "git", "nano", "vim", "cat", "cp", "mv", "rm", "mkdir", "touch",
            "ps", "top", "kill", "df", "du", "free", "netstat", "ip", "ping",
        ]

        # Determine whether local /usr/share/man/ files are readable.
        man_base = Path("/usr/share/man")
        local_readable = False
        if man_base.exists():
            try:
                _probe_man_read(man_base)
                local_readable = True
                console.print(
                    "✓ Using local man pages from /usr/share/man",
                    style="dim green",
                )
            except PermissionError:
                console.print(
                    "⚠️  /usr/share/man not readable via system-packages-doc — "
                    "falling back to disk cache / manpages.ubuntu.com",
                    style="dim yellow",
                )

        processed: set = set()

        for cmd in priority_commands:
            if len(docs) >= max_pages:
                break
            processed.add(cmd)

            content: Optional[str] = None

            # ── Tier 1: local filesystem ──────────────────────────────────────
            if local_readable:
                try:
                    content = _read_man_page(man_base, cmd)
                except PermissionError:
                    local_readable = False   # stop trying for subsequent commands
                except Exception:
                    pass

            # ── Tier 2: disk cache (previously downloaded) ────────────────────
            if not content:
                content = self._load_cached_manpage(cmd)

            # ── Tier 3: fetch from manpages.ubuntu.com (skip if sentinel exists) ──
            if not content and not self._is_cached_manpage(cmd):
                content = _fetch_man_page_online(cmd, self.codename)
                self._save_cached_manpage(cmd, content)  # None → empty sentinel

            if content and content.strip():
                docs.append(Document(
                    content=content[:MAX_DOC_CHARS],
                    source=f"man {cmd}",
                    title=cmd,
                ))

        # ── Bonus: enumerate additional local man pages beyond priority list ──
        # When local /usr/share/man is accessible (system-packages-doc connected
        # or running outside a snap), index all installed section 1 and 8 pages.
        if local_readable and len(docs) < max_pages:
            for section in ("1", "8"):
                section_dir = man_base / f"man{section}"
                if not section_dir.is_dir():
                    continue
                for man_file in sorted(section_dir.iterdir()):
                    if len(docs) >= max_pages:
                        break
                    # Derive the command name from the filename
                    name = man_file.name
                    cmd = None
                    for suffix in (f".{section}.gz", f".{section}", ".gz"):
                        if name.endswith(suffix):
                            cmd = name[: -len(suffix)]
                            break
                    if not cmd or cmd in processed:
                        continue
                    processed.add(cmd)
                    try:
                        content = _read_man_page(man_base, cmd)
                        if content and content.strip():
                            docs.append(Document(
                                content=content[:MAX_DOC_CHARS],
                                source=f"man {cmd}",
                                title=cmd,
                            ))
                    except PermissionError:
                        local_readable = False
                        break
                    except Exception:
                        pass

        return docs

    def _index_help_files(self, max_files: int = 200) -> List[Document]:
        """
        Index Ubuntu desktop help documentation using a three-tier lookup:
          1. /usr/share/help/ via system-packages-doc interface (Mallard XML .page files)
          2. Disk cache     ($SNAP_USER_COMMON/cache/helppages/)
          3. help.ubuntu.com (BFS crawl on first run; results cached to disk)

        The first run performs a BFS crawl of help.ubuntu.com starting from
        index.html.en, discovering and caching every linked page.  A slug list
        (_slugs.txt) is saved so subsequent runs read entirely from disk.
        """
        docs: List[Document] = []
        help_base = Path("/usr/share/help")
        local_readable = False

        if help_base.exists():
            try:
                _probe_man_read(help_base)
                local_readable = True
                console.print(
                    "✓ Using local help files from /usr/share/help",
                    style="dim green",
                )
            except PermissionError:
                console.print(
                    "⚠️  /usr/share/help not readable via system-packages-doc — "
                    "falling back to help.ubuntu.com",
                    style="dim yellow",
                )

        # ── Tier 1: local Mallard .page files ────────────────────────────────
        # Try the user's locale, then C (English) and en_GB as fallbacks.
        if local_readable:
            lang = (
                os.environ.get("LANGUAGE", "").split(":")[0]
                or os.environ.get("LANG", "").split(".")[0]
                or ""
            )
            # Build an ordered list of locale dirs to try, deduplicating
            locale_dirs: list = []
            for loc in dict.fromkeys((lang, lang.split("_")[0] if "_" in lang else "", "C", "en_GB")):
                if loc:
                    locale_dirs.append(help_base / loc)

            for help_dir in locale_dirs:
                if not help_dir.exists():
                    continue
                for page_file in help_dir.rglob("*.page"):
                    if len(docs) >= max_files:
                        break
                    try:
                        tree = ET.parse(page_file)
                        root = tree.getroot()
                        title_elem = root.find(".//{http://projectmallard.org/1.0/}title")
                        title = title_elem.text if title_elem is not None else page_file.stem
                        text_parts: List[str] = []
                        for elem in root.iter():
                            if elem.text:
                                text_parts.append(elem.text.strip())
                            if elem.tail:
                                text_parts.append(elem.tail.strip())
                        content = " ".join(filter(None, text_parts))
                        if content:
                            docs.append(Document(
                                content=content[:MAX_DOC_CHARS],
                                source=str(page_file.relative_to(help_base)),
                                title=title,
                            ))
                    except Exception:
                        pass
            if docs:
                return docs   # local files available and non-empty — done

        # ── Tiers 2 & 3: disk cache / help.ubuntu.com ────────────────────────
        console.print(
            "ℹ  Fetching help pages from help.ubuntu.com...",
            style="dim yellow",
        )
        slug_list_path = self.helppage_dir / "_slugs.txt"

        if slug_list_path.exists():
            # Subsequent runs: slug list already discovered; just serve from cache
            # (or re-fetch individual pages that somehow slipped through).
            try:
                slugs = [s for s in
                         slug_list_path.read_text(encoding="utf-8").splitlines()
                         if s.strip()]
            except Exception:
                slugs = []
            for slug in slugs:
                if len(docs) >= max_files:
                    break
                content = self._load_cached_helppage(slug)
                if not content and not self._is_cached_helppage(slug):
                    content = _fetch_help_page_online(slug, self.ubuntu_version)
                    self._save_cached_helppage(slug, content)
                if content and content.strip():
                    title = content.split('\n', 1)[0].strip() or slug.replace('-', ' ').title()
                    docs.append(Document(
                        content=content[:MAX_DOC_CHARS],
                        source=f"ubuntu-help/{slug}",
                        title=title,
                    ))
        else:
            # First run: BFS crawl starting from index.html.en.
            # Find a working base URL (specific version → LTS fallback).
            base_url: Optional[str] = None
            seed_html: str = ""
            for ver in dict.fromkeys((self.ubuntu_version, _HELP_FALLBACK_VERSION)):
                probe_url = f"{_HELP_BASE_URL.format(version=ver)}/index.html.en"
                try:
                    r = requests.get(probe_url, timeout=15,
                                     headers={"User-Agent": "ask-ubuntu/1.0"})
                    if r.status_code == 200:
                        base_url = _HELP_BASE_URL.format(version=ver)
                        seed_html = r.text
                        break
                except Exception:
                    pass

            if base_url is None:
                console.print("⚠️  Cannot reach help.ubuntu.com", style="yellow")
                return docs

            # Seed the BFS queue from links on the index page.
            def _extract_slugs(html: str) -> List[str]:
                return list(dict.fromkeys(
                    m.replace('.html.en', '')
                    for m in re.findall(r'href="([a-z][a-z0-9-]*\.html\.en)"', html)
                    if m != 'index.html.en'
                ))

            queue: List[str] = _extract_slugs(seed_html)
            seen: set = set(queue) | {'index'}
            all_discovered: List[str] = list(queue)

            while queue and len(docs) < max_files:
                slug = queue.pop(0)
                content = None
                try:
                    r = requests.get(
                        f"{base_url}/{slug}.html.en", timeout=10,
                        headers={"User-Agent": "ask-ubuntu/1.0"},
                    )
                    if r.status_code == 200:
                        content = _html_to_text(r.text)
                        # Expand BFS: discover sub-links on this page
                        for sub in _extract_slugs(r.text):
                            if sub not in seen:
                                seen.add(sub)
                                queue.append(sub)
                                all_discovered.append(sub)
                except Exception:
                    pass

                self._save_cached_helppage(slug, content)   # None → sentinel

                if content and content.strip():
                    title = content.split('\n', 1)[0].strip() or slug.replace('-', ' ').title()
                    docs.append(Document(
                        content=content[:MAX_DOC_CHARS],
                        source=f"ubuntu-help/{slug}",
                        title=title,
                    ))

            # Persist slug list so future runs skip the crawl entirely.
            try:
                self.helppage_dir.mkdir(parents=True, exist_ok=True)
                slug_list_path.write_text('\n'.join(all_discovered), encoding="utf-8")
            except Exception:
                pass

        return docs

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Document, float]]:
        """Search for relevant documents"""
        if self.index is None:
            return []
        query_embedding = self._embed([query])
        faiss.normalize_L2(query_embedding)
        scores, indices = self.index.search(query_embedding, top_k)

        results = []
        for idx, score in zip(indices[0], scores[0]):
            if idx < len(self.documents):
                results.append((self.documents[idx], float(score)))

        return results


def main():
    """Test the indexer"""
    indexer = RAGIndexer()
    indexer.load_or_create_index()

    query = "How do I install a package?"
    console.print(f"\n🔍 Searching for: '{query}'", style="#E95420")
    results = indexer.search(query, top_k=3)

    for doc, score in results:
        console.print(f"\n📄 {doc.title} (score: {score:.3f})", style="green")
        console.print(f"   Source: {doc.source}", style="dim")
        console.print(f"   Content: {doc.content[:200]}...", style="white")


if __name__ == "__main__":
    main()
