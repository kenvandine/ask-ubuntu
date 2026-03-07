from setuptools import setup

setup(
    name="ask-ubuntu",
    version="1.0",
    py_modules=[
        "main",
        "chat_engine",
        "rag_indexer",
        "system_indexer",
        "server",
        "remote_providers",
        "i18n",
    ],
    entry_points={
        "console_scripts": [
            "ask-ubuntu=main:main",
        ],
    },
)
