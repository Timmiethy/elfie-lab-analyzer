# Analyze normalization paths for the three problematic labels
import sys
sys.path.insert(0, '.')

from app.services.analyte_resolver import (
    AnalyteResolver, _normalize_lookup_label, _BILINGUAL_TRANSLATIONS, _LABEL_REWRITES
)

resolver = AnalyteResolver()
ctx = {'family_adapter_id': 'innoquest_bilingual_general', 'specimen_context': 'serum', 'language_id': 'en'}

labels = [
    'Apolipoprotein A1 è½½è„‚è›‹ç™½ A1',
    'Triglyceride ä¸‰é…¸ç"˜æ²¹é…¯',
    'æ€»çº¢èƒ†ç´ ',
]

for label in labels:
    print(f'Input: {label!r}')
    raw_text = label.strip().lower()
    print(f'  After lower: {raw_text!r}')

    translated = raw_text
    for source, target in sorted(_BILINGUAL_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        if source in translated:
            translated = translated.replace(source, target)
            print(f'  Bilingual match: {source!r} -> {target!r}')

    deduped = []
    for token in translated.split():
        if not deduped or deduped[-1] != token:
            deduped.append(token)
    if len(deduped) % 2 == 0:
        midpoint = len(deduped) // 2
        if deduped[:midpoint] == deduped[midpoint:]:
            deduped = deduped[:midpoint]
    after_bilingual = ' '.join(deduped)
    print(f'  After bilingual+dedup: {after_bilingual!r}')

    lookup_text = _normalize_lookup_label(after_bilingual)
    print(f'  After lookup normalize: {lookup_text!r}')

    rewritten = _LABEL_REWRITES.get(lookup_text)
    print(f'  After rewrite: {rewritten!r}')

    result = resolver.resolve(label, context=ctx)
    print(f'  FINAL normalized: {result["normalized_label"]!r}')
    print(f'  FINAL support_state: {result["support_state"]}')
    print(f'  FINAL failure_code: {result["failure_code"]}')
    if result.get('accepted_candidate'):
        print(f'  ACCEPTED: {result["accepted_candidate"]["candidate_code"]}')
    print()
