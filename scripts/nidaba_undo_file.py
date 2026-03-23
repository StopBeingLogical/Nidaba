import json
from pathlib import Path
import chromadb
import logging

# Paths
TRACKER_DIR = Path("/Volumes/Shuttle/projects/nidaba/tracker/")
MIGRATION_TRACKER_PATH = TRACKER_DIR / "migration_tracker.json"
CHROMA_PATH = TRACKER_DIR / "chroma_db"
TARGET_FILE = "/Volumes/Shuttle/projects/nidaba/staging/conversations.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def undo():
    # 1. Clean ChromaDB
    logger.info(f"Removing {TARGET_FILE} from ChromaDB...")
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = chroma_client.get_collection(name="nidaba_atoms")
    
    # Chroma delete by metadata
    collection.delete(where={"source_path": TARGET_FILE})
    logger.info("ChromaDB cleanup complete.")

    # 2. Clean Migration Tracker
    logger.info(f"Removing {TARGET_FILE} from migration tracker...")
    if MIGRATION_TRACKER_PATH.exists():
        with open(MIGRATION_TRACKER_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)
        
        # Filter out entries matching the source path
        initial_count = len(data)
        new_data = {k: v for k, v in data.items() if v.get('source_path') != TARGET_FILE}
        removed_count = initial_count - len(new_data)
        
        with open(MIGRATION_TRACKER_PATH, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, indent=2)
        
        logger.info(f"Removed {removed_count} entries from tracker. Remaining: {len(new_data)}")
    else:
        logger.warning("Migration tracker not found.")

if __name__ == "__main__":
    undo()
