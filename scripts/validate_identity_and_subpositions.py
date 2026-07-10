from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CATEGORIES,
    classify_name_type,
    generate_player,
    load_master_data,
    name_matches_nationality,
    normalize_sub_positions,
    birthplace_matches_nationality,
)
from scripts.validate_ability_balance import flatten_players  # noqa: E402

ROLES = ["投手", "野手"]
BAD_LEFT_POSITIONS = {"捕手", "二塁手", "三塁手", "遊撃手"}
FIELDER_POSITIONS = {"捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"}
MAIN_RATING = "◎"
RATING_SCORE = {"◎": 3, "○": 2, "△": 1, "": 0}
JP_PREFECTURES = {"北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県","茨城県","栃木県","群馬県","埼玉県","千葉県","東京都","神奈川県","新潟県","富山県","石川県","福井県","山梨県","長野県","岐阜県","静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県","奈良県","和歌山県","鳥取県","島根県","岡山県","広島県","山口県","徳島県","香川県","愛媛県","高知県","福岡県","佐賀県","長崎県","熊本県","大分県","宮崎県","鹿児島県","沖縄県"}
US_STATES = {"アラバマ州","アラスカ州","アリゾナ州","アーカンソー州","カリフォルニア州","コロラド州","コネチカット州","デラウェア州","フロリダ州","ジョージア州","ハワイ州","アイダホ州","イリノイ州","インディアナ州","アイオワ州","カンザス州","ケンタッキー州","ルイジアナ州","メイン州","メリーランド州","マサチューセッツ州","ミシガン州","ミネソタ州","ミシシッピ州","ミズーリ州","モンタナ州","ネブラスカ州","ネバダ州","ニューハンプシャー州","ニュージャージー州","ニューメキシコ州","ニューヨーク州","ノースカロライナ州","ノースダコタ州","オハイオ州","オクラホマ州","オレゴン州","ペンシルベニア州","ロードアイランド州","サウスカロライナ州","サウスダコタ州","テネシー州","テキサス州","ユタ州","バーモント州","バージニア州","ワシントン州","ウェストバージニア州","ウィスコンシン州","ワイオミング州"}

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument('--count',type=int,default=5000)
    p.add_argument('--seed',type=int,default=202607090000)
    p.add_argument('--output-dir',type=Path,default=ROOT/'reports'/'identity_subposition_balance_5000')
    return p.parse_args()

def generate_samples(count:int, seed:int):
    master=load_master_data(); players=[]; off=0
    for role in ROLES:
        for cat in CATEGORIES:
            print(f"{role} / {cat} 生成中", flush=True)
            for _ in range(count):
                players.append(generate_player(role, cat, master, seed+off)); off+=1
    return players, master

def pct(n,d): return round(n/max(1,d)*100,2)

def split_tb(v):
    m=re.match(r'(右投|左投)(右打|左打|両打)', str(v)); return m.groups() if m else ('','')

SCHEMAS = {
    'throw_position_consistency_warnings.csv': ['seed','選手名','カテゴリ','投球','メインポジション','サブポジ','警告タイプ','severity'],
    'sub_position_rating_warnings.csv': ['seed','選手名','メインポジション','サブポジション','サブポジ評価','能力値','警告理由','severity'],
    'name_nationality_warnings.csv': ['seed','選手名','カテゴリ','国籍','名前種別','警告タイプ','severity'],
    'name_format_warnings.csv': ['seed','選手名','国籍','警告理由','severity'],
    'region_consistency_warnings.csv': ['seed','選手名','国籍','出身地','警告タイプ','severity'],
    'name_duplicate_summary.csv': ['集計','値','人数','割合%'],
}

def write(df, out, name):
    if df.empty and name in SCHEMAS:
        df = pd.DataFrame(columns=SCHEMAS[name])
    df.to_csv(out/name, index=False, encoding='utf-8-sig')

def parse_subs(value):
    if isinstance(value, str):
        try:
            return normalize_sub_positions(ast.literal_eval(value))
        except (ValueError, SyntaxError):
            pass
    return normalize_sub_positions(value)

