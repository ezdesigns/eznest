import base64
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
import job_drafts
import job_workspaces
import server
import test_job_workspaces as workspaces
from test_pdf_production import pdf_fixture, document_job


class DraftTests(unittest.TestCase):
    handler = workspaces.DesignerJobTests.handler
    setUp = workspaces.DesignerJobTests.setUp
    tearDown = workspaces.DesignerJobTests.tearDown
    request = workspaces.DesignerJobTests.request
    workspace = workspaces.DesignerJobTests.workspace
    wait_ready = workspaces.DesignerJobTests.wait_ready

    def payload(self, name, forms=False):
        code, data = self.request(name, '/api/document/import', {'content':base64.b64encode(pdf_fixture(forms=forms)).decode(), 'preserveArtwork':True})
        self.assertEqual(code, 200, data)
        data['format'] = 'pdf'
        raw = json.dumps(data)
        key = hashlib.sha256(raw.encode()).hexdigest()
        return {'revision':None, 'entries':[{'id':'web-one-0','name':name+'.pdf','sourceFile':name+'.pdf','revision':data['documentId'],'role':'required','sets':2,'dataKey':key}], 'fields':{'material':'roll', 'nesting-effort':'5'}, 'assets':{key:raw}}, data

    def test_drafts_survive_restart_are_private_and_do_not_nest_or_use_stock(self):
        payload, data = self.payload('Alice')
        with self.workspace('Alice'): source = server.job_root()/'documents'/(data['documentId']+'.pdf')
        before = source.read_bytes()
        stock = self.request('Alice','/api/materials')[1]
        code, saved = self.request('Alice','/api/work/draft',payload)
        self.assertEqual(code,200,saved)
        self.assertEqual(self.request('Alice','/api/state')[1], {'status':'idle'})
        self.assertEqual(self.request('Bob','/api/work/draft')[1]['draft'],None)
        self.assertEqual(self.request(None,'/api/work/draft')[1]['draft'],None)
        self.assertEqual(self.request('Bob','/api/document/source/'+data['documentId'])[0],404)
        self.assertEqual(self.request('Alice','/api/document/source/'+data['documentId'])[1],pdf_fixture())
        with job_workspaces._guard:
            for key in list(job_workspaces._workspaces):
                if key[0] == self.root: del job_workspaces._workspaces[key]
        result=self.request('Alice','/api/work/draft')[1]
        self.assertEqual(result['draft']['entries'][0]['sets'],2)
        self.assertEqual(result['assets'][payload['entries'][0]['dataKey']],data)
        self.assertEqual(self.request('Bob','/api/materials')[1],stock)
        self.assertEqual(source.read_bytes(),before)

    def test_stale_tab_cannot_save_clear_or_nest_over_latest_draft(self):
        payload,data=self.payload('Alice')
        self.assertEqual(self.request('Alice','/api/work/draft',payload)[0],200)
        for path,request in [('/api/work/draft',payload),('/api/work/discard',{}),('/api/solve',document_job(data))]:
            code,result=self.request('Alice',path,request)
            self.assertEqual(code,409,(path,result))
            self.assertEqual(result['code'],'draft_conflict')
        saved=self.request('Alice','/api/work/draft')[1]
        payload.update(revision=saved['revision'],assets={})
        payload['entries'][0]['sets']=7
        self.assertEqual(self.request('Alice','/api/work/draft',payload)[0],200)
        latest=self.request('Alice','/api/work/draft')[1]
        self.assertEqual(latest['draft']['entries'][0]['sets'],7)
        self.assertEqual(self.request('Alice','/api/work/discard',{'draftRevision':latest['revision']})[0],200)
        self.assertIsNone(self.request('Alice','/api/work/draft')[1]['draft'])
        self.assertEqual(self.request('Alice','/api/work/draft',payload)[0],409)

    def test_staging_artwork_does_not_publish_or_replace_a_job(self):
        payload,data=self.payload('Alice')
        key=payload['entries'][0]['dataKey']
        staged={'revision':None,'dataKey':key,'raw':payload['assets'][key],'role':'required'}
        self.assertEqual(self.request('Alice','/api/work/draft/artwork',staged)[0],200)
        self.assertIsNone(self.request('Alice','/api/work/draft')[1]['draft'])
        self.assertEqual(self.request('Bob','/api/work/draft/artwork',staged)[0],400)
        payload['assets']={}
        self.assertEqual(self.request('Alice','/api/work/draft',payload)[0],200)
        self.assertEqual(self.request('Alice','/api/work/draft/artwork',staged)[0],409)
        self.assertEqual(self.request('Alice','/api/work/draft')[1]['assets'][key],data)

    def test_failed_save_and_foreign_artwork_keep_previous_draft(self):
        payload,data=self.payload('Alice')
        saved=self.request('Alice','/api/work/draft',payload)[1]
        payload['revision']=saved['revision']
        bad=copy.deepcopy(payload);bad['assets'][bad['entries'][0]['dataKey']]+=' '
        self.assertEqual(self.request('Alice','/api/work/draft',bad)[0],400)
        foreign=copy.deepcopy(payload);foreign['revision']=None
        self.assertEqual(self.request('Bob','/api/work/draft',foreign)[0],400)
        with patch.object(job_drafts,'atomic',side_effect=OSError('test full disk')):
            self.assertEqual(self.request('Alice','/api/work/draft',payload)[0],400)
        self.assertEqual(self.request('Alice','/api/work/draft')[1]['revision'],saved['revision'])

    def test_ready_result_stays_bound_to_draft_and_clear_preserves_other_person(self):
        payload,data=self.payload('Alice')
        revision=self.request('Alice','/api/work/draft',payload)[1]['revision']
        bob,_=self.payload('Bob',True)
        self.assertEqual(self.request('Bob','/api/work/draft',bob)[0],200)
        code, started=self.request('Alice','/api/solve',{**document_job(data),'draftRevision':revision})
        self.assertEqual(code,200,started)
        state=self.wait_ready('Alice')
        saved=self.request('Alice','/api/work/draft')[1]
        self.assertEqual(saved['runId'],state['id'])
        self.assertEqual(saved['revision'],started['draftRevision'])
        code,released=self.request('Alice','/api/release',{'id':state['id'],'map':'<svg xmlns="http://www.w3.org/2000/svg"/>','downloadOnly':True})
        self.assertEqual(code,200,released)
        receipt={'id':state['id'],'sha256':released['sha256'],'name':'print finished','format':'pdf'}
        self.assertEqual(self.request('Bob','/api/export/receipt',receipt)[0],400)
        self.assertEqual(self.request('Alice','/api/export/receipt',receipt)[0],200)
        self.assertEqual(self.request('Alice','/api/state')[1]['exportReceipt']['path'],'print finished.pdf')

        self.assertEqual(self.request('Alice','/api/work/discard',{'draftRevision':saved['revision']})[0],200)
        self.assertIsNotNone(self.request('Bob','/api/work/draft')[1]['draft'])
