"""Small persistent vector store; backend identity prevents mixed-vector retrieval."""
import hashlib
import math
import os
from apps.history.search import tokens
from .providers import post_json

class HashEmbedding:
    reference = 'hash-lexical-v1:256'
    def embed(self, text):
        vector = [0.0] * 256
        for token in tokens(text):
            index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % 256
            vector[index] += 1
        norm = math.sqrt(sum(x*x for x in vector)) or 1
        return [x / norm for x in vector]

class OllamaEmbedding:
    def __init__(self):
        self.model = os.getenv('EMBEDDING_MODEL', '')
        if not self.model:
            raise ValueError('EMBEDDING_MODEL is required')
        self.reference = 'ollama:' + self.model
    def embed(self, text):
        result = post_json(os.getenv('LOCAL_LLM_URL', 'http://127.0.0.1:11434').rstrip('/') + '/api/embed', {'model': self.model, 'input': text})
        vector = result['embeddings'][0]
        if not vector or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
            raise ValueError('Invalid embedding')
        norm = math.sqrt(sum(x*x for x in vector)) or 1
        return [x / norm for x in vector]

def embedding_service():
    backend = os.getenv('EMBEDDING_BACKEND', 'hash')
    if backend not in {'hash', 'ollama'}:
        raise ValueError('Unknown embedding backend')
    return OllamaEmbedding() if backend == 'ollama' else HashEmbedding()

def similarity(left, right):
    if len(left) != len(right):
        return 0.0
    return sum(a*b for a, b in zip(left, right))
