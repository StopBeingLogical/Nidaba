import json
import datetime
from collections import defaultdict
import os

INPUT_FILE = '/Volumes/Shuttle/projects/nidaba/tracker/migration_tracker.json'
OUTPUT_FILE = '/Volumes/Shuttle/NIDABA_TEMPORAL_INDEX.md'
SESSION_GAP_HOURS = 4

def generate_index():
    print(f"Loading {INPUT_FILE}...")
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found.")
        return

    with open(INPUT_FILE, 'r') as f:
        data = json.load(f)

    print(f"Processing {len(data)} atoms...")
    # Handle both list and dict input if necessary, but head command showed a dict.
    if isinstance(data, dict):
        atoms = list(data.values())
    else:
        atoms = data
    
    # Filter out atoms without timestamps if any
    atoms = [a for a in atoms if 'timestamp' in a and a['timestamp']]
    
    # Sort by timestamp
    atoms.sort(key=lambda x: x['timestamp'])

    days = defaultdict(list)
    for atom in atoms:
        try:
            dt = datetime.datetime.fromisoformat(atom['timestamp'])
            # Normalize to naive UTC to avoid mixed offset issues
            if dt.tzinfo is not None:
                dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            day_str = dt.strftime('%Y-%m-%d')
            # Store the normalized dt object for sorting/comparison later
            atom['_dt'] = dt
            days[day_str].append(atom)
        except ValueError:
            continue

    print(f"Writing to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w') as out:
        out.write("# NIDABA Temporal Index\n\n")
        
        # Sort days
        for day in sorted(days.keys()):
            out.write(f"## {day}\n\n")
            
            day_atoms = days[day]
            if not day_atoms:
                continue
            
            # Already sorted by original string, but let's be sure within the day
            day_atoms.sort(key=lambda x: x['_dt'])
                
            sessions = []
            current_session = [day_atoms[0]]
            for i in range(1, len(day_atoms)):
                prev_dt = day_atoms[i-1]['_dt']
                curr_dt = day_atoms[i]['_dt']
                
                if (curr_dt - prev_dt).total_seconds() > SESSION_GAP_HOURS * 3600:
                    sessions.append(current_session)
                    current_session = [day_atoms[i]]
                else:
                    current_session.append(day_atoms[i])
            sessions.append(current_session)
            
            for session in sessions:
                start_dt = session[0]['_dt']
                end_dt = session[-1]['_dt']
                
                topics = set()
                for a in session:
                    if 'topic' in a and a['topic']:
                        topics.add(a['topic'])
                
                # Filter noise: Ignore 'markdown' if other specific topics exist
                if len(topics) > 1 and 'markdown' in topics:
                    topics.remove('markdown')
                
                sorted_topics = sorted(list(topics))
                topics_str = ", ".join(sorted_topics)
                
                start_time = start_dt.strftime('%H:%M:%S')
                end_time = end_dt.strftime('%H:%M:%S')
                
                out.write(f"### Session: {start_time} - {end_time}\n")
                out.write(f"- **Topics:** {topics_str}\n")
                out.write(f"- **Atoms:** {len(session)}\n\n")

    print(f"Index generated at {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_index()
