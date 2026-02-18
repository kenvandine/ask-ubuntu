#!/usr/bin/env python3
"""
RAG Indexer - Indexes Ubuntu documentation and man pages for retrieval
"""

import pickle
import subprocess
import time
from pathlib import Path
from typing import List, Tuple
import xml.etree.ElementTree as ET
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
        self.cache_dir = cache_dir or Path.home() / ".cache" / "ask-ubuntu"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.embed_model = embed_model
        self.client = OpenAI(base_url=base_url, api_key="lemonade")

        # Use model-specific cache paths to avoid dimension mismatches when
        # switching embedding models
        safe_name = embed_model.replace("/", "_").replace(":", "_")
        self.index_path = self.cache_dir / f"faiss_index_{safe_name}"
        self.docs_path = self.cache_dir / f"documents_{safe_name}.pkl"

        self.index = None
        self.documents: List[Document] = []

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
            batch = texts[i:i + EMBED_BATCH_SIZE]
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
            # Index man pages
            task = progress.add_task("Indexing man pages...", total=None)
            man_docs = self._index_man_pages()
            self.documents.extend(man_docs)
            progress.update(
                task, completed=True, description=f"Indexed {len(man_docs)} man pages"
            )

            # Index help files
            task = progress.add_task("Indexing help documentation...", total=None)
            help_docs = self._index_help_files()
            self.documents.extend(help_docs)
            progress.update(
                task, completed=True, description=f"Indexed {len(help_docs)} help files"
            )

            # Create embeddings via Lemonade
            task = progress.add_task(
                f"Creating embeddings for {len(self.documents)} documents...", total=None
            )
            texts = [doc.content for doc in self.documents]
            embeddings = self._embed(texts)
            progress.update(task, completed=True)

            # Build FAISS index
            task = progress.add_task("Building vector index...", total=None)
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension)
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings)
            progress.update(task, completed=True)

            # Save index
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
        """Index common man pages"""
        docs = []
        priority_commands = [
            "apt", "apt-get", "dpkg", "snap", "systemctl", "ufw", "ls", "cd", "grep",
            "find", "chmod", "chown", "sudo", "ssh", "scp", "tar", "wget", "curl",
            "docker", "git", "nano", "vim", "cat", "cp", "mv", "rm", "mkdir", "touch",
            "ps", "top", "kill", "df", "du", "free", "netstat", "ip", "ping",
        ]

        for cmd in priority_commands:
            try:
                result = subprocess.run(
                    ["man", cmd],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env={"MANWIDTH": "80"},
                )
                if result.returncode == 0:
                    content = result.stdout.strip()
                    if content:
                        docs.append(Document(
                            content=content[:MAX_DOC_CHARS],
                            source=f"man {cmd}",
                            title=cmd,
                        ))
            except Exception:
                pass

        return docs[:max_pages]

    def _index_help_files(self, max_files: int = 200) -> List[Document]:
        """Index Ubuntu help documentation"""
        docs = []
        help_base = Path("/usr/share/help")
        help_dirs = [help_base / "C", help_base / "en_GB"]

        for help_dir in help_dirs:
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

                    text_content = []
                    for elem in root.iter():
                        if elem.text:
                            text_content.append(elem.text.strip())
                        if elem.tail:
                            text_content.append(elem.tail.strip())

                    content = " ".join(filter(None, text_content))
                    if content:
                        docs.append(Document(
                            content=content[:MAX_DOC_CHARS],
                            source=str(page_file.relative_to(help_base)),
                            title=title,
                        ))
                except Exception:
                    pass

        return docs

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Document, float]]:
        """Search for relevant documents"""
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
