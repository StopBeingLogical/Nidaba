import json
import re
import os
from datetime import datetime, timedelta
from collections import defaultdict

# Constants
TEMPORAL_INDEX_PATH = "/Volumes/Shuttle/NIDABA_TEMPORAL_INDEX.md"
TRACKER_PATH = "/Volumes/Shuttle/projects/nidaba/tracker/migration_tracker.json"
OUTPUT_PATH = "/Volumes/Shuttle/NIDABA_LAB_EVOLUTION.md"
PYTHON_VENV = "/Volumes/Shuttle/projects/nidaba/venv/bin/python3"

def parse_temporal_index(path):
    sessions = []
    current_date = None
    
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        # Match Date: ## 2025-10-04
        date_match = re.match(r'^## (\d{4}-\d{2}-\d{2})', line)
        if date_match:
            current_date = date_match.group(1)
            continue
            
        # Match Session: ### Session: 01:52:42 - 04:23:51
        session_match = re.match(r'^### Session: (\d{2}:\d{2}:\d{2}) - (\d{2}:\d{2}:\d{2})', line)
        if session_match and current_date:
            start_time = session_match.group(1)
            end_time = session_match.group(2)
            sessions.append({
                'date': current_date,
                'start_time': start_time,
                'end_time': end_time,
                'topics': [],
                'atom_count': 0
            })
            continue
            
        if sessions:
            # Match Topics: - **Topics:** conversation: Stop Being Logical Art
            topics_match = re.match(r'^- \*\*Topics:\*\* (.*)', line)
            if topics_match:
                topics_str = topics_match.group(1)
                sessions[-1]['topics'] = [t.strip() for t in topics_str.split(',')]
                continue
            
            # Match Atoms: - **Atoms:** 3
            atoms_match = re.match(r'^- \*\*Atoms:\*\* (\d+)', line)
            if atoms_match:
                sessions[-1]['atom_count'] = int(atoms_match.group(1))
                continue
                
    return sessions

def load_tracker(path):
    print(f"Loading tracker from {path}...")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_atom_sample(source_path):
    if not os.path.exists(source_path):
        return None
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            lines = [f.readline().strip() for _ in range(5)]
            return " ".join([l for l in lines if l])
    except:
        return None

