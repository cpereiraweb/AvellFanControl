"""Validate owned controls, explicitly report the observed 0741 bit-2 variation."""
REQUIRED = {'read_only','flags_07c5','flags_07c6','features_078e','mode_0751',
            'host_0741','table_0f00_0f5f'}

def assess_restoration(before, after):
    def valid(value):
        if not isinstance(value,dict) or set(value)!=REQUIRED:return False
        table=value['table_0f00_0f5f']
        if not isinstance(table,list) or len(table)!=96:return False
        if any(type(x) is not int or not 0<=x<=255 for x in table):return False
        return value['host_0741'] in (0,4) and type(value['host_0741']) is int and value['flags_07c5']==0 and value['flags_07c6']==0
    if not valid(before) or not valid(after):
        return {'controls_restored':False,'exact_match':False,'error':'Invalid baseline or automatic state'}
    differences={k:{'before':before[k],'after':after[k]} for k in REQUIRED if before[k]!=after[k]}
    bit2_only=set(differences)=={'host_0741'} and (before['host_0741'] ^ after['host_0741'])==4
    return {'controls_restored':not differences or bit2_only,
            'exact_match':not differences,
            'observed_bit2_variation':bit2_only,
            'differences':differences,
            'note':'Bit2 meaning remains undocumented; observed as both 0 and 1 with automatic control. It is never forced by this check.' if bit2_only else ''}
