from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'datasets'

def load_pipeline_config():
    p = ROOT / 'config' / 'pipeline_config.yaml'
    if not p.exists(): return {}
    return yaml.safe_load(p.read_text(encoding='utf-8')) or {}

def load_groups():
    p=ROOT/'config'/'dataset_groups.yaml'
    raw=yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    return raw.get('dataset_groups',[])

def group_by_id(gid): return next((g for g in load_groups() if g.get('id')==gid),None)
