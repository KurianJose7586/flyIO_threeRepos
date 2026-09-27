import asyncio
from app.services.qdrant.service import QdrantService
from app.core.config import get_settings

async def main():
    settings = get_settings()
    qdrant_svc = QdrantService(settings=settings)
    
    # query points by ID directly
    pts = await qdrant_svc.client.retrieve('flyio_knowledge_base', ids=['ee37fba7-d21b-58c1-a8b8-806ec866eba2', 'a61a10de-f431-5500-bdf3-7a40591e27c5'], with_payload=True, with_vectors=True)
    if pts:
        for p in pts:
            print(f'ID: {p.id}')
            print(f'Payload: {p.payload.get("text", "")[:60]}...')
            if p.vector:
                print(f'Vector type: {type(p.vector)}, length: {len(p.vector)}')
            else:
                print('No vector')
    else:
        print('Points not found in Qdrant.')
        
asyncio.run(main())
