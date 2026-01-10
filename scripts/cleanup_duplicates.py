
import sys
import hashlib
import json
from pathlib import Path

# Fix path to ensure backend imports work if needed, though we use stdlib mostly
sys.path.append(str(Path.cwd()))

# Constants
SESSION_ROOT = Path("data/user_sessions")

def cleanup_duplicates(session_id: str):
    print(f"Starting cleanup for session {session_id}...")
    session_dir = SESSION_ROOT / session_id
    if not session_dir.exists():
        print(f"Session directory {session_dir} does not exist.")
        return

    extracted_dir = session_dir / "extracted"
    raw_dir = session_dir / "raw"
    
    if not extracted_dir.exists():
        print("No extracted directory found.")
        return
        
    content_map = {}
    
    # 1. Scan documents
    print("Hashing documents...")
    files = list(extracted_dir.glob("EOB-*.json"))
    for json_file in files:
        doc_id = json_file.stem
        try:
            data = json.loads(json_file.read_text(encoding='utf-8'))
            filename = data.get('filename')
            if not filename:
                continue
                
            raw_path = raw_dir / filename
            if not raw_path.exists():
                print(f"Skipping {doc_id} (raw file {filename} missing)")
                continue
            
            # Compute Hash
            file_bytes = raw_path.read_bytes()
            f_hash = hashlib.sha256(file_bytes).hexdigest()
            
            if f_hash not in content_map:
                content_map[f_hash] = []
            content_map[f_hash].append({'doc_id': doc_id, 'file': json_file})
            
        except Exception as e:
            print(f"Error reading {json_file}: {e}")
            
    # 2. Identify Duplicates
    hashes_map = {}
    to_keep = set()
    to_delete = set()
    
    deleted_count = 0
    
    for f_hash, docs in content_map.items():
        # Sort docs by ID string
        docs.sort(key=lambda x: x['doc_id'])
        keeper = docs[0]
        hashes_map[f_hash] = keeper['doc_id']
        to_keep.add(keeper['doc_id'])
        
        for duplicate in docs[1:]:
            print(f"Marking duplicate for deletion: {duplicate['doc_id']} (Copy of {keeper['doc_id']})")
            to_delete.add(duplicate['doc_id'])
            
    # 3. Update _hashes.json
    print("Updating _hashes.json...")
    hashes_file = session_dir / "_hashes.json"
    try:
        hashes_file.write_text(json.dumps(hashes_map, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Failed to write hashes: {e}")
        
    if not to_delete:
        print("No duplicates found.")
        return
        
    # 4. Delete Artifacts
    print(f"Deleting {len(to_delete)} duplicate documents...")
    for doc_id in to_delete:
        f = extracted_dir / f"{doc_id}.json"
        try:
            f.unlink(missing_ok=True)
            deleted_count += 1
        except Exception:
            pass
            
    # 5. Clean Struct Claim JSON
    struct_path = extracted_dir / "claims_struct.json"
    if struct_path.exists():
        try:
            existing = json.loads(struct_path.read_text(encoding='utf-8'))
            new_struct = [r for r in existing if r.get('doc_id') not in to_delete]
            if len(new_struct) < len(existing):
                struct_path.write_text(json.dumps(new_struct, ensure_ascii=False, indent=2), encoding='utf-8')
                print(f"Cleaned claims_struct.json: {len(existing)} -> {len(new_struct)} rows")
        except Exception as e:
            print(f"Error cleaning struct: {e}")

    # 6. Clean Raw Claim JSON
    raw_claims_path = extracted_dir / "claims_raw.json"
    if raw_claims_path.exists():
        try:
            existing = json.loads(raw_claims_path.read_text(encoding='utf-8'))
            new_raw = [r for r in existing if r.get('doc_id') not in to_delete]
            if len(new_raw) < len(existing):
                raw_claims_path.write_text(json.dumps(new_raw, ensure_ascii=False, indent=2), encoding='utf-8')
                print(f"Cleaned claims_raw.json: {len(existing)} -> {len(new_raw)} rows")
        except Exception as e:
            print(f"Error cleaning raw claims: {e}")
            
    print(f"Cleanup complete. Deleted {deleted_count} documents.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cleanup_duplicates(sys.argv[1])
    else:
        print("Usage: python -m backend.cleanup_duplicates <session_id>")
