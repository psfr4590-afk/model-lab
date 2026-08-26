import argparse,uvicorn
from command_center.config import load_pipeline_config
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--no-browser',action='store_true'); a=p.parse_args(); c=load_pipeline_config().get('command_center',{}); uvicorn.run('command_center.web:app',host=c.get('host','127.0.0.1'),port=int(c.get('port',8000)),reload=False)
