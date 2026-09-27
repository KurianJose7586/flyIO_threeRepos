import asyncio
from app.services.qdrant.service import QdrantService
from app.services.embeddings.service import EmbeddingService
from app.core.config import get_settings

async def main():
    settings = get_settings()
    # Force local provider
    settings.EMBEDDING_PROVIDER = 'local'
    settings.EMBEDDING_MODEL = 'BAAI/bge-base-en-v1.5'
    settings.EMBEDDING_DIMENSION = 768
    
    emb_svc = EmbeddingService(settings=settings)
    qdrant_svc = QdrantService(settings=settings)
    
    vec = await emb_svc.embed_query('What is Noida?')
    
    res = await qdrant_svc.search(query_vector=vec, collection_name='flyio_knowledge_base', limit=3, score_threshold=0.0)
    print(f'Total results: {len(res.results)}')
    for r in res.results:
        print(f'ID: {r.id}, Score: {r.score}')
        print(f'Text: {r.text[:60]}...')
        
asyncio.run(main())
