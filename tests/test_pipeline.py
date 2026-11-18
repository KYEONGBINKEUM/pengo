import json, tempfile, unittest, zipfile, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publisher import analyze_zip, build, primitive
from psd_tools import PSDImage
from PIL import Image

class PipelineTest(unittest.TestCase):
    def test_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bad.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('../outside.php','test')
            with self.assertRaises(ValueError):analyze_zip(path)

    def test_style_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'source.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('css/layout.css','.inner{width:1280px} @media(max-width:800px){.inner{width:94%}} :root{--color1:#123456}')
                z.writestr('index.php','<?php include "inc/head.php"; ?><div class="m_txt inner"></div>')
            r=analyze_zip(path)
            self.assertEqual(r['generation']['inner_width'],'1280px')
            self.assertEqual(r['generation']['breakpoints'],[800])
            self.assertEqual(r['generation']['brand_color'],'#123456')
            self.assertTrue(r['includes'])

    def test_unrelated_flat_psd_and_output_preservation(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); path=td/'different.psd'
            PSDImage.frompil(Image.new('RGB',(320,180),'#3399aa')).save(path)
            report=build(path,td/'site')
            self.assertEqual(report['canvas'],[320,180])
            self.assertEqual(report['mode'],'automatic-draft')
            self.assertTrue((td/'site/index.php').exists())
            self.assertTrue((td/'site/images/main/root-art.png').exists())
            original=(td/'site/index.php').read_bytes()
            with self.assertRaises(ValueError):build(path,td/'site')
            self.assertEqual((td/'site/index.php').read_bytes(),original)

    def test_recipe_cannot_silently_bind_wrong_psd(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); path=td/'different.psd'
            PSDImage.frompil(Image.new('RGB',(20,20),'white')).save(path)
            recipe=td/'recipe.json';recipe.write_text(json.dumps({'source_sha256':'wrong'}))
            with self.assertRaisesRegex(ValueError,'다른 PSD'):build(path,td/'site',recipe_path=recipe)

if __name__=='__main__':unittest.main()
