#!/usr/bin/env python3
"""
RAG Indexer - Indexes Ubuntu documentation and man pages for retrieval
"""

import gzip
import pickle
import subprocess
import os
import sys
import warnings
from pathlib import Path
from typing import List, Dict, Tuple
from contextlib import contextmanager
import xml.etree.ElementTree as ET
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

# Suppress all warnings and model loading output
warnings.filterwarnings('ignore')
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

console = Console()

@contextmanager
def suppress_output():
    """Suppress stdout and stderr"""
    with open(os.devnull, 'w') as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


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

    def __init__(self, cache_dir: Path = None):
        self.cache_dir = cache_dir or Path.home() / ".cache" / "ubuntu-help"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "faiss_index"
        self.docs_path = self.cache_dir / "documents.pkl"
        self.model = None
        self.index = None
        self.documents: List[Document] = []

    def load_or_create_index(self) -> bool:
        """Load existing index or create new one"""
        if self.index_path.exists() and self.docs_path.exists():
            console.print("📚 Loading existing documentation index...", style="cyan")
            try:
                self.index = faiss.read_index(str(self.index_path))
                with open(self.docs_path, 'rb') as f:
                    self.documents = pickle.load(f)
                console.print(f"✓ Loaded {len(self.documents)} documents", style="green")
                return True
            except Exception as e:
                console.print(f"⚠️  Failed to load index: {e}", style="yellow")
                console.print("   Creating new index...", style="yellow")

        # Create new index
        return self.create_index()

    def create_index(self) -> bool:
        """Create a new documentation index"""
        console.print("\n🔨 Building documentation index...", style="cyan bold")
        console.print("   This may take a few minutes on first run.\n", style="yellow")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            # Load embedding model
            task = progress.add_task("Loading embedding model...", total=None)
            import logging
            logging.getLogger('sentence_transformers').setLevel(logging.ERROR)
            with suppress_output():
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
            progress.update(task, completed=True)

            # Index man pages
            task = progress.add_task("Indexing man pages...", total=None)
            man_docs = self._index_man_pages()
            self.documents.extend(man_docs)
            progress.update(task, completed=True, description=f"Indexed {len(man_docs)} man pages")

            # Index help files
            task = progress.add_task("Indexing help documentation...", total=None)
            help_docs = self._index_help_files()
            self.documents.extend(help_docs)
            progress.update(task, completed=True, description=f"Indexed {len(help_docs)} help files")

            # Create embeddings
            task = progress.add_task(f"Creating embeddings for {len(self.documents)} documents...", total=None)
            texts = [doc.content for doc in self.documents]
            embeddings = self.model.encode(texts, show_progress_bar=False)
            progress.update(task, completed=True)

            # Build FAISS index
            task = progress.add_task("Building vector index...", total=None)
            dimension = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity

            # Normalize embeddings for cosine similarity
            faiss.normalize_L2(embeddings)
            self.index.add(embeddings.astype('float32'))
            progress.update(task, completed=True)

            # Save index
            task = progress.add_task("Saving index to disk...", total=None)
            faiss.write_index(self.index, str(self.index_path))
            with open(self.docs_path, 'wb') as f:
                pickle.dump(self.documents, f)
            progress.update(task, completed=True)

        console.print(f"\n✓ Index created with {len(self.documents)} documents!", style="green bold")
        return True

    def _index_man_pages(self, max_pages: int = 500) -> List[Document]:
        """Index common man pages"""
        docs = []
        man_paths = [
            Path("/usr/share/man/man1"),
            Path("/usr/share/man/man5"),
            Path("/usr/share/man/man8"),
        ]

        # Common commands to prioritize
        priority_commands = [
            'apt', 'apt-get', 'dpkg', 'snap', 'systemctl', 'ufw', 'ls', 'cd', 'grep',
            'find', 'chmod', 'chown', 'sudo', 'ssh', 'scp', 'tar', 'wget', 'curl',
            'docker', 'git', 'nano', 'vim', 'cat', 'cp', 'mv', 'rm', 'mkdir', 'touch',
            'ps', 'top', 'kill', 'df', 'du', 'free', 'netstat', 'ip', 'ping',
        ]

        # Index priority commands first
        for cmd in priority_commands:
            try:
                result = subprocess.run(
                    ['man', cmd],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env={'MANWIDTH': '80'}
                )
                if result.returncode == 0:
                    content = result.stdout.strip()
                    if content:
                        docs.append(Document(
                            content=content[:5000],  # Limit size
                            source=f"man {cmd}",
                            title=cmd
                        ))
            except:
                pass

        return docs[:max_pages]

    def _index_help_files(self, max_files: int = 200) -> List[Document]:
        """Index Ubuntu help documentation"""
        docs = []
        help_base = Path("/usr/share/help")

        # Focus on English content
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

                    # Extract title
                    title_elem = root.find(".//{http://projectmallard.org/1.0/}title")
                    title = title_elem.text if title_elem is not None else page_file.stem

                    # Extract all text content
                    text_content = []
                    for elem in root.iter():
                        if elem.text:
                            text_content.append(elem.text.strip())
                        if elem.tail:
                            text_content.append(elem.tail.strip())

                    content = " ".join(filter(None, text_content))
                    if content:
                        docs.append(Document(
                            content=content[:3000],  # Limit size
                            source=str(page_file.relative_to(help_base)),
                            title=title
                        ))
                except:
                    pass

        return docs

    def search(self, query: str, top_k: int = 3) -> List[Tuple[Document, float]]:
        """Search for relevant documents"""
        if self.model is None:
            import logging
            logging.getLogger('sentence_transformers').setLevel(logging.ERROR)
            with suppress_output():
                self.model = SentenceTransformer('all-MiniLM-L6-v2')

        # Encode query
        query_embedding = self.model.encode([query])
        faiss.normalize_L2(query_embedding)

        # Search
        scores, indices = self.index.search(query_embedding.astype('float32'), top_k)

        # Return documents with scores
        results = []
        for idx, score in zip(indices[0], scores[0]):
            if idx < len(self.documents):
                results.append((self.documents[idx], float(score)))

        return results


def main():
    """Test the indexer"""
    indexer = RAGIndexer()
    indexer.load_or_create_index()

    # Test search
    query = "How do I install a package?"
    console.print(f"\n🔍 Searching for: '{query}'", style="cyan")
    results = indexer.search(query, top_k=3)

    for doc, score in results:
        console.print(f"\n📄 {doc.title} (score: {score:.3f})", style="green")
        console.print(f"   Source: {doc.source}", style="dim")
        console.print(f"   Content: {doc.content[:200]}...", style="white")


if __name__ == "__main__":
    main()
