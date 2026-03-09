# Ask Ubuntu Agents & System Personas

This document describes the specialized AI agents, system prompts, and tool-calling behaviors used by **Ask Ubuntu** to provide system-aware assistance.

## Overview

Ask Ubuntu uses a multi-layered approach to provide accurate, machine-specific advice. It combines a core "Ubuntu Expert" persona with specialized indexing agents that feed real-time system state into the context window.

---

## 1. The Ubuntu Assistant (Core Agent)

The primary agent is designed to be a helpful, technical, yet accessible Ubuntu Linux expert.

- **System Role**: A professional Linux administrator and desktop support specialist.
- **Tone**: Concise, technical, and safety-conscious (especially when suggesting `sudo` commands).
- **Primary Objective**: Help users navigate Ubuntu Desktop, troubleshoot system issues, and optimize hardware performance.

### Capabilities
- **System Awareness**: Uses data provided by the `System Indexer` to understand the user's specific hardware and software environment.
- **RAG Integration**: Accesses local documentation, man pages, and Ubuntu help files via the `RAG Indexer`.
- **Hybrid Execution**: Can operate locally (via Lemonade SDK) or through remote providers (Anthropic, OpenAI, Gemini).

---

## 2. Supporting Agents & Indexers

### System State Indexer (`system_indexer.py`)
This "Passive Agent" runs at startup to gather a comprehensive snapshot of the machine. It provides the Core Agent with:
- **Hardware Context**: CPU topology, GPU utilization (AMD/NVIDIA), and Memory/PSI pressure.
- **Storage Context**: Partition schemes (LVM/LUKS), disk health, and mount points.
- **Network Context**: Interface states, VPN status, and link speeds.

### RAG Indexer (`rag_indexer.py`)
This agent manages the Knowledge Base by indexing:
- Local man pages (`/usr/share/man`)
- Ubuntu Help files (`/usr/share/help`)
- Snap-specific documentation

---

## 3. Tool Definitions & Constraints

Ask Ubuntu agents are governed by the following operational constraints:

### Safe Command Generation
When providing terminal commands, the agent must:
1. Prefer `snap` or `apt` over raw binary execution where possible.
2. Explicitly warn users before suggesting commands that modify system partitions or boot configurations (GRUB).
3. Check against the current `app_env.py` to ensure suggested paths are valid within the Snap's strict confinement (e.g., using `hostfs` paths).

### Environment Awareness
The agent adjusts its advice based on:
- **Form Factor**: Tailors power management advice differently for laptops vs. servers.
- **Session Type**: Detects if the user is on X11 or Wayland before suggesting display-related fixes.

---

## 4. Local vs. Remote Orchestration

The `engine_orchestration.py` manages how agents are dispatched:
- **Local First**: Prioritizes the Lemonade SDK for privacy and offline capability.
- **Cloud Fallback**: Switches to remote providers if local LLM resources are insufficient or unavailable.
