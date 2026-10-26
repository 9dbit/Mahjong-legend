"""Full frame is a presentation change. Source tile art/outcome math stay intact."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import hashlib,json,unittest
from PIL import Image
from tools.build_fullframe_ui import QA_PATHS,rewrite_qa
from tools.qa_fullframe_v086 import assert_layout,assert_reel_order,assert_background_images
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/fullframe-v086'
class FullFrameUI(unittest.TestCase):
    def test_runtime_is_loaded(self):
        html=(ROOT/'web/index.html').read_text()
        for value in ['data-release="0.8.7"','fullframe-v086/layout.css','fullframe-v086/layout.js','soft-tech-continue']:
            self.assertIn(value,html)
        self.assertEqual(html.count('class="fullframe-art"'),1)
    def test_manifest_and_source_center_pixels(self):
        manifest=json.loads((OUT/'manifest.json').read_text())
        source=Image.open(ROOT/manifest['source']).convert('RGB')
        for name,digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((OUT/name).read_bytes()).hexdigest(),digest)
        for name in ['rail','hud','crown-center','controls-center','board-center']:
            with Image.open(OUT/f'{name}.webp') as im:
                self.assertEqual(im.convert('RGB').tobytes(),source.crop(tuple(manifest['slices'][name])).tobytes())
    def test_undistorted_dragon_and_banner_derivatives(self):
        data=json.loads((OUT/'manifest.json').read_text())['ornament_derivatives']
        self.assertEqual(data['tail_source_crop_start'],525)
        self.assertEqual(data['tail_overlap_fraction_of_tile_width'],.08)
        self.assertEqual(data['tail_zoom'],1.42)
        for name,digest in data['files'].items():
            self.assertEqual(hashlib.sha256((OUT/name).read_bytes()).hexdigest(),digest)
        expected={'tail-left.webp':(118,413),'tail-right.webp':(117,413),
                  'notice-left.webp':(226,109),'notice-center.webp':(16,109),
                  'notice-right.webp':(226,109)}
        for name,shape in expected.items():
            with self.subTest(name=name),Image.open(OUT/name) as art:
                self.assertEqual(art.size,shape)
                if name.startswith('tail-'):
                    self.assertEqual(art.mode,'RGBA')
                    self.assertEqual(art.getchannel('A').getextrema(),(0,255))
                    self.assertEqual(art.getchannel('A').crop((0,0,shape[0],1)).getextrema(),(0,0))
                else:
                    self.assertEqual(art.mode,'RGB')

    def test_layout_cannot_issue_rounds(self):
        js=(OUT/'layout.js').read_text()
        for token in ['/api/spin','Math.random','balance=','fetch(']:self.assertNotIn(token,js)
        self.assertIn('visualViewport',js)
        self.assertIn('view.scale',js)
    def test_fullframe_css_does_not_restore_height_based_width_clamp(self):
        css=(OUT/'layout.css').read_text()
        self.assertIn('width:var(--ff-width,100vw)',css)
        self.assertIn('aspect-ratio:auto',css)
        self.assertIn('max-width:none',css)
        self.assertIn('aspect-ratio:1',css)
    def test_fullframe_release_and_cache(self):
        r=json.loads((OUT/'release.json').read_text())
        self.assertEqual((r['release'],r['math_version'],r['tile_ratio']),('0.8.7','0.8.0','2:3'))
        self.assertIn('presentation-087',(ROOT/'web/sw.js').read_text())

class GeneratedQAContracts(unittest.TestCase):
    @staticmethod
    def covered_geometry():
        def box(x,y,w,h,**extra):
            return {'x':x,'y':y,'w':w,'h':h,'right':x+w,'bottom':y+h,**extra}
        painted={'visible':True,'image':True,'size':'cover'}
        bands=[]
        for name,top,height,split in [('art-crown',20,110,True),('art-rail',130,40,False),
                                     ('art-board',170,280,True),('art-hud',450,90,False),
                                     ('art-controls',540,120,True)]:
            band=box(0,top,390,height,name=name,**painted)
            band['parts']=[box(x,top,130,height,**painted) for x in (0,130,260)] if split else []
            bands.append(band)
        return {
            'stage':box(0,0,390,690,**painted),'board':box(50,120,290,300),
            'notice':box(50,430,290,40),'meters':box(10,490,370,30),
            'controls':box(10,540,370,80),'logo':box(90,10,179,67.5),
            'disk':box(150,550,60,60),'tiles':[2/3]*23,'overflow':[0,0],
            'buttons':[box(10,50,32,32),box(348,50,32,32)]
                      +[box(x,550,60,60) for x in (10,80,150,220,290)],
            'viewport':{'layoutWidth':390,'layoutHeight':690,'visualWidth':390,'visualHeight':690,'standalone':False},
            'root':box(0,0,390,690,**painted),'body':box(0,0,390,690,**painted),
            'backdrop':box(0,0,390,690,active=True,**painted),
            'art':{'container':box(0,0,390,690,visible=True),
                   'before':box(0,0,390,20,active=True,**painted),
                   'bands':bands,'after':box(0,660,390,30,active=True,**painted)},
        }

    def test_generated_suites_are_complete_compilable_and_idempotent(self):
        # Exercise the actual build outputs, including the older locked/motion
        # suites that previously retained a fixed whole-stage ratio.
        for name in QA_PATHS:
            with self.subTest(path=name):
                generated=(ROOT/name).read_text()
                compile(generated,name,'exec')
                self.assertEqual(rewrite_qa(name,generated),generated)

    def test_unknown_geometry_gate_fails_build_instead_of_silently_skipping(self):
        name='tools/qa_locked_ui.py'
        generated=(ROOT/name).read_text()
        changed=generated.replace('            assert_layout(page,w,h)',
                                  '            assert True  # unexpected upstream edit')
        self.assertNotEqual(changed,generated)
        with self.assertRaisesRegex(ValueError,'source drift'):
            rewrite_qa(name,changed)

    def test_full_width_gate_still_rejects_distorted_tiles_and_unsafe_controls(self):
        geometry=self.covered_geometry()
        page=SimpleNamespace(evaluate=lambda _:geometry)
        self.assertEqual(assert_layout(page,390,690)['stage']['w'],390)
        for mutation in ('tile','safe_area','logo','spin','collapsed_control','small_touch_target'):
            bad=deepcopy(geometry)
            if mutation=='tile':bad['tiles'][0]=1
            elif mutation=='safe_area':bad['buttons'][-1]['bottom']=691
            elif mutation=='logo':bad['logo']['w']=100
            elif mutation=='spin':bad['disk']['w']=75
            elif mutation=='small_touch_target':bad['buttons'][3]['w']=40
            else:bad['buttons'][3]['h']=0
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):
                assert_layout(SimpleNamespace(evaluate=lambda _:bad),390,690)
        with self.assertRaises(AssertionError):assert_layout(page,390,690,left=12)
        with self.assertRaises(AssertionError):assert_layout(page,390,690,right=24)

    def test_artwork_gate_rejects_empty_bands_root_and_extension_gaps(self):
        for mutation in ('root_image','body_extent','hidden_stage','vertical_gap','horizontal_gap','missing_image','top_extension','bottom_extension'):
            bad=self.covered_geometry()
            if mutation=='root_image':bad['root']['image']=False
            elif mutation=='body_extent':bad['body']['bottom']=680
            elif mutation=='hidden_stage':bad['stage']['visible']=False
            elif mutation=='vertical_gap':bad['art']['bands'][1]['y']+=2
            elif mutation=='horizontal_gap':bad['art']['bands'][0]['parts'][1]['x']+=2
            elif mutation=='missing_image':bad['art']['bands'][2]['parts'][0]['image']=False
            elif mutation=='top_extension':bad['art']['before']['image']=False
            else:bad['art']['after']['bottom']-=2
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):
                assert_layout(SimpleNamespace(evaluate=lambda _:bad),390,690)

    def test_root_backing_may_exceed_browser_visual_viewport(self):
        geometry=self.covered_geometry()
        geometry['viewport']['layoutHeight']=844
        for name in ('root','body','backdrop'):
            geometry[name]['h']=844;geometry[name]['bottom']=844
        result=assert_layout(SimpleNamespace(evaluate=lambda _:geometry),390,690)
        self.assertEqual(result['stage']['h'],690)
        self.assertEqual(result['root']['h'],844)

    def test_css_background_decode_rejects_failed_art_assets(self):
        images=[{'label':str(i),'ok':True,'width':32,'height':32} for i in range(13)]
        self.assertEqual(len(assert_background_images(SimpleNamespace(evaluate=lambda _:images))),13)
        images[5]['ok']=False
        with self.assertRaises(AssertionError):
            assert_background_images(SimpleNamespace(evaluate=lambda _:images))

    def test_resize_can_interrupt_starts_but_cannot_duplicate_settlements(self):
        def events(starts,stops):
            return [dict(phase=phase,column=column,at=i)
                    for i,(phase,column) in enumerate(
                        [('start',n) for n in starts]+[('stop',n) for n in stops])]
        receipt={'completed':True,'cancelled':True,'starts':[1,2],'stops':[1,2,3,4,5]}
        transcript=events([1,2],receipt['stops'])
        assert_reel_order(receipt,transcript,allow_interrupted=True)
        with self.assertRaises(AssertionError):assert_reel_order(receipt,transcript)
        for starts,stops in [([1,1],[1,2,3,4,5]),([1,3],[1,2,3,4,5]),([1,2],[1,2,3,4])]:
            with self.subTest(starts=starts,stops=stops),self.assertRaises(AssertionError):
                assert_reel_order({**receipt,'starts':starts,'stops':stops},events(starts,stops),allow_interrupted=True)
        with self.assertRaises(AssertionError):
            assert_reel_order(receipt,events([1,2],[1,2,3,4,5,5]),allow_interrupted=True)
        complete={**receipt,'cancelled':False,'starts':[1,2,3,4,5]}
        assert_reel_order(complete,events([1,1,2,3,4,5],complete['stops']),allow_interrupted=True)
        assert_reel_order(complete,events(complete['starts'],complete['stops']))
if __name__=='__main__':unittest.main()
