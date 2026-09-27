import asyncio
import numpy as np
from app.services.qdrant.service import QdrantService
from app.services.embeddings.service import EmbeddingService
from app.services.embeddings.mock_provider import MockEmbeddingProvider
from app.core.config import get_settings

async def main():
    settings = get_settings()
    settings.EMBEDDING_PROVIDER = 'local'
    settings.EMBEDDING_MODEL = 'BAAI/bge-base-en-v1.5'
    settings.EMBEDDING_DIMENSION = 768
    
    emb_svc = EmbeddingService(settings=settings)
    qdrant_svc = QdrantService(settings=settings)
    
    # query point
    pts = await qdrant_svc.client.retrieve('flyio_knowledge_base', ids=['ee37fba7-d21b-58c1-a8b8-806ec866eba2'], with_vectors=True, with_payload=True)
    stored_vec = np.array(pts[0].vector)
    
    # 1. Local embedding query
    q_vec_local = np.array(await emb_svc.embed_query('Noida'))
    
    # 2. Mock embedding query
    mock_prov = MockEmbeddingProvider(dimension=768)
    q_vec_mock = np.array(await mock_prov.embed_text(pts[0].payload['text']))
    
    # Compute cosine similarity
    score_local = np.dot(stored_vec, q_vec_local)
    score_mock = np.dot(stored_vec, q_vec_mock)
    
    print(f'Similarity with Local Embedding: {score_local}')
    print(f'Similarity with Mock Embedding (exact text): {score_mock}')
        
asyncio.run(main())
