"""Attachments alone do not require OCR or block a text-based resume conversion."""
from source_audit import load

MEDIA_NOTICES={'images_require_visual_review','sheet_images_require_visual_review','package_media_require_visual_review'}


def required_warnings(data, source):
    warnings=source.get('warnings',[])
    if data.get('media_policy','when_needed') not in ('when_needed','review_all'):raise ValueError('Unknown media policy.')
    if not warnings and source.get('status')=='needs_review':return [{'kind':'unspecified_source_warning'}]
    if data.get('media_policy','when_needed')=='review_all':return warnings
    result=[]
    detail=None
    for warning in warnings:
        if warning.get('kind') in MEDIA_NOTICES:continue
        if warning.get('kind')=='xlsx_reader_warning':
            message=warning.get('message','').lower()
            if message=='data validation extension is not supported and will be removed':continue
            if 'image format is not supported' in message and 'image is being dropped' in message:continue
        if warning.get('kind')=='formula_cache_missing':
            detail=detail or load(source['detail_file'])
            cells=[c for s in detail.get('sheets',[]) if s['sheet']==warning.get('sheet') for c in s['cells'] if c['cell']==warning.get('cell')]
            if cells and 'DISPIMG' in str(cells[0].get('formula','')).upper():continue
        result.append(warning)
    return result


def source_pending(data, source):
    if source.get('status')=='error':return True
    if not required_warnings(data,source):
        # An unknown extraction status must not silently pass.
        return source.get('status') not in ('ok','needs_review',None)
    review=data.get('source_reviews',{}).get(source['id'],{})
    return not (review.get('status')=='passed' and review.get('reason') and
                review.get('source_sha256')==source['sha256'] and review.get('detail_sha256')==source.get('detail_sha256'))
