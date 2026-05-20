import asyncio
import sys
from pathlib import Path
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

# Allow importing api.core from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.core.config import settings

async def verify_schema():
    print(f"🔍 Connecting to {settings.database_url.split('@')[-1]}...")
    engine = create_async_engine(settings.database_url)
    
    REQUIRED_TABLES = {
        "mandi_prices", 
        "farmers", 
        "crop_declarations", 
        "knowledge_chunks",
        "chat_history"
    }

    try:
        async with engine.connect() as conn:
            # SQLAlchemy inspect is sync-bound; we use run_sync
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
            
            found = set(tables)
            missing = REQUIRED_TABLES - found
            
            print(f"📊 Tables found: {', '.join(tables)}")
            
            if not missing:
                print("✅ All 5 core tables are present. Schema is synced.")
            else:
                print(f"❌ Missing tables: {', '.join(missing)}")
                sys.exit(1)
                
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(verify_schema())
