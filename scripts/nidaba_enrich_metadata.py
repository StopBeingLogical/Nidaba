import os
import json
import re
from pathlib import Path
from datetime import datetime
import chromadb
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paths
PROCESSED_DIR = Path("/Volumes/Shuttle/projects/nidaba/staging_processed/")
TRACKER_PATH = Path("/Volumes/Shuttle/projects/nidaba/tracker/migration_tracker.json")
CHROMA_PATH = Path("/Volumes/Shuttle/projects/nidaba/tracker/chroma_db")

def extract_date_from_filename(filename):
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d').isoformat()
        except:
            pass
    return None

def get_mtime(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
    except:
        return datetime.now().isoformat()

def enrich():
    if not TRACKER_PATH.exists():
        logger.error(f"Tracker not found at {TRACKER_PATH}")
        return

    with open(TRACKER_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        tracker = json.load(f)

    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = chroma_client.get_collection(name="nidaba_atoms")

    # JSON Caches
    chatgpt_cache = {} # path -> {msg_id -> timestamp}
    myactivity_cache = {} # path -> {index_role -> timestamp}
    concierge_cache = {} # path -> conversation_timestamp

    high_precision = 0
    low_precision = 0

    # Step 1: Pre-process JSON files found in tracker
    unique_sources = set(item['source_path'] for item in tracker.values())
    
    for src in unique_sources:
        path = Path(src)
        # Handle staging -> staging_processed path translation
        if "/staging/" in src:
            path = Path(src.replace("/staging/", "/staging_processed/"))
        
        if not path.exists():
            continue

        if path.name == "conversations.json" or "chunk_" in path.name and path.suffix == ".json":
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.load(f)
                cache = {}
                if isinstance(data, list) and len(data) > 0 and 'mapping' in data[0]:
                    for conv in data:
                        for msg_id, mapping in conv.get('mapping', {}).items():
                            msg = mapping.get('message')
                            if msg and msg.get('create_time'):
                                cache[msg_id] = datetime.fromtimestamp(msg['create_time']).isoformat()
                chatgpt_cache[str(src)] = cache
            except: pass

        elif path.name == "MyActivity.json":
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.load(f)
                cache = {}
                for idx, item in enumerate(data):
                    ts = item.get('time')
                    if ts:
                        cache[f"{idx}_title"] = ts
                        cache[f"{idx}_response"] = ts
                myactivity_cache[str(src)] = cache
            except: pass

        elif "concierge_extracted_conversations" in path.name:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    data = json.load(f)
                cache = {}
                for conv_title, conv_data in data.items():
                    ts = conv_data.get('created')
                    if ts:
                        cache[conv_title] = datetime.fromtimestamp(ts).isoformat()
                concierge_cache[str(src)] = cache
            except: pass

    # Step 2: Update Atoms
    all_uuids = list(tracker.keys())
    # Chroma update needs metadata lists
    # We'll batch these
    UPDATE_BATCH_SIZE = 500
    
    for i in range(0, len(all_uuids), UPDATE_BATCH_SIZE):
        batch_uuids = all_uuids[i:i+UPDATE_BATCH_SIZE]
        batch_metadatas = []
        ids_to_update = []

        for uuid in batch_uuids:
            item = tracker[uuid]
            src = item['source_path']
            line_range = item['line_range']
            topic = item['topic']
            
            new_ts = None
            precision = "low"

            # Try High Precision
            if src in chatgpt_cache:
                # line_range is cidx_mUUID
                msg_id_match = re.search(r'_m(.*)$', line_range)
                if msg_id_match:
                    new_ts = chatgpt_cache[src].get(msg_id_match.group(1))
            
            if not new_ts and src in myactivity_cache:
                # line_range is item_X_role
                match = re.search(r'item_(\d+)_(.*)', line_range)
                if match:
                    new_ts = myactivity_cache[src].get(f"{match.group(1)}_{match.group(2)}")

            if not new_ts and src in concierge_cache:
                # topic is "conversation: TITLE"
                title = topic.replace("conversation: ", "")
                new_ts = concierge_cache[src].get(title)

            if new_ts:
                precision = "high"
            else:
                # Fallback to Low Precision
                path = Path(src)
                if "/staging/" in src:
                    path = Path(src.replace("/staging/", "/staging_processed/"))
                
                new_ts = extract_date_from_filename(path.name)
                if not new_ts and path.exists():
                    new_ts = get_mtime(path)
                
                if not new_ts:
                    new_ts = item['timestamp'] # keep original if all else fails

            # Apply Update
            item['timestamp'] = new_ts
            if precision == "high": high_precision += 1
            else: low_precision += 1

            # Prepare for Chroma
            ids_to_update.append(uuid)
            batch_metadatas.append({
                "source_path": src,
                "line_range": line_range,
                "topic": topic,
                "timestamp": new_ts
            })

        # Update Chroma
        if ids_to_update:
            collection.update(ids=ids_to_update, metadatas=batch_metadatas)

    # Step 3: Save Tracker
    with open(TRACKER_PATH, 'w') as f:
        json.dump(tracker, f, indent=2)

    logger.info(f"Enrichment Complete.")
    logger.info(f"High Precision (JSON): {high_precision}")
    logger.info(f"Low Precision (Filesystem): {low_precision}")

if __name__ == "__main__":
    enrich()
