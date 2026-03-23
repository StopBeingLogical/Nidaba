import os
import json
import hashlib
import asyncio
import httpx
import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime
import chromadb
from chromadb.config import Settings
from tqdm import tqdm
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paths
STAGING_DIR = Path("/Volumes/Shuttle/projects/nidaba/staging/")
TRACKER_DIR = Path("/Volumes/Shuttle/projects/nidaba/tracker/")
MIGRATION_TRACKER_PATH = TRACKER_DIR / "migration_tracker.json"
CHROMA_PATH = TRACKER_DIR / "chroma_db"

# Embedding settings
OLLAMA_API_URL = "http://localhost:11434/api/embeddings"
MODEL_NAME = "nomic-embed-text"
BATCH_SIZE = 50
CONCURRENT_BATCHES = 5

class MigrationTracker:
    def __init__(self, path):
        self.path = path
        self.data = {}
        if self.path.exists():
            try:
                with open(self.path, 'r', encoding='utf-8', errors='ignore') as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Error loading migration tracker: {e}")

    def is_processed(self, uuid):
        return uuid in self.data and self.data[uuid].get('status') == 'COMPLETED'

    def mark_completed(self, uuid, source_path, line_range, topic):
        self.data[uuid] = {
            'uuid': uuid,
            'source_path': str(source_path),
            'line_range': line_range,
            'timestamp': datetime.now().isoformat(),
            'topic': topic,
            'status': 'COMPLETED'
        }

    def save(self):
        try:
            with open(self.path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tracker: {e}")

class Atomizer:
    @staticmethod
    def get_uuid(text):
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    @staticmethod
    def split_into_paragraphs(text):
        paragraphs = re.split(r'\n\s*\n', text)
        return [p.strip() for p in paragraphs if p.strip()]

    @staticmethod
    def split_long_text(text, max_length=6000):
        """Recursively split text into chunks smaller than max_length."""
        if len(text) <= max_length:
            return [text]

        # Try splitting by double newline (paragraphs)
        if '\n\n' in text:
            parts = text.split('\n\n')
            result = []
            for p in parts:
                if p.strip():
                    result.extend(Atomizer.split_long_text(p.strip(), max_length))
            return result

        # Try splitting by single newline
        if '\n' in text:
            parts = text.split('\n')
            result = []
            for p in parts:
                if p.strip():
                    result.extend(Atomizer.split_long_text(p.strip(), max_length))
            return result

        # Try splitting by sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        if len(sentences) > 1:
            result = []
            current = ""
            for s in sentences:
                s = s.strip()
                if not s: continue
                # Estimate length with a space separator
                if len(current) + len(s) + (1 if current else 0) <= max_length:
                    current = (current + " " + s).strip()
                else:
                    if current:
                        result.append(current)
                    if len(s) > max_length:
                        result.extend(Atomizer.split_long_text(s, max_length))
                        current = ""
                    else:
                        current = s
            if current:
                result.append(current)
            return result

        # Fallback to character split
        return [text[i:i + max_length] for i in range(0, len(text), max_length)]

    def _create_atoms(self, content, source_path, line_range_prefix, topic):
        """Helper to create one or more atoms from content, handling length limits."""
        chunks = self.split_long_text(content)
        atoms = []
        for j, chunk in enumerate(chunks):
            uuid = self.get_uuid(chunk)
            line_range = line_range_prefix
            if len(chunks) > 1:
                line_range = f"{line_range_prefix}_sub{j}"
            atoms.append({
                'uuid': uuid,
                'content': chunk,
                'source_path': str(source_path),
                'line_range': line_range,
                'topic': topic
            })
        return atoms

    def atomize_text(self, text, source_path, topic="general"):
        atoms = []
        paragraphs = self.split_into_paragraphs(text)
        for i, para in enumerate(paragraphs):
            atoms.extend(self._create_atoms(para, source_path, f"p{i}", topic))
        return atoms

    def process_html(self, path):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            soup = BeautifulSoup(f.read(), 'lxml')
            text_elements = []
            for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']):
                text = tag.get_text(strip=True)
                if text:
                    text_elements.append(text)
            return self.atomize_text("\n\n".join(text_elements), path, topic="html")

    def process_xlsx(self, path):
        atoms = []
        try:
            df = pd.read_excel(path)
            for idx, row in df.iterrows():
                row_text = " | ".join([f"{col}: {val}" for col, val in row.items() if pd.notna(val)])
                if row_text:
                    atoms.extend(self._create_atoms(row_text, path, f"r{idx}", "excel"))
        except Exception as e:
            logger.error(f"Error processing XLSX {path}: {e}")
        return atoms

    def process_json(self, path):
        atoms = []
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
            
            # 1. MyActivity.json (Google Takeout)
            if path.name == "MyActivity.json" and isinstance(data, list):
                logger.info(f"Using specialized MyActivity.json handler for {path}")
                for idx, item in enumerate(data):
                    # Atom 1: title (User query)
                    title = item.get('title', '')
                    if title:
                        atoms.extend(self._create_atoms(title, path, f"item_{idx}_title", "google_takeout_query"))
                    
                    # Atom 2: safeHtmlItem[0].html (Assistant response)
                    html_items = item.get('safeHtmlItem', [])
                    if html_items and 'html' in html_items[0]:
                        html_content = html_items[0]['html']
                        soup = BeautifulSoup(html_content, 'lxml')
                        assistant_response = soup.get_text(separator=' ', strip=True)
                        if assistant_response:
                            atoms.extend(self._create_atoms(assistant_response, path, f"item_{idx}_response", "google_takeout_response"))
                return atoms

            # 2. concierge_extracted_conversations-*.json
            is_concierge = False
            if isinstance(data, dict) and data:
                for k, v in list(data.items())[:5]:
                    if isinstance(v, dict) and 'messages' in v:
                        is_concierge = True
                        break
            
            if is_concierge:
                logger.info(f"Using specialized Concierge Conversations handler for {path}")
                for conv_id, conv_data in data.items():
                    if isinstance(conv_data, dict) and 'messages' in conv_data:
                        for msg_idx, msg in enumerate(conv_data['messages']):
                            role = msg.get('role')
                            content = msg.get('content')
                            if role in ['user', 'assistant'] and content:
                                atoms.extend(self._create_atoms(content, path, f"{conv_id}_m{msg_idx}", f"concierge_{role}"))
                return atoms

            # 3. ChatGPT export
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and 'mapping' in data[0]:
                logger.info(f"Using specialized ChatGPT export handler for {path}")
                for conv_idx, conv in enumerate(data):
                    title = conv.get('title', 'Untitled')
                    for msg_id, mapping in conv.get('mapping', {}).items():
                        msg = mapping.get('message')
                        if msg and msg.get('author', {}).get('role') in ['user', 'assistant']:
                            parts = msg.get('content', {}).get('parts', [])
                            content = " ".join([p for p in parts if isinstance(p, str)])
                            if content:
                                atoms.extend(self._create_atoms(content, path, f"c{conv_idx}_m{msg_id}", f"chatgpt_conv: {title}"))
                return atoms

            # 4. Claude export
            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and 'chat_messages' in data[0]:
                logger.info(f"Using specialized Claude export handler for {path}")
                for conv_idx, conv in enumerate(data):
                    title = conv.get('name', 'Untitled')
                    summary = conv.get('summary')
                    if summary:
                        atoms.extend(self._create_atoms(summary, path, f"c{conv_idx}_summary", f"claude_conv: {title}"))
                    
                    for msg_idx, msg in enumerate(conv.get('chat_messages', [])):
                        role = msg.get('sender')
                        content = msg.get('text')
                        if role in ['human', 'assistant'] and content:
                            role_tag = "user" if role == "human" else "assistant"
                            atoms.extend(self._create_atoms(content, path, f"c{conv_idx}_m{msg_idx}", f"claude_{role_tag}: {title}"))
                return atoms

            # Default: General JSON
            logger.info(f"Using general JSON handler for {path}")
            text = json.dumps(data, indent=2)
            return self.atomize_text(text, path, topic="json")
        except Exception as e:
            logger.error(f"Error processing JSON {path}: {e}")
        return atoms

    def process_jsonl(self, path):
        atoms = []
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for idx, line in enumerate(f):
                    try:
                        data = json.loads(line)
                        text = json.dumps(data)
                        atoms.extend(self._create_atoms(text, path, f"l{idx}", "jsonl"))
                    except:
                        continue
        except Exception as e:
            logger.error(f"Error processing JSONL {path}: {e}")
        return atoms

class EmbeddingClient:
    def __init__(self, api_url, model):
        self.api_url = api_url
        self.model = model

    async def embed_batch(self, client, texts):
        tasks = []
        for text in texts:
            tasks.append(self.embed_single(client, text))
        return await asyncio.gather(*tasks)

    async def embed_single(self, client, text):
        try:
            response = await client.post(
                self.api_url,
                json={"model": self.model, "prompt": text},
                timeout=30.0
            )
            if response.status_code == 200:
                return response.json().get('embedding')
            else:
                logger.error(f"Ollama API error {response.status_code}: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Ollama connection error: {e}")
            return None

async def process_batch(client, batch, tracker, chroma_collection, embed_client, semaphore):
    async with semaphore:
        texts = [b['content'] for b in batch]
        embeddings = await embed_client.embed_batch(client, texts)
        
        ids = []
        valid_embeddings = []
        metadatas = []
        documents = []
        
        for atom, emb in zip(batch, embeddings):
            if emb:
                ids.append(atom['uuid'])
                valid_embeddings.append(emb)
                metadatas.append({
                    'source_path': atom['source_path'],
                    'line_range': atom['line_range'],
                    'topic': atom['topic'],
                    'timestamp': datetime.now().isoformat()
                })
                documents.append(atom['content'])
                tracker.mark_completed(atom['uuid'], atom['source_path'], atom['line_range'], atom['topic'])
        
        if valid_embeddings:
            unique_ids = []
            unique_embeddings = []
            unique_metadatas = []
            unique_documents = []
            seen_uuids = set()
            
            for i, uuid in enumerate(ids):
                if uuid not in seen_uuids:
                    seen_uuids.add(uuid)
                    unique_ids.append(uuid)
                    unique_embeddings.append(valid_embeddings[i])
                    unique_metadatas.append(metadatas[i])
                    unique_documents.append(documents[i])

            try:
                chroma_collection.add(
                    ids=unique_ids,
                    embeddings=unique_embeddings,
                    metadatas=unique_metadatas,
                    documents=unique_documents
                )
            except chromadb.errors.DuplicateIDError:
                pass 
            except Exception as e:
                logger.error(f"Error adding batch to ChromaDB: {e}")

async def process_atoms(atoms, tracker, chroma_collection, embed_client):
    unique_atoms = {}
    skipped_by_tracker = 0
    for atom in atoms:
        uuid = atom['uuid']
        if uuid in unique_atoms:
            continue
        if tracker.is_processed(uuid):
            skipped_by_tracker += 1
            continue
        unique_atoms[uuid] = atom

    if not unique_atoms:
        if skipped_by_tracker > 0:
            logger.info(f"Skipped {skipped_by_tracker} atoms (already in tracker).")
        return

    uuids_to_check = list(unique_atoms.keys())
    to_embed_map = {}
    skipped_by_chroma = 0
    CHROMA_CHECK_BATCH_SIZE = 500

    for i in range(0, len(uuids_to_check), CHROMA_CHECK_BATCH_SIZE):
        batch_uuids = uuids_to_check[i:i + CHROMA_CHECK_BATCH_SIZE]
        try:
            results = chroma_collection.get(ids=batch_uuids)
            existing_ids = set(results['ids'])
            
            for uuid in batch_uuids:
                atom = unique_atoms[uuid]
                if uuid in existing_ids:
                    tracker.mark_completed(uuid, atom['source_path'], atom['line_range'], atom['topic'])
                    skipped_by_chroma += 1
                else:
                    to_embed_map[uuid] = atom
        except Exception as e:
            logger.error(f"Error checking ChromaDB batch: {e}")
            for uuid in batch_uuids:
                if uuid not in to_embed_map:
                    to_embed_map[uuid] = unique_atoms[uuid]

    if skipped_by_chroma > 0:
        tracker.save()

    to_embed = list(to_embed_map.values())
    
    total_skipped = skipped_by_tracker + skipped_by_chroma
    logger.info(f"Atoms status: {total_skipped} skipped, {len(to_embed)} to embed.")

    if not to_embed:
        return

    semaphore = asyncio.Semaphore(CONCURRENT_BATCHES)
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(0, len(to_embed), BATCH_SIZE):
            batch = to_embed[i:i + BATCH_SIZE]
            tasks.append(process_batch(client, batch, tracker, chroma_collection, embed_client, semaphore))
        
        await asyncio.gather(*tasks)
    
    tracker.save()

async def main():
    if not TRACKER_DIR.exists():
        TRACKER_DIR.mkdir(parents=True)
    
    tracker = MigrationTracker(MIGRATION_TRACKER_PATH)
    atomizer = Atomizer()
    embed_client = EmbeddingClient(OLLAMA_API_URL, MODEL_NAME)
    
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = chroma_client.get_or_create_collection(name="nidaba_atoms")
    
    # 1. File Selection & Filtering
    SKIP_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.wav', '.pdf', '.zip', '.pyc', '.map'}
    
    files = []
    for p in STAGING_DIR.rglob('*'):
        if p.is_file():
            # Skip macOS metadata files
            if p.name.startswith('._') or p.name == '.DS_Store':
                continue
            if p.suffix.lower() in SKIP_EXTENSIONS:
                continue
            files.append(p)
    
    logger.info(f"Found {len(files)} files to process.")
    
    for file_path in tqdm(files, desc="Processing files"):
        try:
            atoms = []
            ext = file_path.suffix.lower()
            
            # 6. Improved Logging for specialized handlers
            if ext == '.json':
                atoms = atomizer.process_json(file_path)
            elif ext == '.jsonl':
                logger.info(f"Using specialized JSONL handler for {file_path}")
                atoms = atomizer.process_jsonl(file_path)
            elif ext == '.html':
                logger.info(f"Using specialized HTML handler for {file_path}")
                atoms = atomizer.process_html(file_path)
            elif ext == '.xlsx':
                logger.info(f"Using specialized XLSX handler for {file_path}")
                atoms = atomizer.process_xlsx(file_path)
            elif ext == '.md' or ext == '':
                # 3. Handle Extensionless Files as text (paragraphs)
                topic = "markdown" if ext == '.md' else "extensionless"
                logger.info(f"Using text handler ({topic}) for {file_path}")
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    atoms = atomizer.atomize_text(f.read(), file_path, topic=topic)
            else:
                # 7. Encoding: utf-8, ignore
                logger.info(f"Using general file handler for {file_path}")
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    atoms = atomizer.atomize_text(f.read(), file_path, topic=f"file_{ext[1:]}" if ext else "text")
            
            if atoms:
                await process_atoms(atoms, tracker, collection, embed_client)
        except Exception as e:
            logger.error(f"Failed to process file {file_path}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
