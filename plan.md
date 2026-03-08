To implement runtime hardware detection and model selection for the **Ask Ubuntu** assistant, you can follow these detailed instructions. This plan involves modifying the existing system to categorize the user's hardware into four tiers and dynamically loading the most suitable models.

### Implementation Overview

1. **Modify `system_indexer.py**`: Add logic to detect CPU vendor, model name, and available RAM to determine a `hardware_tier`.
2. **Modify `chat_engine.py**`: Use the detected tier to select from a predefined map of optimized LLMs.
3. **Modify `rag_indexer.py**`: Use the detected tier to select optimized embedding models.

---

### Phase 1: Hardware Detection Logic

**File:** `system_indexer.py`

Add a method to determine the hardware tier based on system attributes.

```python
def get_hardware_tier(self):
    """
    Categorizes hardware into 4 tiers for model optimization.
    Tiers: high_end, mid_intel, balanced_amd, legacy
    """
    cpu_info = ""
    try:
        # Get CPU model name on Linux
        cpu_info = subprocess.check_output("grep 'model name' /proc/cpuinfo | head -1", shell=True).decode().lower()
    except Exception:
        import platform
        cpu_info = platform.processor().lower()

    # Get Total RAM in GB
    total_ram_gb = 0
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if "MemTotal" in line:
                    total_ram_gb = int(line.split()[1]) / (1024 * 1024)
                    break
    except Exception:
        total_ram_gb = 8 # Default assumption

    # Tier Logic [Inference]
    if "strix" in cpu_info or "ryzen ai" in cpu_info:
        return "high_end"
    elif "intel" in cpu_info and ("ultra" in cpu_info or "core i" in cpu_info):
        return "mid_intel"
    elif "amd" in cpu_info and total_ram_gb >= 16:
        return "balanced_amd"
    else:
        return "legacy"

```

---

### Phase 2: Dynamic Model Mapping

Update the initialization in your engine files to reference this tier.

#### **1. LLM Selection (Chat Engine)**

**File:** `chat_engine.py`

Replace the hardcoded `Qwen3-4B-Instruct-2507-GGUF` with a dynamic selection:

```python
# Tier-to-Model Map
LLM_TIER_MAP = {
    "high_end": "Qwen3-4B-Instruct-2507-GGUF",     # NPU optimized
    "mid_intel": "Phi-3.5-mini-instruct-Q4_K_M",   # Fast on Intel CPU/iGPU
    "balanced_amd": "Llama-3.2-3B-Instruct-Q4_K_M",# Good for non-NPU Ryzen
    "legacy": "Llama-3.2-1B-Instruct-Q4_K_M"       # Low RAM/Old CPU
}

# Implementation in __init__
tier = self.system_indexer.get_hardware_tier()
self.model = LLM_TIER_MAP.get(tier, "legacy")

```

#### **2. Embedding Selection (RAG Indexer)**

**File:** `rag_indexer.py`

Replace `nomic-embed-text-v1-GGUF` with hardware-appropriate alternatives:

```python
EMBED_TIER_MAP = {
    "high_end": "nomic-embed-text-v1.5-GGUF",
    "mid_intel": "all-MiniLM-L6-v2-GGUF",      # Extremely lightweight for Intel
    "balanced_amd": "nomic-embed-text-v1-GGUF",
    "legacy": "bge-small-en-v1.5-GGUF"         # Smallest footprint
}

tier = self.system_indexer.get_hardware_tier()
self.embed_model = EMBED_TIER_MAP.get(tier, "legacy")

```

---

### Phase 3: Instructions for OpenHands CLI

You can feed the following prompt to OpenHands to automate these changes:

> **OpenHands Task:** > 1. Modify `system_indexer.py` to include a `get_hardware_tier()` method that detects CPU type (Intel vs AMD) and model (searching for "strix" or "ryzen ai") and RAM size.
> 2. Update `chat_engine.py` to import this tier and select an LLM model from the following map:
> * High-End (Strix): Qwen3-4B-Instruct
> * Mid Intel: Phi-3.5-mini-instruct
> * Balanced AMD: Llama-3.2-3B-Instruct
> * Legacy: Llama-3.2-1B-Instruct
>
>

> 3. Update `rag_indexer.py` to use a similar mapping for embedding models, defaulting to `bge-small-en-v1.5-GGUF` for legacy systems.
> 4. Ensure all models are formatted for the Lemonade Server API (GGUF).
>
>

### Sources:

* `system_indexer.py` - Hardware info collection logic.
* `chat_engine.py` - AI model initialization.
* `rag_indexer.py` - Embedding model usage.
* Lemonade Server Spec - Model loading endpoints and hardware constraints.
