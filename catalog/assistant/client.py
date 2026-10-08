"""Thin client for Ollama's hosted chat API (https://docs.ollama.com/api/chat).

The wire format is isolated here. Request bodies, responses and the API key are never
logged, and errors raised to callers carry no URL, header or body.
"""
import json
import urllib.error
import urllib.request

from django.conf import settings


class AssistantUnavailable(Exception):
    """The model backend could not produce a usable reply."""


class OllamaClient:
    def __init__(self, api_key, model, base_url, timeout):
        self._api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def __repr__(self):
        return f'OllamaClient(model={self.model!r}, api_key=***)'

    def chat(self, messages, tools):
        """Return {"content": str, "tool_calls": [{"name": str, "arguments": dict}]}."""
        body = json.dumps({
            'model': self.model,
            'messages': messages,
            'tools': tools,
            'stream': False,  # the API streams by default
            'options': {'temperature': 0.3, 'num_predict': 600},
        }).encode()
        request = urllib.request.Request(
            f'{self.base_url}/chat', data=body, method='POST',
            headers={
                'Authorization': f'Bearer {self._api_key}',
                'Content-Type': 'application/json',
            })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
            message = payload['message']
            content = message.get('content') or ''
            calls = []
            for call in message.get('tool_calls') or []:
                function = call['function']
                arguments = function.get('arguments') or {}
                if isinstance(arguments, str):  # be lenient with OpenAI-style strings
                    arguments = json.loads(arguments)
                calls.append({'name': function['name'], 'arguments': arguments})
            return {'content': content, 'tool_calls': calls}
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            # Only the exception class leaves this function: URLs and bodies may hold secrets.
            raise AssistantUnavailable(f'Assistant backend error ({type(exc).__name__})') from None


def get_client():
    """Return the configured client, or None when no API key is set."""
    if not settings.OLLAMA_API_KEY:
        return None
    return OllamaClient(
        settings.OLLAMA_API_KEY, settings.OLLAMA_MODEL,
        settings.OLLAMA_BASE_URL, settings.ASSISTANT_TIMEOUT_SECONDS)
