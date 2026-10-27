"""Contained network diagrams from already adopted common blocks, not file names or gold."""
import re

NETWORK=re.compile(r'방화벽|스위치|라우터|외부망|전용회선|보안\s*[·ㆍ]?\s*네트워크|\b(?:firewall|switch|router|fortigate|vpn)\b',re.I)

def network_diagrams(blocks):
    result={}
    for did,items in blocks.items():
        proofs=[]
        for block in items.values():
            visual=block.get('visual',{})
            if block.get('type')!='figure' or visual.get('kind')!='diagram':continue
            nodes={n['node_id']:n for n in visual.get('nodes',[])}
            # Only use connections already serialized for factual indexing. A retained
            # raw model figure, a title, or a textual promise of a diagram is insufficient.
            adopted=[b for b in items.values() if block['block_id'] in b.get('context_ids',[])
                     and 'deterministic_serialization_of_reviewed_visual_structure' in b.get('warnings',[])
                     and b.get('text','').startswith('구성도 연결선:')]
            links=[r for r in visual.get('relations',[]) if r.get('from_node') in nodes and r.get('to_node') in nodes
                   and r['from_node']!=r['to_node']]
            linked={r[k] for r in links for k in ['from_node','to_node']}
            network_labels=[n['label'] for key,n in nodes.items() if key in linked and NETWORK.search(n.get('label',''))]
            adopted=[b for b in adopted if NETWORK.search(b['text'])]
            if not adopted or not network_labels:continue
            proofs.append({'kind':'network_diagram','block_id':block['block_id'],'loc':block['loc'],
              'network_labels':network_labels,'indexed_evidence_block_ids':[b['block_id'] for b in adopted],
              'basis':'adopted_visual_connections','source_warnings':block.get('warnings',[])})
        if proofs:result[did]=proofs
    return result
