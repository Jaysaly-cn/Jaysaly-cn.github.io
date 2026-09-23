"""Versioned, code-owned schemas. Never change v1: add a new name instead.

Only structure is checked; quotations and business meaning still need review.
"""
SCHEMAS = {
    'json-feedback-v1': {
        'type': 'object', 'required': ['suggestions'], 'additionalProperties': False,
        'properties': {'suggestions': {
            'type': 'array', 'maxItems': 5,
            'items': {'type': 'object', 'required': ['theme', 'kind', 'quote'],
                      'additionalProperties': False,
                      'properties': {
                          'theme': {'type': 'string', 'minLength': 2, 'maxLength': 100},
                          'kind': {'type': 'string', 'enum': ['problem', 'request', 'praise', 'other']},
                          'quote': {'type': 'string', 'minLength': 2, 'maxLength': 4000},
                      }},
        }},
    },
    'json-change-v1': {
        'type': 'object', 'required': ['summary', 'old_quote', 'new_quote'],
        'additionalProperties': False,
        'properties': {
            'summary': {'type': 'string', 'minLength': 5, 'maxLength': 1500},
            'old_quote': {'type': 'string', 'maxLength': 4000},
            'new_quote': {'type': 'string', 'maxLength': 4000},
        },
    },
}
