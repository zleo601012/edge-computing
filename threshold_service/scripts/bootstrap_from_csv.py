import argparse, json
import pandas as pd
import httpx

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--n", type=int, default=720)
    ap.add_argument("--chunk", type=int, default=200)
    ap.add_argument("--metrics", default="COD_mg_L,NH3N_mg_L,TN_mg_L,TP_mg_L,BOD_mg_L,NO3_NO2_mg_L,EC_uS_cm,pH,DO_mg_L")
    args = ap.parse_args()

    metrics = args.metrics.split(",")
    df = pd.read_csv(args.csv, low_memory=False)
    assert "node_id" in df.columns

    obs = []
    for node_id, g in df.groupby("node_id"):
        g = g.head(args.n)
        for _, row in g.iterrows():
            values = {}
            for m in metrics:
                if m in row and pd.notna(row[m]):
                    values[m] = float(row[m])
            if values:
                obs.append({"node_id": node_id, "values": values})

    # 分批提交
    with httpx.Client(timeout=30.0) as client:
        for i in range(0, len(obs), args.chunk):
            batch = obs[i:i+args.chunk]
            r = client.post(f"{args.url}/ingest_batch", json=batch)
            r.raise_for_status()
            print(r.json())

if __name__ == "__main__":
    main()
