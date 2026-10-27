#!/usr/bin/env python3
"""肖像画像を Wikimedia Commons から images/ に保存します。

オンライン環境でプロジェクトのルートから実行:
    python3 scripts/download_portraits.py

画像ごとのライセンスは CREDITS.md と portraits.json の sourcePage を確認してください。
"""
from pathlib import Path
from urllib.request import Request, urlopen
import json, sys, time
ROOT=Path(__file__).resolve().parent.parent
manifest=json.loads((ROOT/'portraits.json').read_text(encoding='utf-8'))
out=ROOT/'images'; out.mkdir(exist_ok=True)
items=manifest['portraits']; failed=[]
for i,p in enumerate(items,1):
    target=ROOT/p['local'].removeprefix('./')
    if target.exists() and target.stat().st_size>1000:
        print(f'[{i}/{len(items)}] 既存 {target.name}'); continue
    req=Request(p['src'],headers={'User-Agent':'AmericaBowlStudyGuide/1.0 (educational use)'})
    try:
        with urlopen(req,timeout=25) as r: data=r.read()
        if len(data)<1000: raise RuntimeError('画像ファイルが小さすぎます')
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
        print(f'[{i}/{len(items)}] 保存 {target.name} ({len(data)//1024} KB)')
    except Exception as e:
        failed.append((p['nameEn'],str(e))); print(f'[{i}/{len(items)}] 失敗 {p["nameEn"]}: {e}')
    time.sleep(.08)
if failed:
    print(f'完了: {len(items)-len(failed)}/{len(items)}枚。失敗分はオンライン表示で補われます。')
    sys.exit(1)
print(f'完了: {len(items)}枚を images/ に保存しました。')
