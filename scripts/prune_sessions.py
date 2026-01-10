
import sys
import shutil
import re
from pathlib import Path

# Fix path
sys.path.append(str(Path.cwd()))
from backend.session import SESSION_ROOT

# UUID pattern (approximate)
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

def prune_sessions():
    print(f"Scanning {SESSION_ROOT} for stale sessions...")
    if not SESSION_ROOT.exists():
        print("Session root not found.")
        return

    keep_count = 0
    delete_count = 0
    deleted_sessions = []

    for item in SESSION_ROOT.iterdir():
        if not item.is_dir():
            continue
            
        name = item.name
        
        if not item.is_dir():
            continue
            
        name = item.name
        
        # ALLOWLIST
        if name in ["Founder", "DebugChat", "profile-test-session", "recon-test-session", "test-session", "testsession1"]:
            print(f"Keeping named session: {name}")
            keep_count += 1
            continue
            
        # Delete EVERYTHING else (UUIDs, Hex strings, etc)
        print(f"Deleting stale session: {name}")
        try:
            shutil.rmtree(item)
            delete_count += 1
            deleted_sessions.append(name)
        except Exception as e:
            print(f"Failed to delete {name}: {e}")

    print(f"\nCleanup Complete.")
    print(f"Deleted {delete_count} sessions.")
    print(f"Kept {keep_count} sessions.")

if __name__ == "__main__":
    prune_sessions()
