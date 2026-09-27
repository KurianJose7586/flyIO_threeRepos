import asyncio
import numpy as np
from app.services.qdrant.service import QdrantService
from app.services.embeddings.mock_provider import MockEmbeddingProvider
from app.core.config import get_settings

async def main():
    settings = get_settings()
    qdrant_svc = QdrantService(settings=settings)
    
    pts = await qdrant_svc.client.retrieve('flyio_knowledge_base', ids=['6e68903c-46a5-53ec-9358-c4f8277c041f'], with_vectors=True, with_payload=True)
    if not pts:
        print('Point not found')
        return
        
    stored_vec = np.array(pts[0].vector)
    text = pts[0].payload['text']
    
    mock_prov = MockEmbeddingProvider(dimension=768)
    q_vec_mock = np.array(await mock_prov.embed_text(text))
    
    score_mock = np.dot(stored_vec, q_vec_mock)
    print(f'Similarity with Mock: {score_mock}')
        
asyncio.run(main())
