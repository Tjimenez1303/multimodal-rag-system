"""Clients of model servers that implement the OpenAI API format.

The name refers to the format of the routes and bodies (``/v1/chat/completions``,
``/v1/embeddings``) that Docker Model Runner, Ollama, llama.cpp and vLLM implement.
These clients use neither OpenAI's service nor its SDK, only httpx.
"""
