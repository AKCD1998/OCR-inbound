"""HQ-only PDF/image -> TSV -> source-bound review proposals, never ERP writes."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True)
    p.add_argument('--request-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--admission',type=Path,required=True);p.add_argument('--admission-sha256',required=True)
    a=p.parse_args()
    from component_common import read,sha,save,verify_admission,checked
    verify_admission(a.admission,a.admission_sha256,__file__,'ingress')
    if sha(a.request)!=a.request_sha256:raise ValueError('Request bytes differ')
    request=read(a.request);source=checked(request['source']);tesseract=checked(request['tesseract'])
    for item in request['code_pins']:checked(item)
    for item in request.get('reader_data_pins',[]):checked(item)
    sys.path.insert(0,request['package_src'])
    from ocr_inbound.document_ai.hq_ingress import tsv_tokens,adapt_page,needs_retry,merge_retry
    from ocr_inbound.batch_supplier_extraction import extract_batch_page
    from ocr_inbound.document_ai.learning import ProductMatcher
    matcher=ProductMatcher(read(checked(request['catalogue']))) if request.get('catalogue') else None
    # Imported only after actual live-ancestor admission and unchanged source pins.
    from PIL import Image,ImageOps
    import pypdfium2 as pdfium
    out=a.output.parent;out.mkdir(parents=True,exist_ok=True)
    pdf=None
    with source.open('rb') as stream:signature=stream.read(5)
    if signature==b'%PDF-':
        pdf=pdfium.PdfDocument(source);count=len(pdf)
    else:count=1
    if not 1<=count<=20:raise ValueError('Prototype accepts at most20pages; no silent truncation')
    pages=[];rows=[];calls=0
    try:
        for n in range(1,count+1):
            image=out/f'page-{n:03d}.png';page=None;bitmap=None
            if pdf is not None:
                page=pdf[n-1];w,h=page.get_size()
                if w*h*4>20_000_000:raise ValueError('Rendered page exceeds20M pixel gate')
                bitmap=page.render(scale=2);im=bitmap.to_pil()
            else:
                with Image.open(source) as original:
                    if original.width*original.height>20_000_000:raise ValueError('Image exceeds20M pixel gate')
                    im=ImageOps.exif_transpose(original).convert('RGB')
            width,height=im.size;im.save(image);im.close()
            if bitmap:bitmap.close()
            if page:page.close()
            prefix=out/f'page-{n:03d}'
            subprocess.run([str(tesseract),str(image),str(prefix),'-l','tha+eng','--psm','3','tsv'],
                           check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            calls+=1;tsv=prefix.with_suffix('.tsv')
            tokens,rejected=tsv_tokens(tsv.read_text(encoding='utf-8-sig'),width,height)
            parsed=extract_batch_page(n,tokens,(width,height),source_file=source.name)
            if needs_retry(parsed):
                alternate=out/f'page-{n:03d}-psm6'
                subprocess.run([str(tesseract),str(image),str(alternate),'-l','tha+eng','--psm','6','tsv'],
                               check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                calls+=1
                retry_tokens,_=tsv_tokens(alternate.with_suffix('.tsv').read_text(encoding='utf-8-sig'),width,height)
                for token in retry_tokens:
                    token['engine']='TESSERACT_TSV_PSM6';token['token_id']='psm6:'+token['token_id']
                retry_parse=extract_batch_page(n,retry_tokens,(width,height),source_file=source.name)
                save(out/f'page-{n:03d}.primary.parse.json',parsed)
                save(out/f'page-{n:03d}.secondary.parse.json',retry_parse)
                parsed=merge_retry(parsed,retry_parse)
            save(out/f'page-{n:03d}.parse.json',parsed)
            rows.extend(adapt_page(parsed,tokens,f'p{n}',matcher))
            pages.append({'id':f'p{n}','number':n,'width':width,'height':height,
                          'image_path':str(image),'sha256':sha(image),
                          'source_transform':'PDF144dpi_or_EXIF_upright_RGB',
                          'invalid_TSV_tokens_excluded':len(rejected)})
    finally:
        if pdf:pdf.close()
    save(a.output,{'contract':'document-ai-proposals.v1','document_id':request['document_id'],
        'source_sha256':request['source']['sha256'],'artifacts_root':str(out),'pages':pages,'rows':rows,
        'processing':{'adapter':'HQ_TESSERACT_TSV_plus_frozen_supplier_parser',
                      'new_text_OCR_calls':calls,'optimizer_updates':0,'manual_transcriptions':0,
                      'maximum_reader_modes_per_page':2,'same_engine_agreement_is_not_gold':True,
                      'trained_matcher_selected':False,'benchmark_gain_claimed':False,
                      'all_rows_require_final_human_review':True},'status':'COMPLETE'})

if __name__=='__main__':main()
