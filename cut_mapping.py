"""Shop-specific cut recognition and output names; never controls cutter hardware."""
OPERATIONS = ('thru', 'kiss', 'contour')


def defaults():
    rules=[]
    for operation, layers, spots in (
        ('thru',['Thru-cut','thru-cut','LNThru-cut'],['CutContour_Thru-cut','CutContourThruCut']),
        ('kiss',['Kiss-cut','kiss-cut','LNKiss-cut','CutContour_Kiss-cut'],['CutContour_Kiss-cut','CutContourKissCut']),
        ('regmark',['Regmark','LNRegmark'],['Regmark','LNRegmark'])):
        for field, names in [('layer',layers),('spot',spots)]:
            rules.extend({'source':field,'match':'exact','name':name,'operation':operation} for name in names)
    return {'version':1,'rules':rules,'genericOperation':'',
            'outputs':{'thru':{'spot':'CutContour_Thru-cut','layer':'Thru-cut','toolHint':''},
                       'kiss':{'spot':'CutContour_Kiss-cut','layer':'Kiss-cut','toolHint':''},
                       'contour':{'spot':'CutContour','layer':'CutContour','toolHint':''}},
            'suspectPrefixes':['CutContour','Thru-cut','Kiss-cut','LNThru-cut','LNKiss-cut','Regmark','LNRegmark']}


def text(value, label, empty=False):
    if not isinstance(value,str) or len(value)>80 or any(ord(c)<32 or ord(c)==127 for c in value) or (not empty and not value.strip()):
        raise ValueError('Invalid cut mapping '+label+'.')
    return value.strip()


def validate(value):
    if not isinstance(value,dict) or value.get('version')!=1:
        raise ValueError('Choose a version 1 cut mapping.')
    rules=value.get('rules')
    if not isinstance(rules,list) or not 1<=len(rules)<=100:
        raise ValueError('Use between 1 and 100 cut mapping rules.')
    clean=[]
    for rule in rules:
        if not isinstance(rule,dict) or rule.get('source') not in ('spot','layer') or rule.get('match') not in ('exact','prefix') or rule.get('operation') not in (*OPERATIONS,'regmark'):
            raise ValueError('Invalid cut mapping rule.')
        item={k:rule[k] for k in ('source','match','operation')};item['name']=text(rule.get('name'),'source name')
        if any(r['source']==item['source'] and r['match']==item['match'] and r['name']==item['name'] and r['operation']!=item['operation'] for r in clean):
            raise ValueError('One source name cannot map to different cut operations.')
        if item not in clean:clean.append(item)
    generic=value.get('genericOperation','')
    if generic not in ('',*OPERATIONS):raise ValueError('Choose how unspecified cut paths should be handled.')
    outputs={}
    for operation in OPERATIONS:
        raw=value.get('outputs',{}).get(operation,{})
        outputs[operation]={k:text(raw.get(k,''),k,k=='toolHint') for k in ('spot','layer','toolHint')}
    for key in ('spot','layer'):
        if len({item[key] for item in outputs.values()})!=len(OPERATIONS):
            raise ValueError('Each cut type needs a different output '+key+' name.')
    prefixes=value.get('suspectPrefixes',[])
    if not isinstance(prefixes,list) or len(prefixes)>40:raise ValueError('Invalid cut-name prefixes.')
    return {'version':1,'rules':clean,'genericOperation':generic,'outputs':outputs,
            'suspectPrefixes':list(dict.fromkeys(text(p,'prefix') for p in prefixes))}


def classify(mapping, spot, layers, generic_spot='CutContour'):
    """Exact rules beat prefix rules for each name; contradictory evidence rejects."""
    operations=set()
    for field,names in [('spot',[spot] if spot else []),('layer',layers)]:
        for name in names:
            matches=[r for r in mapping['rules'] if r['source']==field and (name==r['name'] if r['match']=='exact' else name.startswith(r['name']))]
            exact=[r for r in matches if r['match']=='exact']
            chosen=exact or matches
            operations.update(r['operation'] for r in chosen)
    if len(operations)>1:
        raise ValueError('Conflicting cut types for spot '+str(spot or '(none)')+' on layer '+str(' / '.join(layers) or '(none)')+'. Correct the shop mapping or source file.')
    if operations:return next(iter(operations))
    if spot==generic_spot:
        if mapping['genericOperation']:return mapping['genericOperation']
        raise ValueError('Unspecified cut type for '+generic_spot+'. Choose Thru-cut, Kiss-cut or Generic cut at import, or map its source layer in the shop profile.')
    if any(name.startswith(prefix) for name in ([spot] if spot else [])+layers for prefix in mapping['suspectPrefixes']):
        raise ValueError('Unmapped cut name: '+str(spot or ' / '.join(layers))+'. Add an exact name or prefix rule in Shop / RIP profile.')
    return None


def import_mapping(value, generic_spot):
    if value is not None:return validate(value)
    # Compatibility for existing API clients: retain their explicit generic spot.
    result=defaults();result['genericOperation']='contour'
    result['outputs']['contour']={'spot':generic_spot,'layer':generic_spot,'toolHint':''}
    return validate(result)


def output_mapping(profile):
    mapping=validate(profile['cutMapping']) if profile.get('cutMapping') else defaults()
    if not profile.get('cutMapping'):
        mapping['outputs']['contour'].update(spot=profile.get('cutSpot') or 'CutContour',layer=profile.get('cutLayer') or profile.get('cutSpot') or 'CutContour')
    return validate(mapping)


def counts(piece):
    return {op:sum(path['operation']==op for path in piece['cutPaths']) for op in OPERATIONS}
