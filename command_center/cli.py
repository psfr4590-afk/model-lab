from __future__ import annotations
import argparse, json
from .service import init,add,ingest,stage,status,groups

def main(argv=None):
    p=argparse.ArgumentParser(prog="run_pipeline.py",description="Model Lab · M²S Model Training Pipeline")
    sub=p.add_subparsers(dest="cmd")
    sub.add_parser("init"); sub.add_parser("status"); sub.add_parser("web"); sub.add_parser("groups")
    ds=sub.add_parser("dataset"); dss=ds.add_subparsers(dest="action")
    a=dss.add_parser("add"); a.add_argument("--name",required=True); a.add_argument("--description",default=""); a.add_argument("--group-id",default=None)
    dss.add_parser("list")
    s=dss.add_parser("status"); s.add_argument("--id",type=int,required=True)
    i=dss.add_parser("ingest"); i.add_argument("--id",type=int,required=True); i.add_argument("--path",required=True)
    st=sub.add_parser("stage"); st.add_argument("name",choices=["crawl","clean","dedup","weight","tokenize","shard","train","export"]); st.add_argument("--id",type=int,required=True)
    t=sub.add_parser("train"); t.add_argument("--id",type=int,required=True)
    args=p.parse_args(argv)
    if args.cmd=="init": out=init()
    elif args.cmd=="status": out=status()
    elif args.cmd=="groups": out=groups()
    elif args.cmd=="web":
        import uvicorn
        from .config import load_pipeline_config
        cfg=load_pipeline_config(); host=cfg.get("command_center",{}).get("host","127.0.0.1"); port=int(cfg.get("command_center",{}).get("port",8000))
        uvicorn.run("command_center.web:app",host=host,port=port,reload=False); return
    elif args.cmd=="dataset" and args.action=="add": out=add(args.name,args.description,args.group_id)
    elif args.cmd=="dataset" and args.action=="list": out=status()
    elif args.cmd=="dataset" and args.action=="status": out=status(args.id)
    elif args.cmd=="dataset" and args.action=="ingest": out=ingest(args.id,args.path)
    elif args.cmd=="stage": out=stage(args.id,args.name)
    elif args.cmd=="train": out=stage(args.id,"train")
    else: p.print_help(); return
    print(json.dumps(out,indent=2,ensure_ascii=False,default=str))

if __name__ == "__main__":
    main()
