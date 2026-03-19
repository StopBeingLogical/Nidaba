import json
import os
import chromadb
import sys

# Paths
MIGRATION_TRACKER_PATH = "/Volumes/Shuttle/projects/nidaba/tracker/migration_tracker.json"
CHROMA_DB_PATH = "/Volumes/Shuttle/projects/nidaba/tracker/chroma_db"
COLLECTION_NAME = "nidaba_atoms"

def purge_garbage():
    if not os.path.exists(MIGRATION_TRACKER_PATH):
        print(f"Error: {MIGRATION_TRACKER_PATH} not found.")
        return

    print(f"Loading {MIGRATION_TRACKER_PATH}...")
    try:
        with open(MIGRATION_TRACKER_PATH, 'r') as f:
            tracker_data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return

    to_delete_uuids = []
    purged_sources = set()

    # Identify "garbage" UUIDs
    # A source_path is considered garbage if the filename starts with '._' or is '.DS_Store'
    for uuid, entry in tracker_data.items():
        source_path = entry.get('source_path', '')
        if not source_path:
            continue
            
        filename = os.path.basename(source_path)
        
        # Identify "garbage"
        if filename.startswith('._') or filename == '.DS_Store':
            to_delete_uuids.append(uuid)
            purged_sources.add(source_path)

    if not to_delete_uuids:
        print("No garbage atoms found in tracker.")
        return

    print(f"Found {len(to_delete_uuids)} garbage atoms from {len(purged_sources)} sources.")

    # Connect to ChromaDB
    print(f"Connecting to ChromaDB at {CHROMA_DB_PATH}...")
    try:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        print(f"Error connecting to ChromaDB: {e}")
        return

    # Delete from ChromaDB
    # Using batches to ensure robustness
    batch_size = 500
    total_to_delete = len(to_delete_uuids)
    for i in range(0, total_to_delete, batch_size):
        batch = to_delete_uuids[i:i + batch_size]
        print(f"Deleting batch {i // batch_size + 1}/{(total_to_delete + batch_size - 1) // batch_size} ({len(batch)} items) from ChromaDB...")
        try:
            collection.delete(ids=batch)
        except Exception as e:
            print(f"Error deleting batch from ChromaDB: {e}")

    # Remove from tracker data
    print("Updating tracker data...")
    for uuid in to_delete_uuids:
        if uuid in tracker_data:
            del tracker_data[uuid]

    # Save updated tracker data
    print(f"Saving updated {MIGRATION_TRACKER_PATH}...")
    try:
        temp_path = MIGRATION_TRACKER_PATH + ".tmp"
        with open(temp_path, 'w') as f:
            json.dump(tracker_data, f, indent=2)
        os.rename(temp_path, MIGRATION_TRACKER_PATH)
    except Exception as e:
        print(f"Error saving updated JSON: {e}")
        return

    print("\nSummary:")
    print(f"Total atoms purged: {len(to_delete_uuids)}")
    print(f"Total sources purged: {len(purged_sources)}")
    
    if purged_sources:
        print("\nExamples of purged sources (up to 10):")
        for s in sorted(list(purged_sources))[:10]:
            print(f"- {s}")
        if len(purged_sources) > 10:
            print(f"... and {len(purged_sources) - 10} more.")

if __name__ == '__main__':
    purge_garbage()
