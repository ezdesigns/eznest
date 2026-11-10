import opt_out
import base64
import concurrent.futures
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import job_workspaces
import server
import shop_members
from update_queue import UpdateQueue
import test_shop_auth
from test_pdf_production import pdf_fixture, document_job
from test_material_inventory import values
import material_inventory


class DesignerJobTests(unittest.TestCase):
    handler = test_shop_auth.ShopAuthTests.handler

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.multiple(server, WORK=self.root, STATE={'status':'idle'}, PROCESS=None,
                                      LAN=True, PORT=8765, HOST='0.0.0.0', UPDATE_QUEUE=UpdateQueue()),
                        patch.object(server.Handler, 'allowed', return_value=True),
                        patch.object(server.Handler, 'origin_ok', return_value=True)]
        for item in self.patches:item.start()
        shop_members.create(self.root, 'Shared shop')
        self.cookies = {}
        for name in ('Alice','Bob'):
            joined = shop_members.join(self.root, shop_members.invite(self.root)['code'], name, '192.168.1.50')
            self.cookies[name] = shop_members.cookie(joined['token']).split(';')[0]

    def tearDown(self):
        for workspace in job_workspaces.all_for(self.root):
            process = workspace.process
            if process and process.poll() is None:
                process.terminate();process.wait(timeout=5)
        for item in reversed(self.patches):item.stop()
        with job_workspaces._guard:
            for key in list(job_workspaces._workspaces):
                if key[0] == self.root:del job_workspaces._workspaces[key]
        self.temp.cleanup()

    def request(self, name, path, data=None, extra=None):
        headers = {'Cookie':self.cookies[name]} if name else {'X-EZ-Token':server.TOKEN}
        headers.update(extra or {})
        h = self.handler(path, json.dumps(data or {}).encode(),
                         ip='192.168.1.50' if name else '127.0.0.1',headers=headers)
        if data is None:h.do_GET()
        else:h.handle_post()
        self.assertIsNone(job_workspaces.CURRENT.get())
        return h.sent[0][:2]

    def workspace(self, name):
        h=self.handler('/api/state',headers={'Cookie':self.cookies[name]})
        return job_workspaces.select(self.root,h.workspace_owner(),server.restore_state)

    def upload(self, name, forms=False):
        status, parsed = self.request(name,'/api/document/import',{
            'content':base64.b64encode(pdf_fixture(forms=forms)).decode(),'preserveArtwork':True})
        self.assertEqual(status,200,parsed)
        return document_job(parsed)

    def wait_ready(self, name):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            code,state=self.request(name,'/api/state')
            if state['status']!='running':
                self.assertEqual(state['status'],'ready',state)
                return state
            time.sleep(.05)
        self.fail('Designer job did not finish')

    def test_two_designers_nest_restore_export_and_discard_independently(self):
        a=self.upload('Alice');b=self.upload('Bob',forms=True)
        self.assertEqual(self.request('Alice','/api/solve',a)[0],200)
        self.assertEqual(self.request('Bob','/api/solve',b)[0],200)
        alice=self.wait_ready('Alice');bob=self.wait_ready('Bob')
        self.assertNotEqual(alice['id'],bob['id'])
        self.assertNotEqual(alice['job']['parts'][0]['documentId'],bob['job']['parts'][0]['documentId'])
        self.assertEqual(self.request(None,'/api/state')[1],{'status':'idle'})
        status,release=self.request('Alice','/api/release',{'id':alice['id'],'map':'<svg xmlns="http://www.w3.org/2000/svg"/>','downloadOnly':True})
        self.assertEqual(status,200,release)
        self.assertEqual(self.request('Alice',release['url'])[0],200)
        self.assertEqual(self.request('Bob',release['url'])[0],404)
        self.assertEqual(self.request('Bob','/api/print/'+alice['id'])[0],404)
        self.assertNotEqual(self.request('Bob','/api/release',{'id':alice['id'],'map':'<svg/>','downloadOnly':True})[0],200)
        self.assertNotEqual(self.request('Bob','/api/solve',a)[0],200)
        # Simulate a host restart: no in-memory state, same authenticated people.
        with job_workspaces._guard:
            for key in list(job_workspaces._workspaces):
                if key[0]==self.root:del job_workspaces._workspaces[key]
        self.assertEqual(self.request('Alice','/api/state')[1]['id'],alice['id'])
        self.assertEqual(self.request('Bob','/api/state')[1]['id'],bob['id'])
        self.assertEqual(self.request('Bob','/api/work/discard',{})[0],200)
        self.assertEqual(self.request('Bob','/api/state')[1],{'status':'idle'})
        self.assertEqual(self.request('Alice','/api/state')[1]['id'],alice['id'])

    def test_parallel_requests_never_swap_owners_and_stock_remains_shared(self):
        for name in self.cookies:
            with self.workspace(name):server.job_state().update(marker=name)
        def read(name):return self.request(name,'/api/state',extra={'X-EZ-Workspace':'someone-else'})[1]['marker']
        names=['Alice','Bob']*20
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(read,names)),names)
        material_inventory.save(self.root,'roll',values(),0)
        material_inventory.reserve(self.root,'roll','example',200,500,'hash')
        material_inventory.transition(self.root,'example','use')
        for name in self.cookies:
            self.assertEqual(self.request(name,'/api/materials')[1]['materials'][0]['onHandMm'],800)
            with self.workspace(name):self.assertFalse((server.job_root()/'materials.sqlite3').exists())

    def test_cancel_only_stops_the_requesting_designers_worker(self):
        processes={name:Mock() for name in self.cookies}
        for name,process in processes.items():
            process.poll.return_value=None
            with self.workspace(name):
                server.set_job_process(process)
                server.job_state().update(status='running')
        self.assertEqual(self.request('Alice','/api/cancel',{})[0],200)
        processes['Alice'].terminate.assert_called_once()
        processes['Bob'].terminate.assert_not_called()
        self.assertEqual(self.request('Bob','/api/state')[1]['status'],'running')
        for process in processes.values():process.poll.return_value=0

    def test_host_update_waits_for_every_designer(self):
        queue=server.UPDATE_QUEUE;ticket='a'*32;queue.queue(ticket)
        with self.workspace('Bob'):
            server.job_state().update(status='running')
        self.assertFalse(queue.claim(ticket,server.shop_work_state()))
        with self.workspace('Bob'):
            server.job_state().update(status='ready',deliveryCompleted=False)
        self.assertFalse(queue.claim(ticket,server.shop_work_state()))
        with self.workspace('Bob'):server.job_state()['deliveryCompleted']=True
        self.assertTrue(queue.claim(ticket,server.shop_work_state()))

    def test_existing_host_state_is_not_adopted_by_new_members(self):
        server.STATE.update(marker='old host job')
        self.assertEqual(self.request(None,'/api/state')[1]['marker'],'old host job')
        for name in self.cookies:self.assertEqual(self.request(name,'/api/state')[1],{'status':'idle'})

    def test_member_cannot_change_another_designers_stock_reservation(self):
        ident='a'*32
        material_inventory.save(self.root,'roll',values(),0)
        material_inventory.reserve(self.root,'roll',ident,200,500,'hash')
        with self.workspace('Alice'):
            server.job_state().update(id=ident)
        status,result=self.request('Bob','/api/materials/transition',{'id':ident,'action':'use'})
        self.assertEqual(status,400,result)
        self.assertIn('your own jobs',result['error'])
        self.assertEqual(self.request('Alice','/api/materials/transition',{'id':ident,'action':'use'})[0],200)
        self.assertEqual(self.request('Bob','/api/materials')[1]['materials'][0]['onHandMm'],800)

    def test_host_capacity_does_not_replace_either_designers_job(self):
        workers=[]
        for name in self.cookies:
            worker=Mock();worker.poll.return_value=None;workers.append(worker)
            with self.workspace(name):
                server.set_job_process(worker)
                server.job_state().update(status='running',marker=name)
        try:
            status,result=self.request(None,'/api/solve',{'parts':[]})
            self.assertEqual(status,400,result)
            self.assertIn('preparing two layouts',result['error'])
            for name in self.cookies:
                with self.workspace(name):self.assertEqual(server.job_state()['marker'],name)
        finally:
            for worker in workers:worker.poll.return_value=0

    def test_unreadable_membership_never_falls_back_to_the_hosts_job(self):
        server.STATE.update(marker='private host job')
        with patch.object(shop_members,'member',side_effect=OSError('private path')):
            code,result=self.request('Alice','/api/state')
        self.assertEqual(code,503)
        self.assertNotIn('marker',result)
        self.assertNotIn('private path',result['error'])
