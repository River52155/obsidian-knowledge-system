import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
import semantic_search as sem
from memory_search import build

class FakeEncoder:
    device='test'
    def __init__(self):self.encoded=[]
    def passages(self,rows):
        for row in rows:
            for a in range(0,len(row['text']),20):
                b=min(a+20,len(row['text']));yield row['id'],a,b,Path(row['path']).stem+'\n'+row['heading']+'\n'+row['text'][a:b]
    def tokenize(self,batch,**kw):return {'input_ids':[[1]*len(t) for t in batch]}
    def encode(self,batch):
        self.encoded+=batch;v=[]
        for t in batch:
            x=np.frombuffer(hashlib.sha256(t.encode()).digest(),dtype=np.uint8).astype(np.float32);x=np.tile(x,16);v.append(x/np.linalg.norm(x))
        return np.array(v,dtype=np.float32)

class ArtifactTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.vault=self.root/'vault';(self.vault/'wiki').mkdir(parents=True);self.note=self.vault/'wiki/a.md';self.note.write_text('# 标题\n这是一段很长的合成文字，用于检查中间窗口不能缺失。'*3);self.db=self.root/'db/baseline.sqlite3';build(self.vault,self.db);self.encoder=FakeEncoder();self.patch=patch('semantic_search.get_encoder',return_value=self.encoder);self.patch.start();self.addCleanup(self.patch.stop);sem.build_embeddings(self.db,self.db.parent/'embedding-index.npz',write_report=False)
    def tearDown(self):self.tmp.cleanup()
    def mutate(self,fn):
        path=self.db.parent/'embedding-index.npz'
        with np.load(path,allow_pickle=False) as d:a={k:d[k] for k in d.files}
        fn(a);np.savez_compressed(path,**a)
    def test_empty_vectors_with_nonempty_manifest_rejected(self):
        self.mutate(lambda a:a.update({k:v[:0] for k,v in a.items() if k!='metadata'}))
        with self.assertRaises(ValueError):sem.SemanticIndex(self.db)
        self.assertFalse(sem.status(self.db)['ready'])
    def test_missing_or_duplicated_passage_rejected(self):
        self.mutate(lambda a:a.update({k:np.delete(v,1,axis=0) for k,v in a.items() if k!='metadata'}))
        with self.assertRaises(ValueError):sem.validate_index(self.db)
    def test_coordinates_and_counts_must_match(self):
        self.mutate(lambda a:a['start_chars'].__setitem__(0,9999))
        with self.assertRaises(ValueError):sem.validate_index(self.db)
    def test_empty_corpus_valid(self):
        self.note.unlink();build(self.vault,self.db);sem.build_embeddings(self.db,self.db.parent/'embedding-index.npz',write_report=False)
        self.assertEqual(sem.validate_index(self.db)['vectors'],0)
    def test_health_rejects_same_corruption_as_loader(self):
        self.mutate(lambda a:a.pop('start_chars'))
        self.assertFalse(sem.status(self.db)['ready'])
        with self.assertRaises(ValueError):sem.SemanticIndex(self.db)
    def test_validation_cache_invalidates_on_artifact_or_contract_change(self):
        self.assertEqual(sem.validate_index(self.db)['artifact_version'],2)
        self.mutate(lambda a:a['end_chars'].__setitem__(0,10000))
        self.assertFalse(sem.status(self.db)['ready'])
    def test_legacy_validated_but_marked_for_upgrade(self):
        def old(a):
            a.pop('input_keys',None);m=json.loads(str(a['metadata']));m.pop('artifact_version',None);a['metadata']=np.array(json.dumps(m))
        self.mutate(old);self.assertTrue(sem.validate_index(self.db)['upgrade_required'])
    def test_crc_corruption_is_unready_and_recovers_automatically(self):
        import zipfile,struct
        from index_updates import IndexUpdates
        update=IndexUpdates(self.db)
        update.refresh();old=update.current_db();path=old.parent/'embedding-index.npz'
        with zipfile.ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as z:
            for n,b in entries.items():z.writestr(n,b)
        with zipfile.ZipFile(path) as z:info=z.getinfo('vectors.npy')
        raw=bytearray(path.read_bytes());offset=info.header_offset+30+len(info.filename.encode())+len(info.extra);raw[offset+info.file_size-1]^=1;path.write_bytes(raw)
        self.assertFalse(sem.status(old)['ready'])
        with self.assertRaises(ValueError):sem.validate_index(old)
        update.refresh();self.assertNotEqual(update.current_db(),old);self.assertTrue(sem.status(update.current_db())['ready'])

    def test_duplicate_window_rejected_even_when_counts_match(self):
        def duplicate(a):
            for k,v in a.items():
                if k!='metadata':v[1]=v[0]
        self.mutate(duplicate)
        with self.assertRaises(ValueError):sem.validate_index(self.db)

    def test_inventory_only_changes_reuse_all_inputs(self):
        from index_updates import IndexUpdates
        update=IndexUpdates(self.db);update.refresh();self.encoder.encoded=[]
        (self.vault/'wiki/image.png').write_bytes(b'fixture');update.refresh()
        self.assertEqual(self.encoder.encoded,[])
        (self.vault/'wiki/index.md').write_text('# 导航\n仅用于导航。');update.refresh()
        self.assertEqual(self.encoder.encoded,[]);self.assertGreater(update.status()['progress']['reused_vectors'],0)
