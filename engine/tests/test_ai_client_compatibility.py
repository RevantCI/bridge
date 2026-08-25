from __future__ import annotations

import json

import pytest

from tc_ai_bridge.ai_client import AIError, OpenAIResponsesClient


def _success(result: dict) -> bytes:
    return json.dumps({
        'output_text': json.dumps(result),
        'usage': {
            'input_tokens': 5,
            'output_tokens': 3,
            'total_tokens': 8,
            'input_tokens_details': {'cached_tokens': 0},
        },
    }).encode('utf-8')


def test_retries_once_without_reasoning_when_provider_explicitly_rejects_it():
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        payload = json.loads(body)
        requests.append(payload)
        if len(requests) == 1:
            return 400, json.dumps({'error': {
                'message': "Unsupported parameter: 'reasoning.effort' is not supported with this model.",
                'type': 'invalid_request_error',
                'param': 'reasoning.effort',
                'code': 'unsupported_parameter',
            }}).encode('utf-8')
        return 200, _success({'links': []})

    client = OpenAIResponsesClient('test-key', model='non-reasoning-model', transport=transport)
    result = client._post_structured('instructions', 'input', 'test_schema', {
        'type': 'object', 'properties': {'links': {'type': 'array'}}, 'required': ['links'],
    })

    assert result == {'links': []}
    assert requests[0]['reasoning'] == {'effort': 'medium'}
    assert 'reasoning' not in requests[1]
    assert client.last_reasoning_effort is None
    assert client._effective_reasoning_effort() == 'provider-default'


def test_does_not_retry_an_unrelated_bad_request():
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return 400, json.dumps({'error': {
            'message': "Unsupported parameter: 'text.format'.",
            'param': 'text.format',
            'code': 'unsupported_parameter',
        }}).encode('utf-8')

    client = OpenAIResponsesClient('test-key', transport=transport)

    with pytest.raises(AIError, match=r"Unsupported parameter: 'text\.format'"):
        client._post_structured('instructions', 'input', 'test_schema', {'type': 'object'})

    assert len(requests) == 1


def test_does_not_retry_reasoning_error_without_explicit_unsupported_signal():
    requests: list[dict] = []

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body))
        return 400, json.dumps({'error': {
            'message': 'reasoning.effort must be one of the allowed values',
            'param': 'reasoning.effort',
            'code': 'invalid_value',
        }}).encode('utf-8')

    client = OpenAIResponsesClient('test-key', transport=transport)

    with pytest.raises(AIError, match='allowed values'):
        client._post_structured('instructions', 'input', 'test_schema', {'type': 'object'})

    assert len(requests) == 1