def synthesize():
    sessions = parse_temporal_index(TEMPORAL_INDEX_PATH)
    tracker = load_tracker(TRACKER_PATH)
    
    # Index tracker by date for fast lookup
    print("Indexing atoms by date...")
    atoms_by_date = defaultdict(list)
    for uuid, atom in tracker.items():
        ts_str = atom.get('timestamp')
        if ts_str:
            # Format: 2026-02-08T01:09:52.270000
            date_part = ts_str.split('T')[0]
            atoms_by_date[date_part].append(atom)
            
    # Group sessions by Month
    monthly_groups = defaultdict(list)
    for s in sessions:
        month = s['date'][:7] # YYYY-MM
        monthly_groups[month].append(s)
        
    eras = []
    decision_log = []
    
    # Reasoning logic for Eras and Decisions
    # We define eras based on the dominant topics in the sessions
    era_definitions = [
        {"name": "The Retro-Foundations", "keywords": ["C++", "4X", "retro", "Apple II", "Win95", "SanctuaryRPG"], "weight": 1},
        {"name": "The Infrastructure Pivot", "keywords": ["Proxmox", "TrueNAS", "server", "ZFS", "NAS", "Ryzen", "OMV", "setup"], "weight": 2},
        {"name": "The Cognitive Integration", "keywords": ["AI", "LLM", "Orchestrator", "Logos", "Praxis", "Atlas", "Daemon", "Ephemera", "Qwen", "OpenAI"], "weight": 3},
        {"name": "The Great Ingestion", "keywords": ["google_takeout", "jsonl", "migration", "takeout"], "weight": 4},
        {"name": "The High-Performance Leap", "keywords": ["7800XT", "Arrow Lake", "GPU", "CUDA", "Lane Philosophy", "architecture"], "weight": 5}
    ]
    
    current_era = None
    
    output = []
    output.append("# NIDABA LAB EVOLUTION\n")
    
    # Decision Log Collection
    decisions = []
    
    # Group sessions by Week
    weekly_groups = defaultdict(list)
    for s in sessions:
        dt = datetime.strptime(s['date'], "%Y-%m-%d")
        week = dt.strftime("%Y-W%U")
        weekly_groups[week].append(s)
        
    # Iterate through weeks to build history
    sorted_weeks = sorted(weekly_groups.keys())
    
    era_history = []
    
    for week in sorted_weeks:
        week_sessions = weekly_groups[week]
        all_topics = " ".join([" ".join(s['topics']) for s in week_sessions]).lower()
        
        # Determine Era for this week - find highest weight match
        best_era_name = current_era if current_era else era_definitions[0]['name']
        current_weight = next((ed['weight'] for ed in era_definitions if ed['name'] == current_era), 0) if current_era else 0
        max_weight = -1
        candidate_era = None
        
        for ed in era_definitions:
            if any(k.lower() in all_topics for k in ed['keywords']):
                if ed['weight'] > max_weight:
                    max_weight = ed['weight']
                    candidate_era = ed['name']
        
        if candidate_era and max_weight >= current_weight:
            best_era_name = candidate_era
                
        if current_era != best_era_name:
            current_era = best_era_name
            era_history.append({"era": current_era, "start": week})
            
        # Extract decisions
        if "proxmox" in all_topics and "truenas" in all_topics:
            decisions.append(f"{week}: Pivot to TrueNAS for ZFS simplicity and storage-centric architecture.")
        if "7800xt" in all_topics or "gpu" in all_topics:
            decisions.append(f"{week}: Adoption of high-end GPU for local LLM acceleration.")
        if "logos" in all_topics or "orchestrator" in all_topics:
            decisions.append(f"{week}: Shift towards 'Logos' as the central project orchestrator.")
        if "google_takeout" in all_topics:
            decisions.append(f"{week}: Initiation of massive data ingestion (Google Takeout) for personal memory mapping.")
        if "lane philosophy" in all_topics:
            decisions.append(f"{week}: Formalization of 'Lane Philosophy' for hardware abstraction.")

    # Build Eras Section
    output.append("## The Eras\n")
    for e in era_history:
        output.append(f"- **{e['era']}** (Started {e['start']})")
    output.append("")

    # Build Decision Log
    output.append("## The Decision Log\n")
    unique_decisions = []
    seen_decisions = set()
    for d in decisions:
        simplified = d.split(": ")[1]
        if simplified not in seen_decisions:
            unique_decisions.append(d)
            seen_decisions.add(simplified)
            
    for d in unique_decisions:
        output.append(f"- {d}")
    output.append("")

    # Build Evolution History (Grouped by Week)
    output.append("## Evolutionary Milestones\n")
    for week in sorted_weeks:
        week_sessions = weekly_groups[week]
        all_topics = " ".join([" ".join(s['topics']) for s in week_sessions]).lower()
        topic_counts = defaultdict(int)
        total_atoms = 0
        for s in week_sessions:
            total_atoms += s['atom_count']
            for t in s['topics']:
                topic_counts[t] += 1
        
        if not topic_counts: continue
        
        top_topic = max(topic_counts, key=topic_counts.get)
        clean_topic = top_topic.replace('conversation: ', '')
        
        # Attempt to get a sample for the core revelation
        revelation = f"Intensive work on {clean_topic}."
        
        # Specific revelation overrides
        if "TrueNAS" in all_topics: revelation = "Realization that ZFS reliability is paramount for long-term data integrity."
        elif "AI" in all_topics or "Daemon" in all_topics: revelation = "Shift from passive data storage to active cognitive orchestration."
        elif "google_takeout" in all_topics: revelation = "Scaling the system to handle hundreds of thousands of personal data atoms."
        elif "lane philosophy" in all_topics: revelation = "Decoupling architectural intent from specific hardware constraints."
        
        # Add high-level synthesis
        output.append(f"### Week of {week}")
        output.append(f"- **Primary Focus:** {clean_topic}")
        output.append(f"- **Core Revelation:** {revelation}")
        output.append(f"- **Activity:** {len(week_sessions)} sessions, {total_atoms} atoms.")
        output.append("")


    # Build Current Trajectory
    output.append("## Current Trajectory\n")
    last_week = sorted_weeks[-1]
    last_topics = " ".join([" ".join(s['topics']) for s in weekly_groups[last_week]]).lower()
    
    trajectory = "Consolidating infrastructure and expanding AI capabilities."
    if "lane philosophy" in last_topics or "architecture" in last_topics:
        trajectory = "Deepening architectural rigor with a focus on 'Lane Philosophy'—abstracting hardware implementation from logical intent."
    elif "logos" in last_topics or "orchestrator" in last_topics:
        trajectory = "Finalizing the 'Logos' orchestrator to serve as the central nervous system of the lab."
    elif "takeout" in last_topics or "google_takeout" in last_topics:
        trajectory = "Completing the massive data ingestion phase and transitioning to automated classification and memory synthesis."
        
    output.append(f"Based on the most recent activity in week {last_week}, the project is moving towards:")
    output.append(f"> {trajectory}")
    output.append("\nFuture focus appears to be on seamless multi-node orchestration and refined data classification.")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(output))
    
    print(f"Synthesis complete. Output written to {OUTPUT_PATH}")

if __name__ == "__main__":
    synthesize()