def main():
    a=parse_args(); a.output_dir.mkdir(parents=True, exist_ok=True)
    players, master=generate_samples(a.count, a.seed); df=flatten_players(players)
    write(df, a.output_dir, 'generated_players.csv')
    tb=[]
    for (cat, role), g in df.groupby(['category','role']):
        vals=g['batting_throwing'].map(split_tb)
        tmp=pd.DataFrame(vals.tolist(), columns=['投球','打席'])
        for (th,ba), c in tmp.value_counts().items(): tb.append({'カテゴリ':cat,'対象':role,'投球':th,'打席':ba,'人数':int(c),'割合%':pct(c,len(g))})
    write(pd.DataFrame(tb), a.output_dir, 'throw_bat_distribution.csv')
    warnings=[]; rating_warn=[]; count_rows=[]; pair=[]
    fielders=df[df.role=='野手']
    for _,r in fielders.iterrows():
        subs=parse_subs(r['サブポジJSON'])
        if r.handedness=='左投' and r.position in BAD_LEFT_POSITIONS: warnings.append({'seed':r.seed,'選手名':r['name'],'カテゴリ':r.category,'投球':r.handedness,'メインポジション':r.position,'サブポジ':r['サブポジ'],'警告タイプ':'左投げ禁止メイン','severity':'error'})
        for s in subs:
            pos=s['position']; apt=s['aptitude']
            if r.handedness=='左投' and pos in BAD_LEFT_POSITIONS: warnings.append({'seed':r.seed,'選手名':r['name'],'カテゴリ':r.category,'投球':r.handedness,'メインポジション':r.position,'サブポジ':pos,'警告タイプ':'左投げ禁止サブポジ','severity':'error'})
            if pos==r.position: rating_warn.append({'seed':r.seed,'選手名':r['name'],'メインポジション':r.position,'サブポジション':pos,'サブポジ評価':apt,'能力値':str({k:r[k] for k in ['走力','肩力','守備力','捕球']}),'警告理由':'メインと同一','severity':'error'})
            if RATING_SCORE.get(apt,0)>RATING_SCORE[MAIN_RATING]: rating_warn.append({'seed':r.seed,'選手名':r['name'],'メインポジション':r.position,'サブポジション':pos,'サブポジ評価':apt,'能力値':'','警告理由':'メイン評価超過','severity':'error'})
            if pos=='捕手' and (r['肩力']<60 or r['捕球']<45 or r['守備力']<40): rating_warn.append({'seed':r.seed,'選手名':r['name'],'メインポジション':r.position,'サブポジション':pos,'サブポジ評価':apt,'能力値':str({k:r[k] for k in ['肩力','守備力','捕球']}),'警告理由':'捕手適正能力不足','severity':'warning'})
            if pos=='遊撃手' and (r['走力']<55 or r['肩力']<55 or r['守備力']<50): rating_warn.append({'seed':r.seed,'選手名':r['name'],'メインポジション':r.position,'サブポジション':pos,'サブポジ評価':apt,'能力値':str({k:r[k] for k in ['走力','肩力','守備力']}),'警告理由':'遊撃手適正能力不足','severity':'warning'})
    write(pd.DataFrame(warnings), a.output_dir, 'throw_position_consistency_warnings.csv')
    write(pd.DataFrame(rating_warn), a.output_dir, 'sub_position_rating_warnings.csv')
    for (cat,pos),g in fielders.groupby(['category','position']):
        counts=g['サブポジ数']; count_rows.append({'カテゴリ':cat,'メインポジション':pos,'サブポジなし':int((counts==0).sum()),'1個':int((counts==1).sum()),'2個':int((counts==2).sum()),'3個以上':int((counts>=3).sum()),'平均サブポジ数':round(counts.mean(),3),'サブポジ保有率%':pct(int((counts>0).sum()),len(g))})
        main_n=len(g); c=Counter(p for val in g['サブポジJSON'] for p in [s['position'] for s in parse_subs(val)])
        for sub,n in c.items(): pair.append({'カテゴリ':cat,'メインポジション':pos,'サブポジション':sub,'人数':n,'メインポジション人数':main_n,'保有率%':pct(n,main_n)})
    write(pd.DataFrame(count_rows), a.output_dir, 'sub_position_count_distribution.csv'); write(pd.DataFrame(pair), a.output_dir, 'sub_position_pair_distribution.csv')
    nat=[]
    for (cat,role),g in df.groupby(['category','role']):
        for n,c in g.nationality.value_counts().items(): nat.append({'カテゴリ':cat,'対象':role,'国籍':n,'人数':int(c),'割合%':pct(c,len(g))})
    write(pd.DataFrame(nat), a.output_dir, 'nationality_distribution.csv')
    name_rows=[]; name_warn=[]
    for (cat,natn),g in df.groupby(['category','nationality']):
        types=g.apply(lambda r: classify_name_type(r['name'], master, r['nationality']), axis=1)
        matches=g.apply(lambda r: name_matches_nationality(r['name'], r['nationality'], master), axis=1)
        for t,c in types.value_counts().items(): name_rows.append({'カテゴリ':cat,'国籍':natn,'名前判定':t,'対象人数':len(g),'人数':int(c),'割合%':pct(c,len(g)),'一致人数':int(matches.sum()),'一致率%':pct(int(matches.sum()),len(g))})
    for _,r in df.iterrows():
        t=classify_name_type(r['name'], master, r['nationality']); ok=name_matches_nationality(r['name'], r['nationality'], master)
        if not ok and t!='複数国該当': name_warn.append({'seed':r.seed,'選手名':r['name'],'カテゴリ':r.category,'国籍':r.nationality,'名前種別':t,'警告タイプ':'国籍名前不一致','severity':'error' if t not in ('不明','複数国該当') else 'warning'})
    write(pd.DataFrame(name_rows), a.output_dir, 'name_nationality_consistency.csv'); write(pd.DataFrame(name_warn), a.output_dir, 'name_nationality_warnings.csv')
    dup=[]; fmt=[]
    for name,c in df.name.value_counts().items():
        if c>1: dup.append({'集計':'完全同姓同名','値':name,'人数':int(c),'割合%':pct(c,len(df))})
    for _,r in df.iterrows():
        parts=str(r['name']).split(' ')
        if not str(r['name']).strip() or len(parts)<2 or re.search(r'[0-9]', str(r['name'])) or (len(parts)>=2 and parts[0]==parts[-1]): fmt.append({'seed':r.seed,'選手名':r['name'],'国籍':r.nationality,'警告理由':'名前形式異常','severity':'error'})
    write(pd.DataFrame(dup), a.output_dir, 'name_duplicate_summary.csv'); write(pd.DataFrame(fmt), a.output_dir, 'name_format_warnings.csv')
    reg=[]; regw=[]
    for (natn,bp),g in df.groupby(['nationality','birthplace']): reg.append({'国籍':natn,'地域':bp,'人数':len(g),'割合%':pct(len(g),len(df[df.nationality==natn]))})
    for _,r in df.iterrows():
        if not birthplace_matches_nationality(r.birthplace, r.nationality, master): regw.append({'seed':r.seed,'選手名':r['name'],'国籍':r.nationality,'出身地':r.birthplace,'警告タイプ':'国籍地域不一致','severity':'error'})
    cov=[]
    for natn, required in [('日本',JP_PREFECTURES),('アメリカ',US_STATES)]:
        vals=set(master.places.get(natn,[])); cov.append({'国籍':natn,'必須数':len(required),'マスタ数':len(vals),'不足数':len(required-vals),'不足': ' / '.join(sorted(required-vals))})
    write(pd.DataFrame(reg), a.output_dir, 'region_distribution.csv'); write(pd.DataFrame(regw), a.output_dir, 'region_consistency_warnings.csv'); write(pd.DataFrame(cov), a.output_dir, 'region_master_coverage.csv')
    cat=[]
    df['名前種別']=df.apply(lambda r: classify_name_type(r['name'], master, r['nationality']), axis=1)
    for keys,g in df.groupby(['category','role','年齢帯','nationality','名前種別']): cat.append(dict(zip(['カテゴリ','投手野手','年齢帯','国籍','名前種別'],keys)) | {'人数':len(g),'割合%':pct(len(g),len(df[(df.category==keys[0]) & (df.role==keys[1])]))})
    write(pd.DataFrame(cat), a.output_dir, 'category_identity_summary.csv')
    review = ["# 名前・国籍・地域・サブポジ整合性レビュー", "", f"生成条件: count={a.count}, seed={a.seed}（投手/野手 × 3カテゴリ、合計{len(df)}件）", "", "## 修正必須項目", f"- 左投げ禁止ポジション警告: {len(warnings)}件", f"- 国籍・地域不整合: {len(regw)}件", f"- 名前形式警告: {len(fmt)}件", f"- サブポジ評価警告: {len(rating_warn)}件", "", "## 現状維持項目", "- 野手能力、投手能力、変化球、特殊能力、投手適正の確率・分布は変更していません。", "", "詳細は同ディレクトリの各CSVを参照してください。"]
    (a.output_dir/'identity_subposition_review.md').write_text('\n'.join(review)+'\n', encoding='utf-8')
    assert len(warnings)==0
    assert not any(not str(n).strip() for n in df.name)
    assert len(regw)==0
    assert len(fmt)==0
    assert all(not any(s['position']=='投手' for s in parse_subs(v)) for v in df['サブポジJSON'])
    assert all(len({s['position'] for s in parse_subs(v)}) == len(parse_subs(v)) for v in df['サブポジJSON'])
    assert all(not any(s['position']==pos for s in parse_subs(v)) for pos,v in zip(df.position, df['サブポジJSON'], strict=False))
    assert not any('メイン評価超過' == x.get('警告理由') for x in rating_warn)
    assert JP_PREFECTURES <= set(master.places.get('日本',[]))
    assert US_STATES <= set(master.places.get('アメリカ',[]))

if __name__ == '__main__': main()
