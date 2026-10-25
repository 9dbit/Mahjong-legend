"""Short DB claims + fenced deterministic computation + exactly-once settlement.

Lock ordering is always PlayerSession -> SpinTicket. Never hold a database
transaction while evaluating a round. All idempotency records are retained.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import secrets
import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from mahjong_legend.engine import GameConfig, play_round, verify_round, sha256, display_decimal
from .domain import digest, ENGINE_HASH
from .models import PlayerSession, SpinTicket, SpinRequest, Round, LedgerEntry, ActiveRelease
from .releases import active_release, manifest

class GameError(ValueError):
    def __init__(self,message,code=409): self.code=code;super().__init__(message)

def money(value):
    return Decimal(value).quantize(Decimal('.000000000001'),rounding=ROUND_HALF_UP)

def _new_ticket(player,release=None):
    release=release or player.preview_release or active_release()
    if release.engine_hash!=ENGINE_HASH: raise GameError('Engine version is incompatible with the active release',503)
    seed=secrets.token_hex(32)
    player.ticket_sequence+=1;player.save(update_fields=['ticket_sequence','touched_at'])
    return SpinTicket.objects.create(session=player,sequence=player.ticket_sequence,release=release,
        secret_seed=seed,commitment=sha256(bytes.fromhex(seed)),expires_at=timezone.now()+timedelta(seconds=settings.STUDIO_TICKET_TTL_SECONDS))

def _ticket(player):
    ticket=SpinTicket.objects.select_related('release').filter(session=player,status__in=['ready','pending']).first()
    if ticket and ticket.status=='ready' and ticket.expires_at<=timezone.now():
        ticket.status='expired';ticket.save(update_fields=['status']);ticket=None
    return ticket or _new_ticket(player)

@transaction.atomic
def obtain(token=None, preview_release=None):
    if isinstance(token,str) and len(token)<=100:
        player=PlayerSession.objects.filter(token_hash=sha256(token.encode()),preview_release=preview_release).first()
        if player: return player,token,False
    # Serialize only allocation, not spins. A cookie-less flood cannot create
    # unlimited durable rows. Existing browser sessions remain usable at the cap.
    pointer=ActiveRelease.objects.select_for_update().get(pk=1)
    release=preview_release or pointer.release
    if PlayerSession.objects.count()>=settings.STUDIO_MAX_SESSIONS:
        raise GameError('Demo session capacity reached. Existing sessions remain available.',503)
    token=secrets.token_urlsafe(32)
    player=PlayerSession.objects.create(token_hash=sha256(token.encode()),balance=money(release.config['bet']['initial_balance']),preview_release=preview_release)
    LedgerEntry.objects.create(session=player,kind='initial',credit=player.balance,balance_after=player.balance)
    _new_ticket(player,release)
    return player,token,True

def _state(player,ticket=None):
    ticket=ticket or _ticket(player); cfg=GameConfig(ticket.release.config['math']);bet=ticket.release.config['bet']
    last=Round.objects.filter(session=player).order_by('-created_at').first()
    return {'game':'Mahjong Wild','version':cfg.raw['version'],'ui_version':'0.9.2',
        'balance':display_decimal(player.balance),'spin_price':str(bet['default']),
        'bet_options':bet['options'],'max_payout_x':str(cfg.cap),'spin_count':player.spins,
        'next_seed_commitment_sha256':ticket.commitment,'config_sha256':cfg.digest,
        'ticket':{'id':str(ticket.id),'sequence':ticket.sequence,'status':ticket.status,'release_id':str(ticket.release_id),
                  'expires_at':ticket.expires_at.isoformat(),'commitment':ticket.commitment,'stake':ticket.stake if ticket.status=='pending' else None},
        'rules':{'grid':list(cfg.heights),'ways':2000,'base_multipliers':list(cfg.base_mult),'bonus_multipliers':list(cfg.bonus_mult),
                 'scatter_per_reel':cfg.scatter_prob,'free_spins_for_3_scatters':cfg.raw['free_spins_for_3_scatters'],
                 'extra_free_spins':cfg.raw['extra_free_spins_per_additional_scatter'],
                 'paytable':cfg.raw['paytable'],'symbols':cfg.raw['symbols']},
        'manifest':manifest(ticket.release,private=bool(player.preview_release_id)),
        'last_round_id':last.transcript['round_id'] if last else None,
        'virtual_credits_only':True,'session_storage':'persistent','preview':bool(player.preview_release_id)}

@transaction.atomic
def state(player):
    locked=PlayerSession.objects.select_for_update().get(pk=player.pk)
    return _state(locked)

def spin(player,bet,ticket_id,key):
    try: ticket_id=uuid.UUID(str(ticket_id));key=uuid.UUID(str(key))
    except (ValueError,TypeError,AttributeError) as exc: raise GameError('Client update required: ticket and UUID idempotency_key are mandatory',428) from exc
    if not isinstance(bet,str): raise GameError('Virtual stake must be a string denomination',400)
    payload=digest({'ticket':str(ticket_id),'bet':bet})
    with transaction.atomic():
        locked=PlayerSession.objects.select_for_update().get(pk=player.pk)
        record=SpinRequest.objects.filter(session=locked,key=key).first()
        if record and record.payload_hash!=payload: raise GameError('Idempotency key was already used for another request')
        ticket=SpinTicket.objects.select_for_update(of=('self',)).select_related('release').filter(pk=ticket_id,session=locked).first()
        if not ticket: raise GameError('Ticket is not owned by this session',404)
        if record:
            finished=Round.objects.filter(ticket=ticket).first()
            if finished: return finished.response
        elif ticket.status=='consumed': raise GameError('Ticket already settled; recover the last round')
        if ticket.status not in ('ready','pending'): raise GameError('Ticket expired or was revoked. Refresh game state.')
        if ticket.status=='ready' and ticket.expires_at<=timezone.now(): raise GameError('Ticket expired. Refresh game state.')
        if ticket.release.engine_hash!=ENGINE_HASH: raise GameError('Historical engine is unavailable; no credits were debited',503)
        policy=ticket.release.config['bet']
        if bet not in policy['options']: raise GameError('Unsupported virtual stake for this ticket',400)
        stake=Decimal(bet)
        if locked.balance<stake: raise GameError('Not enough virtual credits. Reset the demo to restore them.',400)
        if ticket.status=='pending':
            if ticket.stake!=bet: raise GameError('A pending ticket cannot change its stake')
            if ticket.lease_until and ticket.lease_until>timezone.now(): raise GameError('Round is processing. Retry with the same request key.',409)
        if not record: SpinRequest.objects.create(session=locked,key=key,ticket=ticket,payload_hash=payload)
        ticket.status='pending';ticket.stake=bet;ticket.fence+=1
        ticket.lease_until=timezone.now()+timedelta(seconds=settings.STUDIO_LEASE_SECONDS)
        ticket.save(update_fields=['status','stake','fence','lease_until'])
        fence=ticket.fence;release=ticket.release;seed=ticket.secret_seed
    try:
        completed=play_round(seed,GameConfig(release.config['math']))
    except Exception:
        with transaction.atomic():
            PlayerSession.objects.select_for_update().get(pk=player.pk)
            failed=SpinTicket.objects.select_for_update().get(pk=ticket_id)
            settled=Round.objects.filter(ticket=failed).first()
            if settled: return settled.response
            if failed.status!='pending' or failed.fence!=fence:
                raise GameError('Round recovery took over this request; retry with the same key')
            if failed.status=='pending' and failed.fence==fence:
                failed.status='failed';failed.lease_until=None;failed.save(update_fields=['status','lease_until'])
        raise GameError('Round computation failed; no virtual credits were debited',422)
    with transaction.atomic():
        locked=PlayerSession.objects.select_for_update().get(pk=player.pk)
        ticket=SpinTicket.objects.select_for_update().get(pk=ticket_id)
        done=Round.objects.filter(ticket=ticket).first()
        if done: return done.response
        if ticket.status!='pending' or ticket.fence!=fence: raise GameError('Round recovery took over this request; retry with the same key')
        award=money(stake*Decimal(completed['total_payout_x']))
        locked.balance=money(locked.balance-stake+award);locked.spins+=1;locked.save(update_fields=['balance','spins','touched_at'])
        ticket.status='consumed';ticket.lease_until=None;ticket.save(update_fields=['status','lease_until'])
        result=Round.objects.create(ticket=ticket,session=locked,release=release,transcript=completed,stake=stake,award=award)
        LedgerEntry.objects.create(session=locked,round=result,kind='round',debit=stake,credit=award,balance_after=locked.balance)
        next_ticket=_new_ticket(locked)
        response={'round':completed,'stake_virtual_credits':display_decimal(stake),'win_virtual_credits':display_decimal(award),
                  'round_release_id':str(release.id),'round_manifest':manifest(release,private=bool(locked.preview_release_id)),
                  'state':_state(locked,next_ticket),'idempotency_key':str(key),'ticket_id':str(ticket.id)}
        result.response=response;result.save(update_fields=['response'])
        return response

@transaction.atomic
def reset(player):
    locked=PlayerSession.objects.select_for_update().get(pk=player.pk)
    current=_ticket(locked)
    if current.status=='pending': raise GameError('Complete or recover the pending round before reset')
    current.status='revoked';current.save(update_fields=['status'])
    release=locked.preview_release or active_release()
    before=locked.balance;locked.balance=money(release.config['bet']['initial_balance']);locked.spins=0
    locked.save(update_fields=['balance','spins','touched_at'])
    LedgerEntry.objects.create(session=locked,kind='reset',debit=before,credit=locked.balance,balance_after=locked.balance)
    return _state(locked,_new_ticket(locked))

def last_round(player):
    result=Round.objects.filter(session=player).order_by('-created_at').first()
    if not result: raise GameError('No rounds yet',404)
    return {'round':result.transcript,'release_id':str(result.release_id),'ticket_id':str(result.ticket_id)}

def verify(player,transcript):
    if not isinstance(transcript,dict): raise GameError('Round object required',400)
    record=Round.objects.filter(session=player,transcript__round_id=transcript.get('round_id')).first()
    if not record: raise GameError('Round is not in this session history',404)
    if record.release.engine_hash!=ENGINE_HASH: raise GameError('Historical evaluator unavailable',503)
    return verify_round(transcript,GameConfig(record.release.config['math']))
