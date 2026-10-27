"""Read-only source/summary display for the named completed documents."""
from adapter import *
import argparse
ap=argparse.ArgumentParser();ap.add_argument('doc_ids',nargs='+');ap.add_argument('--sources',action='store_true');args=ap.parse_args()
gold={g['doc_id']:g for g in read(PREP/'private/gold.json')}
for did in args.doc_ids:
    env=read(OUT/'results/enrichment'/did/'envelope.json')
    c=ec.loads(env['response']['choices'][0]['message']['content'])
    p=read(PREP/'public/inputs'/f'{did}.json')
    print('DOCUMENT',did,'RESPONSE_HASH',digest(env))
    print('SUMMARY',json.dumps(c.get('summary'),ensure_ascii=False))
    print('GOLD',json.dumps(gold[did]['summary_facts'],ensure_ascii=False))
    if args.sources:
        for b in p['document']['blocks']:
            print('BLOCK',json.dumps(b,ensure_ascii=False))
