"""Contract tests for durable settlement, publication, authorization and jobs."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import io
import json
import tempfile
import threading
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.db import connection, close_old_connections
from django.utils import timezone
from PIL import Image
from mahjong_legend.engine import GameConfig, play_round
from . import game
from .domain import baseline_config, validate_config, digest, ENGINE_HASH
from .models import Draft, ActiveRelease, Release, PlayerSession, SpinTicket, SpinRequest, Round, LedgerEntry, Job, Asset
from .releases import bootstrap, active_release, validate_draft, publish, activate
from .jobs import run_one

def owner():
    return get_user_model().objects.create_superuser('owner',password='local-test-only-long-passphrase')

class StudioEngineTests(TestCase):
    def setUp(self):
        bootstrap();self.user=owner();self.player,_,_=game.obtain()
    def draft(self,edit=None):
        c=deepcopy(active_release().config)
        if edit: edit(c)
        return Draft.objects.create(name='Candidate',config=c,base_release=active_release(),created_by=self.user)
    def spin(self,player=None,**overrides):
        player=player or self.player;s=game.state(player)
        return game.spin(player,overrides.get('bet',s['spin_price']),overrides.get('ticket_id',s['ticket']['id']),overrides.get('key',uuid.uuid4()))
    def test_exact_legacy_math_hash_and_seed_are_preserved(self):
        s=game.state(self.player);t=SpinTicket.objects.get(pk=s['ticket']['id'])
        result=self.spin()
        self.assertEqual(result['round'],play_round(t.secret_seed,GameConfig()))
        self.assertEqual(s['config_sha256'],GameConfig().digest)
        self.assertNotIn('secret_seed',json.dumps(s))
        self.assertNotIn(t.secret_seed,json.dumps(s))
    def test_idempotency_survives_reloaded_session_objects(self):
        s=game.state(self.player);key=uuid.uuid4()
        first=self.spin(key=key);again=game.spin(PlayerSession.objects.get(pk=self.player.pk),'1',s['ticket']['id'],key)
        self.assertEqual(first,again);self.assertEqual(Round.objects.count(),1)
        self.assertEqual(LedgerEntry.objects.filter(kind='round').count(),1)
        self.assertEqual(SpinRequest.objects.count(),1)
    def test_conflicting_payload_same_key_rejected(self):
        s=game.state(self.player);key=uuid.uuid4();self.spin(key=key)
        with self.assertRaisesRegex(game.GameError,'another request'): game.spin(self.player,'2',s['ticket']['id'],key)
        self.assertEqual(Round.objects.count(),1)
    def test_consumed_ticket_new_key_cannot_settle_again(self):
        s=game.state(self.player);self.spin()
        with self.assertRaisesRegex(game.GameError,'already settled'): self.spin(ticket_id=s['ticket']['id'])
    def test_foreign_ticket_rejected(self):
        other,_,_=game.obtain();s=game.state(other)
        with self.assertRaisesRegex(game.GameError,'not owned'): self.spin(ticket_id=s['ticket']['id'])
    def test_failed_computation_does_not_debit(self):
        before=self.player.balance
        with patch('game_studio.game.play_round',side_effect=RuntimeError('guard')):
            with self.assertRaisesRegex(game.GameError,'no virtual credits'): self.spin()
        self.player.refresh_from_db();self.assertEqual(self.player.balance,before)
        self.assertEqual(Round.objects.count(),0);self.assertEqual(LedgerEntry.objects.filter(kind='round').count(),0)
    def test_ticket_keeps_old_bet_policy_across_publication(self):
        old=game.state(self.player)
        d=self.draft(lambda c:c['bet'].update(options=['2','5'],default='2'))
        validate_draft(d);new=publish(d,self.user,'Bet policy update')
        result=game.spin(self.player,'1',old['ticket']['id'],uuid.uuid4())
        self.assertEqual(result['stake_virtual_credits'],'1.000000')
        self.assertEqual(result['state']['bet_options'],['2','5'])
        self.assertNotEqual(result['round_release_id'],str(new.id))
        self.assertEqual(result['state']['manifest']['release_id'],str(new.id))
        self.assertEqual(result['round_manifest']['bet']['default'],'1')
    def test_release_change_does_not_change_replay(self):
        first=self.spin();d=self.draft(lambda c:c['presentation'].update(big_win_x=30))
        validate_draft(d);publish(d,self.user,'Visual threshold')
        self.assertTrue(game.verify(self.player,first['round'])['valid'])
        tampered=deepcopy(first['round']);tampered['total_payout_x']='123'
        self.assertFalse(game.verify(self.player,tampered)['valid'])
    def test_changed_math_publish_requires_fresh_validation_job(self):
        d=self.draft(lambda c:c['math'].update(scatter_probability_per_reel=.081));validate_draft(d)
        with self.assertRaisesRegex(ValueError,'Math Lab'): publish(d,self.user,'Math changed')
        Job.objects.create(kind='simulate',status='succeeded',created_by=self.user,request={'config_hash':'stale','engine_hash':ENGINE_HASH},result={'rounds':1000000,'independent_validation':True,'failures':0})
        with self.assertRaisesRegex(ValueError,'Math Lab'): publish(d,self.user,'Still stale')
    def test_edit_invalidates_validation_binding(self):
        d=self.draft();validate_draft(d);d.config['presentation']['big_win_x']=30;d.revision+=1;d.save()
        with self.assertRaisesRegex(ValueError,'exact draft'): publish(d,self.user,'Stale validation')
    def test_rollback_keeps_existing_ticket(self):
        initial=active_release();d=self.draft(lambda c:c['bet'].update(default='2'));validate_draft(d)
        published=publish(d,self.user,'New default');new,_,_=game.obtain()
        current=game.state(new);activate(initial,self.user,'Restore baseline')
        self.assertEqual(game.state(new)['ticket']['id'],current['ticket']['id'])
        r=self.spin(new,bet='2');self.assertEqual(r['round_release_id'],str(published.id))
        self.assertEqual(r['state']['manifest']['release_id'],str(initial.id))
    def test_expired_ticket_cannot_be_debited(self):
        s=game.state(self.player);SpinTicket.objects.filter(pk=s['ticket']['id']).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaisesRegex(game.GameError,'expired'): game.spin(self.player,'1',s['ticket']['id'],uuid.uuid4())
        self.assertNotEqual(game.state(self.player)['ticket']['id'],s['ticket']['id'])
    def test_pending_reset_and_second_stake_are_rejected(self):
        s=game.state(self.player);SpinTicket.objects.filter(pk=s['ticket']['id']).update(status='pending',stake='1',lease_until=timezone.now()+timedelta(seconds=60))
        with self.assertRaisesRegex(game.GameError,'pending'): game.reset(self.player)
        with self.assertRaisesRegex(game.GameError,'change its stake'): self.spin(bet='2')
    def test_stale_worker_fence_cannot_double_settle(self):
        s=game.state(self.player);key=uuid.uuid4();seen=[]
        def evaluator(seed,cfg):
            seen.append(seed)
            if len(seen)==1:
                SpinTicket.objects.filter(pk=s['ticket']['id']).update(lease_until=timezone.now()-timedelta(seconds=1))
                game.spin(self.player,'1',s['ticket']['id'],key)
            return play_round(seed,cfg)
        with patch('game_studio.game.play_round',side_effect=evaluator): self.spin(key=key)
        self.assertEqual(len(seen),2);self.assertEqual(Round.objects.count(),1)
        self.assertEqual(SpinTicket.objects.get(pk=s['ticket']['id']).fence,2)
        self.assertEqual(LedgerEntry.objects.filter(kind='round').count(),1)
    def test_preview_isolated_from_live_balance(self):
        from .releases import make_release
        r=make_release(baseline_config(),'Preview',self.user,preview=True)
        preview,_,_=game.obtain(preview_release=r);self.spin(preview)
        self.player.refresh_from_db();self.assertEqual(self.player.balance,Decimal('1000'))
        self.assertEqual(game.state(preview)['manifest']['release_id'],str(r.id))
    def test_failed_stale_worker_returns_already_settled_response(self):
        s=game.state(self.player);key=uuid.uuid4();seen=[];responses=[]
        def evaluator(seed,cfg):
            seen.append(seed)
            if len(seen)==1:
                SpinTicket.objects.filter(pk=s['ticket']['id']).update(lease_until=timezone.now()-timedelta(seconds=1))
                responses.append(game.spin(self.player,'1',s['ticket']['id'],key))
                raise RuntimeError('Original worker failed after takeover settled')
            return play_round(seed,cfg)
        with patch('game_studio.game.play_round',side_effect=evaluator): result=self.spin(key=key)
        self.assertEqual(result,responses[0]);self.assertEqual(LedgerEntry.objects.filter(kind='round').count(),1)
    @override_settings(STUDIO_MAX_SESSIONS=1)
    def test_capacity_keeps_existing_session_usable(self):
        with self.assertRaisesRegex(game.GameError,'capacity'): game.obtain()
        self.assertEqual(self.spin()['state']['spin_count'],1)
    def test_asset_type_and_bet_precision_cannot_cross_schema(self):
        c=baseline_config();c['tiles']['A']['normal']='/assets/audio/sfx/spin.wav'
        self.assertFalse(validate_config(c)['valid'])
    def test_silence_is_explicit_null_and_grid_is_integer(self):
        for value in ({},False,0):
            c=baseline_config();c['audio']['music']['base']=value
            self.assertFalse(validate_config(c)['valid'])
        c=baseline_config();c['audio']['music']['base']=None
        self.assertTrue(validate_config(c)['valid'])
        c=baseline_config();c['math']['grid']=[4.0,5.0,5.0,5.0,4.0]
        self.assertFalse(validate_config(c)['valid'])
        c=baseline_config();c['scene']['crown']={}
        self.assertFalse(validate_config(c)['valid'])
    def test_baseline_music_loop_must_fit_real_clip(self):
        d=self.draft(lambda c:c['audio']['music']['base'].update(loop_start=100))
        result=validate_draft(d)
        self.assertFalse(result['valid'])
        self.assertTrue(any('loop exceeds' in e for e in result['errors']))
        c=baseline_config();c['bet'].update(options=['1.0000000000001'],default='1.0000000000001')
        self.assertFalse(validate_config(c)['valid'])
    def test_strict_schema_rejects_unbounded_and_nonfinite_inputs(self):
        for edit in (lambda c:c['math']['symbols'].update(A=10000000),
                     lambda c:c['math'].update(scatter_probability_per_reel=float('nan')),
                     lambda c:c['math'].update(base_multipliers=[]),
                     lambda c:c['bet'].update(options=['1','1']),
                     lambda c:c['tiles']['A'].update(normal='https://evil.example/tile.png'),
                     lambda c:c['audio']['events']['tap'].update(gain=99),
                     lambda c:c.update(tiles=[])):
            c=baseline_config();edit(c);self.assertFalse(validate_config(c)['valid'])

class StudioApiTests(TestCase):
    def setUp(self):
        call_command('bootstrap_studio',stdout=io.StringIO());self.user=owner();self.client.force_login(self.user)
    def post(self,path,data,client=None,**headers): return (client or self.client).post(path,json.dumps(data),content_type='application/json',**headers)
    def test_anonymous_cannot_read_or_edit_studio(self):
        anonymous=Client()
        for path in ('overview','drafts','assets','jobs','releases'):
            self.assertEqual(anonymous.get('/api/studio/'+path).status_code,401)
        self.assertEqual(self.post('/api/studio/drafts',{'name':'hack'},anonymous).status_code,401)
    def test_csrf_is_required_for_authenticated_writes(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(self.post('/api/studio/drafts',{'name':'No CSRF'},client).status_code,403)
        session=client.get('/api/studio/session').json()
        self.assertEqual(self.post('/api/studio/drafts',{'name':'With CSRF'},client,HTTP_X_CSRFTOKEN=session['csrf_token']).status_code,201)
    def test_editor_cannot_publish_or_rollback(self):
        editor=get_user_model().objects.create_user('editor',password='testing-only-long-password')
        editor.groups.add(Group.objects.get(name='Editor'));self.client.force_login(editor)
        d=self.post('/api/studio/drafts',{'name':'Editor draft'}).json()
        self.assertEqual(self.post(f"/api/studio/drafts/{d['id']}/publish",{'revision':1,'reason':'No'}).status_code,403)
        self.assertEqual(self.post(f'/api/studio/releases/{active_release().id}/activate',{'reason':'No'}).status_code,403)
    def test_revision_conflict_prevents_lost_update(self):
        d=self.post('/api/studio/drafts',{'name':'Draft'}).json();path='/api/studio/drafts/'+d['id']
        self.assertEqual(self.client.patch(path,json.dumps({'revision':1,'name':'New name'}),content_type='application/json').status_code,200)
        self.assertEqual(self.client.patch(path,json.dumps({'revision':1,'name':'Stale'}),content_type='application/json').status_code,409)
        self.assertEqual(self.client.get(path).json()['name'],'New name')
    def test_public_spin_requires_ticket_key_and_same_origin(self):
        client=Client();s=client.get('/api/state').json()
        headers={'HTTP_X_ML_REQUEST':'local-demo'}
        self.assertEqual(self.post('/api/spin',{'bet':'1'},client,**headers).status_code,428)
        data={'bet':'1','ticket_id':s['ticket']['id'],'idempotency_key':str(uuid.uuid4())}
        self.assertEqual(self.post('/api/spin',data,client,**headers,HTTP_ORIGIN='https://evil.example').status_code,403)
        first=self.post('/api/spin',data,client,**headers)
        self.assertEqual(first.status_code,200,first.content)
        self.assertEqual(self.post('/api/spin',data,client,**headers).json(),first.json())
    def test_legacy_session_gets_explicit_cutover_notice(self):
        client=Client();client.cookies['MLSESSION']='legacy-session'
        self.assertIn('migration_notice',client.get('/api/state').json())
    @override_settings(STUDIO_SETUP_TOKEN='a-long-random-test-token-not-for-production')
    def test_setup_cannot_replace_existing_owner(self):
        c=Client();r=self.post('/api/studio/setup',{'token':settings_token(),'username':'second','password':'a-long-new-test-password'},c)
        self.assertEqual(r.status_code,409)
    def test_signed_preview_is_bound_to_editor(self):
        d=self.post('/api/studio/drafts',{'name':'Preview'}).json()
        result=self.post(f"/api/studio/drafts/{d['id']}/preview",{'revision':1})
        self.assertEqual(result.status_code,200,result.content)
        token=result.json()['url'].rsplit('/',1)[-1]
        self.assertEqual(Client().get('/api/preview/'+token+'/state').status_code,403)
        preview=self.client.get('/api/preview/'+token+'/state')
        self.assertTrue(preview.json()['preview'])
    def test_nonfinite_json_rejected(self):
        r=self.client.post('/api/studio/drafts','{"name":NaN}',content_type='application/json')
        self.assertEqual(r.status_code,400)
    def test_baseline_import_is_allowlisted(self):
        r=self.post('/api/studio/assets/import-baseline',{'path':'../../etc/passwd'})
        self.assertEqual(r.status_code,400)
    def test_small_math_job_reports_real_uncertainty_and_cannot_satisfy_publish_gate(self):
        d=self.post('/api/studio/drafts',{'name':'Math'}).json()
        r=self.post(f"/api/studio/drafts/{d['id']}/simulate",{'revision':1,'rounds':100,'target_rtp':97})
        self.assertEqual(r.status_code,202,r.content);self.assertTrue(run_one())
        j=Job.objects.get(pk=r.json()['job']['id']);self.assertEqual(j.status,'succeeded',j.error)
        self.assertEqual(j.result['rounds'],100);self.assertEqual(len(j.result['cohorts']),2)
        self.assertFalse(j.result['publish_sample_gate']);self.assertEqual(j.result['failures'],0)
    def test_ingested_tile_becomes_private_derivative_then_public_on_publish(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        image=io.BytesIO();Image.new('RGBA',(32,48),'red').save(image,format='PNG')
        with tempfile.TemporaryDirectory() as temp,override_settings(STUDIO_MEDIA_ROOT=temp):
            r=self.client.post('/api/studio/assets',{'kind':'tile','file':SimpleUploadedFile('tile.png',image.getvalue(),'image/png')})
            self.assertEqual(r.status_code,202,r.content);run_one()
            job=Job.objects.get(pk=r.json()['job']['id']);self.assertEqual(job.status,'succeeded',job.error)
            asset=Asset.objects.get(pk=job.result['asset_id'])
            self.assertEqual([asset.metadata['width'],asset.metadata['height']],[218,327])
            public=f'/media/{asset.id}/{asset.sha256}'
            self.assertEqual(Client().get(public).status_code,404)
            d=Draft.objects.create(name='Tile update',config=baseline_config(),base_release=active_release(),created_by=self.user)
            d.config['tiles']['A']['normal']=str(asset.id);d.save();validate_draft(d);publish(d,self.user,'Tile artwork')
            self.assertEqual(Client().get(public).status_code,200)
            self.assertEqual(Client().get(f'/api/studio/assets/{asset.id}/content').status_code,401)
    def test_cancelled_job_is_not_executed(self):
        j=Job.objects.create(kind='simulate',created_by=self.user)
        self.post(f'/api/studio/jobs/{j.id}/cancel',{})
        self.assertFalse(run_one());j.refresh_from_db();self.assertEqual(j.status,'cancelled')

def settings_token():
    from django.conf import settings
    return settings.STUDIO_SETUP_TOKEN

class PostgreSQLConcurrencyTests(TransactionTestCase):
    def test_simultaneous_spin_never_double_debits(self):
        if connection.vendor!='postgresql': self.skipTest('Requires PostgreSQL row locks; covered by CI PostgreSQL service')
        bootstrap();player,_,_=game.obtain();s=game.state(player);key=uuid.uuid4();started=threading.Event();release=threading.Event();out=[]
        def slow(seed,cfg):
            started.set();release.wait(10);return play_round(seed,cfg)
        def first():
            close_old_connections()
            try: out.append(game.spin(PlayerSession.objects.get(pk=player.pk),'1',s['ticket']['id'],key))
            finally: close_old_connections()
        with patch('game_studio.game.play_round',side_effect=slow):
            thread=threading.Thread(target=first);thread.start();self.assertTrue(started.wait(10))
            try:
                with self.assertRaisesRegex(game.GameError,'processing'): game.spin(player,'1',s['ticket']['id'],key)
            finally: release.set();thread.join(15)
        self.assertFalse(thread.is_alive());self.assertEqual(len(out),1)
        self.assertEqual(Round.objects.count(),1);self.assertEqual(LedgerEntry.objects.filter(kind='round').count(),1)
        self.assertEqual(game.spin(player,'1',s['ticket']['id'],key),out[0])
