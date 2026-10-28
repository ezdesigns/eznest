import copy
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import telemetry
import telemetry_sender as sender

TOKEN='osa_'+'A'*43
ENV={'EZ_NEST_OUTPUT_UPLOADS':'1','EZ_NEST_OUTPUT_TOKEN':TOKEN}


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.environment=patch.dict(os.environ,ENV);self.environment.start();self.addCleanup(self.environment.stop)
        self.job=json.loads((Path(__file__).resolve().parents[1]/'sample.json').read_text())

    def event(self,ident):
        telemetry.observe(self.root,ident*32,self.job,{'width':180,'usedLength':100,'area':10000,'placements':[{}],'elapsed':5})

    def agree(self):
        state=sender.status(self.root)
        return sender.consent(self.root,revision=state['revision'],version=state['consentVersion'],configurationId=state['configurationId'],confirmed=True)

    def test_default_off_missing_gate_and_no_implicit_consent(self):
        self.event('a')
        with patch.object(sender,'emit') as emit:
            self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()
            with patch.dict(os.environ,{'EZ_NEST_OUTPUT_UPLOADS':'0'}):
                self.assertFalse(sender.status(self.root)['configured'])
                with self.assertRaises(ValueError):self.agree()
                self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()

    def test_future_only_retry_same_ids_and_exact_ack(self):
        self.event('a');self.agree();self.event('b')
        sent=[]
        def send(payload,token):sent.append(copy.deepcopy(payload));self.assertEqual(token,TOKEN);return False
        with patch.object(sender,'emit',side_effect=send):self.assertEqual(sender.tick(self.root),0)
        self.assertEqual(len(telemetry.pending(self.root)),4)
        with patch.object(sender,'emit',side_effect=lambda p,t: sent.append(copy.deepcopy(p)) or True):
            self.assertEqual(sender.tick(self.root),2)
        self.assertEqual(sent[0],sent[1])
        self.assertEqual({p['nestId'] for p in sent},{'b'*32})
        self.assertEqual({p['nestId'] for p in telemetry.pending(self.root)},{'a'*32})
        self.assertTrue(sender.status(self.root)['lastDeliveredAt'])
        self.assertIsNone(sender.status(self.root)['lastError'])

    def test_revoke_and_new_consent_exclude_unsent_backlog(self):
        self.agree();self.event('a');sender.revoke(self.root)
        with patch.object(sender,'emit') as emit:self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()
        self.event('b');self.agree();self.event('c')
        with patch.object(sender,'emit',return_value=True) as emit:
            self.assertEqual(sender.tick(self.root),2)
            self.assertEqual({call.args[0]['nestId'] for call in emit.call_args_list},{'c'*32})

    def test_consent_version_stale_revision_and_changed_token_rejected(self):
        state=sender.status(self.root)
        for overrides in ({'confirmed':False},{'version':'old'},{'revision':-1},{'configurationId':'old'}):
            args=dict(revision=state['revision'],version=state['consentVersion'],configurationId=state['configurationId'],confirmed=True);args.update(overrides)
            with self.assertRaises(ValueError):sender.consent(self.root,**args)
        self.agree();self.event('a')
        with patch.dict(os.environ,{'EZ_NEST_OUTPUT_TOKEN':'osa_'+'B'*43}),patch.object(sender,'emit') as emit:
            self.assertFalse(sender.status(self.root)['enabled']);self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()
        with patch.object(sender,'CONSENT_VERSION','new'),patch.object(sender,'emit') as emit:
            self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()

    def test_reverting_config_or_version_never_revives_old_consent(self):
        for change in ('token', 'gate', 'version'):
            self.agree()
            context = patch.object(sender,'CONSENT_VERSION','changed') if change=='version' else patch.dict(os.environ, {'EZ_NEST_OUTPUT_TOKEN':'osa_'+'B'*43} if change=='token' else {'EZ_NEST_OUTPUT_UPLOADS':'0'})
            with context:
                self.assertFalse(sender.status(self.root)['enabled'])
            self.event({'token':'a','gate':'b','version':'c'}[change])
            with patch.object(sender,'emit') as emit:
                self.assertFalse(sender.status(self.root)['enabled'])
                self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()
            self.agree()
            with patch.object(sender,'emit') as emit:
                self.assertEqual(sender.tick(self.root),0);emit.assert_not_called()

    def test_revocation_waits_for_inflight_then_prevents_new_requests(self):
        self.agree();self.event('a')
        entered=threading.Event();release=threading.Event();revoked=threading.Event()
        def send(*_):entered.set();self.assertTrue(release.wait(5));return True
        with patch.object(sender,'emit',side_effect=send) as emit:
            worker=threading.Thread(target=lambda:sender.tick(self.root,limit=10));worker.start()
            self.assertTrue(entered.wait(5))
            stopper=threading.Thread(target=lambda:(sender.revoke(self.root),revoked.set()));stopper.start()
            self.assertFalse(revoked.wait(.05))
            with sender.CONTROL_LOCK:self.assertIn(str(self.root.resolve()),sender.REVOKING)
            release.set();worker.join(5);stopper.join(5)
            self.assertFalse(worker.is_alive());self.assertFalse(stopper.is_alive());self.assertTrue(revoked.is_set())
            self.assertEqual(sender.tick(self.root),0);self.assertEqual(emit.call_count,1)

    def test_candidate_maintenance_neither_uploads_nor_invalidates_rollback_consent(self):
        self.agree(); self.event('a')
        with telemetry.database(self.root) as db: before=sender.read(db)
        for version in (sender.CONSENT_VERSION, 'candidate-contract'):
            with patch.object(sender,'CONSENT_VERSION',version), patch.object(sender,'emit') as emit:
                self.assertTrue(sender.status(self.root,paused=lambda:True)['paused'])
                self.assertEqual(sender.tick(self.root,paused=lambda:True),0)
                stop=Mock(); stop.wait.side_effect=[False,True]
                sender.run(self.root,stop,paused=lambda:True)
                emit.assert_not_called()
                with telemetry.database(self.root) as db: self.assertEqual(sender.read(db),before)
        # Either rollback or successful commit opens admission again. Only a
        # committed changed contract invalidates consent and requires agreement.
        with patch.object(sender,'emit',return_value=True): self.assertEqual(sender.tick(self.root),2)
        with patch.object(sender,'CONSENT_VERSION','committed-contract'):
            self.assertFalse(sender.status(self.root)['enabled'])
        self.assertFalse(sender.status(self.root)['enabled'])

    def test_pause_between_events_stops_the_batch_without_revoking_consent(self):
        self.agree(); self.event('a')
        paused=Mock(side_effect=[False,False,True])
        with patch.object(sender,'emit',return_value=True) as emit:
            self.assertEqual(sender.tick(self.root,paused=paused),1)
            self.assertEqual(emit.call_count,1)
        self.assertTrue(sender.status(self.root)['enabled'])

    def test_both_http_status_routes_preserve_consent_during_service_maintenance(self):
        import server
        from test_telemetry import TelemetryApiTests
        helper=TelemetryApiTests(methodName='runTest'); helper.setUp()
        try:
            info=sender.status(server.WORK)
            sender.consent(server.WORK,revision=info['revision'],version=info['consentVersion'],
                           configurationId=info['configurationId'],confirmed=True)
            with telemetry.database(server.WORK) as db: before=sender.read(db)
            with patch.dict(os.environ,{'EZ_NEST_MACOS_SERVICE':'1'}), \
                 patch.dict(sys.modules,{'macos_service_runtime':SimpleNamespace(maintenance=lambda:True)}), \
                 patch.object(sender,'CONSENT_VERSION','candidate-contract'):
                for route in ('/api/telemetry/output','/api/telemetry'):
                    info=helper.request(route)
                    self.assertTrue((info.get('outputDelivery') or info)['paused'])
                with telemetry.database(server.WORK) as db: self.assertEqual(sender.read(db),before)
            with patch.dict(os.environ,{'EZ_NEST_MACOS_SERVICE':'1'}), \
                 patch.dict(sys.modules,{'macos_service_runtime':None}):
                self.assertTrue(server.telemetry_paused())
            with patch.object(server.UPDATE_QUEUE,'stopping',True):
                self.assertTrue(server.telemetry_paused())
        finally: helper.tearDown()

    def test_secret_not_saved_or_returned_and_consent_survives_reopen(self):
        self.agree();self.assertTrue(sender.status(self.root)['enabled'])
        self.assertNotIn(TOKEN,json.dumps(sender.status(self.root)))
        self.assertNotIn(TOKEN.encode(),(self.root/'telemetry.sqlite3').read_bytes())
        with telemetry.database(self.root) as db:
            self.assertTrue(sender.effective(sender.read(db),TOKEN))

    def test_large_stock_band_and_invalid_record_do_not_block_queue(self):
        self.agree()
        telemetry.record_stock(self.root,'d'*32,'e'*32,100000000,'f'*32,0)
        self.assertEqual(telemetry.pending(self.root)[0]['payload']['remainingMmBand'],'[100000000,100000250)')
        with patch.object(sender,'emit',return_value=True):self.assertEqual(sender.tick(self.root),1)
        telemetry.record_stock(self.root,'d'*32,'e'*32,100000000,'1'*32,1)
        with telemetry.database(self.root) as db:
            row=db.execute('SELECT id,atom FROM events WHERE acknowledged=0').fetchone()
            atom=json.loads(row['atom']);atom['payload']['remainingMmBand']='[1e+08,1e+08)'
            db.execute('UPDATE events SET atom=? WHERE id=?',(json.dumps(atom),row['id']))
        self.event('b')
        with patch.object(sender,'emit',return_value=True) as emit:
            self.assertEqual(sender.tick(self.root),2)
            self.assertEqual({c.args[0]['nestId'] for c in emit.call_args_list},{'b'*32})
        self.assertEqual(sender.status(self.root)['withheldEvents'],1)
        self.assertEqual(sender.status(self.root)['pendingEvents'],0)
        self.assertEqual(len(telemetry.pending(self.root)),1)

    def test_transport_requires_matching_receipt_and_never_redirects(self):
        payload={'schema':sender.SCHEMA,'requestId':'123'}
        for outcome,request_id,schema,expected in [('created','123',sender.SCHEMA,True),('replay','123',sender.SCHEMA,True),('created','other',sender.SCHEMA,False),('created','123','other',False),('ok','123',sender.SCHEMA,False)]:
            body={'outcome':outcome,'result':{'requestId':request_id,'schema':schema}}
            response=io.BytesIO(json.dumps(body).encode());response.status=200
            with patch.object(sender,'build_opener') as opener:
                opener.return_value.open.return_value=response
                self.assertEqual(sender._emit_https(payload,TOKEN),expected)
                req=opener.return_value.open.call_args.args[0]
                self.assertEqual(req.full_url,sender.ENDPOINT)
                self.assertEqual(req.get_header('Authorization'),'Bearer '+TOKEN)
                self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],10)
                self.assertIsInstance(opener.call_args.args[0],sender.NoRedirect)
        self.assertIsNone(sender.NoRedirect().redirect_request(None,None,302,'','', 'https://other.test'))


if __name__=='__main__':unittest.main()
