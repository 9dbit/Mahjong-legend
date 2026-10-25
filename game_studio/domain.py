"""Version-one declarative configuration. No scripts or per-player odds."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math
import uuid
from pathlib import Path
from mahjong_legend.engine import GameConfig, canonical_json, sha256

ENGINE_HASH = sha256((Path(__file__).resolve().parents[1] / 'mahjong_legend/engine.py').read_bytes())
SYMBOLS = 'ABCDEFGHIJKLMNOWS'
EVENTS = {'tap':'button', 'spin':'spin', 'stop':'reel_stop', 'break':'tile_break',
          'cascade':'cascade', 'wild':'wild', 'multiplier':'multiplier', 'scatter':'scatter',
          'bonus':'bonus', 'win':'win', 'bigwin':'win'}
BASE_TILES = {s:{v:f'/assets/portrait-v085/tiles/{s}-{v}.webp' for v in ('normal','gold')} for s in SYMBOLS}
BASE_AUDIO = {e:f'/assets/audio/sfx/{v}.wav' for e,v in EVENTS.items()}
BASE_MUSIC = '/assets/approved-v082/audio/jade_serenity.m4a'
BASELINE_REFS = {p for v in BASE_TILES.values() for p in v.values()} | set(BASE_AUDIO.values()) | {BASE_MUSIC}
BASELINE_KINDS = {**{p:'tile' for v in BASE_TILES.values() for p in v.values()},
                  **{p:'audio' for p in BASE_AUDIO.values()},BASE_MUSIC:'audio'}

def digest(data):
    return sha256(canonical_json(data))

def baseline_config():
    return {'schema_version':1, 'math':deepcopy(GameConfig().raw),
        'bet':{'options':['0.2','0.5','1','2','5','10'],'default':'1','initial_balance':'1000',
               'auto_counts':[10,25,50,100], 'auto_stop_on_bonus':True,'auto_stop_on_win_x':None},
        'presentation':{'big_win_x':20,'mega_win_x':50,'animation_speed':1},
        'tiles':deepcopy(BASE_TILES),
        'scene':{'background':None,'crown':None,'board':None,'footer':None},
        'audio':{'output_gain':1.3,'buses':{'music':1,'reels':1,'wins':1,'ui':1},
            'events':{e:{'asset':BASE_AUDIO[e],'gain':.8 if e=='tap' else .85 if e=='break' else .7,
                        'bus':'ui' if e=='tap' else 'wins' if e in ('win','bigwin','bonus') else 'reels',
                        'enabled':True} for e in EVENTS},
            'music':{'base':{'asset':BASE_MUSIC,'gain':1,'loop_start':0,'loop_end':None},'bonus':None}}}

def decimal_value(value, low, high, label):
    if not isinstance(value, (str,int,float)) or isinstance(value,bool):
        raise ValueError(f'{label}: expected a decimal value')
    try: d = Decimal(str(value))
    except InvalidOperation as exc: raise ValueError(f'{label}: invalid decimal') from exc
    if not d.is_finite() or not Decimal(str(low)) <= d <= Decimal(str(high)):
        raise ValueError(f'{label}: must be between {low} and {high}')
    return d

def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label}: integer {low}–{high} required')
    return value

def asset_refs(config):
    for s, variants in config['tiles'].items():
        for state, ref in variants.items(): yield ref, 'tile', f'tiles.{s}.{state}'
    for slot, ref in config['scene'].items():
        if ref: yield ref, 'scene', f'scene.{slot}'
    for name, value in config['audio']['events'].items():
        if value.get('enabled') and value.get('asset'): yield value['asset'], 'audio', f'audio.events.{name}'
    for name, value in config['audio']['music'].items():
        if value and value.get('asset'): yield value['asset'], 'audio', f'audio.music.{name}'

def validate_config(config):
    errors, warnings = [], []
    try:
        if not isinstance(config, dict) or config.get('schema_version') != 1:
            raise ValueError('schema_version must be 1')
        if set(config) != {'schema_version','math','bet','presentation','tiles','scene','audio'}:
            raise ValueError('Configuration contains missing or unknown sections')
        if len(canonical_json(config)) > 150000: raise ValueError('Configuration too large')
        raw = config['math']
        if set(raw) != set(GameConfig().raw): raise ValueError('Math keys must match the supported engine schema')
        if raw['grid'] != [4,5,5,5,4] or any(type(v) is not int for v in raw['grid']): raise ValueError('This renderer supports integer 4/5/5/5/4 only')
        if set(raw['symbols']) != set('ABCDEFGHIJKLMNO'): raise ValueError('Ordinary symbols must be A–O')
        for s,v in raw['symbols'].items(): integer(v,1,100,f'weight {s}')
        if sum(raw['symbols'].values()) != 100: raise ValueError('Symbol weights must total 100')
        if set(raw['paytable']) != set('ABCDEFGHIJKLMNO'): raise ValueError('Paytable must contain A–O')
        for s, values in raw['paytable'].items():
            if not isinstance(values,list) or len(values)!=3: raise ValueError(f'{s}: 3/4/5 reel pay values required')
            for v in values: decimal_value(v,0,1000,f'paytable {s}')
        for key in ['base_multipliers','bonus_multipliers']:
            values = raw[key]
            if not isinstance(values,list) or len(values)!=4: raise ValueError(f'{key}: four steps required by this renderer')
            for v in values: integer(v,1,100,key)
        for key in ['scatter_probability_per_reel','enhanced_probability_reels_2_to_4']:
            decimal_value(raw[key],0,.25,key)
        integer(raw['free_spins_for_3_scatters'],1,50,'free spins')
        integer(raw['extra_free_spins_per_additional_scatter'],0,10,'extra free spins')
        integer(raw['bonus_all_enhanced_reel'],2,4,'enhanced bonus reel')
        for key in ['paytable_scale_base','paytable_scale_bonus']: decimal_value(raw[key],.000001,100,key)
        decimal_value(raw['max_round_payout_x'],1,10000,'round cap')
        GameConfig(raw)
        bet=config['bet']; options=bet['options']
        if not isinstance(options,list) or not 1<=len(options)<=20 or any(not isinstance(v,str) for v in options):
            raise ValueError('Bet options: 1–20 string denominations required')
        values=[decimal_value(v,.01,10000,'bet') for v in options]
        if any(len(v)>40 or Decimal(v).as_tuple().exponent < -12 for v in options):
            raise ValueError('Bet denomination supports at most 12 decimal places and 40 characters')
        if sorted(set(values))!=values: raise ValueError('Bet options must be unique and increasing')
        if str(bet['default']) not in options: raise ValueError('Default bet must be an offered denomination')
        decimal_value(bet['initial_balance'],0,100000000,'initial balance')
        if not isinstance(bet['auto_counts'],list) or not 1<=len(bet['auto_counts'])<=8: raise ValueError('Auto counts required')
        for v in bet['auto_counts']: integer(v,1,1000,'Auto count')
        if type(bet['auto_stop_on_bonus']) is not bool: raise ValueError('auto_stop_on_bonus must be boolean')
        if bet.get('auto_stop_on_win_x') is not None: decimal_value(bet['auto_stop_on_win_x'],.01,10000,'Auto win stop')
        p=config['presentation']
        big=decimal_value(p['big_win_x'],1,10000,'big win')
        mega=decimal_value(p['mega_win_x'],1,10000,'mega win')
        if mega<big: raise ValueError('Mega win threshold must be at least Big win')
        decimal_value(p['animation_speed'],.5,2,'animation speed')
        if set(config['tiles'])!=set(SYMBOLS): raise ValueError('All 17 tile symbols are required')
        for s, v in config['tiles'].items():
            if set(v)!= {'normal','gold'} or any(not isinstance(r,str) or not r for r in v.values()):
                raise ValueError(f'Tile {s}: normal and gold images are required')
        if set(config['scene']) != {'background','crown','board','footer'}: raise ValueError('Unknown scene slot')
        if any(v is not None and (not isinstance(v,str) or not v) for v in config['scene'].values()):
            raise ValueError('Scene slots must be null or a verified image asset ID')
        a=config['audio']; decimal_value(a['output_gain'],0,2,'audio output gain')
        if set(a['buses'])!={'music','reels','wins','ui'}: raise ValueError('Audio buses must include music/reels/wins/ui')
        for v in a['buses'].values(): decimal_value(v,0,2,'bus gain')
        if set(a['events'])!=set(EVENTS): raise ValueError('All audio event slots must be configured')
        for name,e in a['events'].items():
            if type(e['enabled']) is not bool: raise ValueError(f'{name}: enabled must be boolean')
            if e['enabled'] and not e.get('asset'): raise ValueError(f'{name}: choose a sound or disable explicitly')
            if e['bus'] not in a['buses'] or e['bus']=='music': raise ValueError(f'{name}: invalid SFX bus')
            decimal_value(e['gain'],0,2,name+' gain')
        if set(a['music'])!={'base','bonus'}: raise ValueError('Music slots must be base/bonus')
        for v in a['music'].values():
            if v is not None:
                if not isinstance(v,dict) or not isinstance(v.get('asset'),str) or not v['asset']:
                    raise ValueError('Music must be null for no sound, or reference a verified audio asset')
                decimal_value(v['gain'],0,2,'music gain')
                start=decimal_value(v.get('loop_start',0),0,120,'loop start')
                if v.get('loop_end') is not None and decimal_value(v['loop_end'],0,120,'loop end')<=start:
                    raise ValueError('Music loop end must follow start')
        for ref,kind,label in asset_refs(config):
            if not isinstance(ref,str) or len(ref)>200: raise ValueError(label+': invalid asset reference')
            if ref.startswith('/') and ref not in BASELINE_REFS: raise ValueError(label+': unrecognized baseline asset')
            if ref in BASELINE_REFS and BASELINE_KINDS[ref]!=kind: raise ValueError(label+': asset type does not match the slot')
            if ref not in BASELINE_REFS:
                try: uuid.UUID(ref)
                except ValueError as exc: raise ValueError(label+': choose a verified asset ID') from exc
        if digest(raw)!=GameConfig().digest:
            warnings.append('Math differs from the baseline. Independent Math Lab validation is required before publication; an estimate is not a guaranteed RTP.')
        if float(raw['scatter_probability_per_reel'])>.15:
            warnings.append('High scatter rate may produce long bonus chains; computation guard failures block publication.')
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,InvalidOperation) as exc:
        errors.append(str(exc))
    return {'valid':not errors,'errors':errors,'warnings':warnings}
