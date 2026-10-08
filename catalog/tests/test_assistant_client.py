import io
import json
import urllib.error
from unittest import mock

from django.test import SimpleTestCase, override_settings

from catalog.assistant.client import AssistantUnavailable, OllamaClient, get_client


def fake_response(payload):
    response = mock.MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


class OllamaClientTest(SimpleTestCase):
    def setUp(self):
        self.client = OllamaClient('sekrit-key', 'some-model', 'https://ollama.com/api/', 30)

    def test_request_shape_and_object_arguments(self):
        payload = {'message': {'content': '', 'tool_calls': [
            {'function': {'name': 'search_books', 'arguments': {'query': 'emma', 'by': 'title'}}}]}}
        with mock.patch('urllib.request.urlopen', return_value=fake_response(payload)) as urlopen:
            result = self.client.chat([{'role': 'user', 'content': 'hi'}], [{'type': 'function'}])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://ollama.com/api/chat')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer sekrit-key')
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 30)
        body = json.loads(request.data)
        self.assertIs(body['stream'], False)
        self.assertEqual(body['model'], 'some-model')
        self.assertEqual(result['tool_calls'], [{'name': 'search_books', 'arguments': {'query': 'emma', 'by': 'title'}}])

    def test_plain_content(self):
        with mock.patch('urllib.request.urlopen', return_value=fake_response({'message': {'content': 'Hello'}})):
            self.assertEqual(self.client.chat([], []), {'content': 'Hello', 'tool_calls': []})

    def test_http_error_becomes_unavailable_without_leaking(self):
        err = urllib.error.HTTPError('https://ollama.com/api/chat', 401, 'Unauthorized sekrit-key', {}, io.BytesIO(b'body'))
        with mock.patch('urllib.request.urlopen', side_effect=err):
            with self.assertRaises(AssistantUnavailable) as ctx:
                self.client.chat([], [])
        self.assertNotIn('sekrit', str(ctx.exception))
        self.assertNotIn('ollama.com', str(ctx.exception))

    def test_network_timeout_and_bad_json(self):
        with mock.patch('urllib.request.urlopen', side_effect=TimeoutError()):
            with self.assertRaises(AssistantUnavailable):
                self.client.chat([], [])
        bad = mock.MagicMock()
        bad.read.return_value = b'not json'
        bad.__enter__.return_value = bad
        with mock.patch('urllib.request.urlopen', return_value=bad):
            with self.assertRaises(AssistantUnavailable):
                self.client.chat([], [])
        with mock.patch('urllib.request.urlopen', return_value=fake_response({'oops': 1})):
            with self.assertRaises(AssistantUnavailable):
                self.client.chat([], [])

    def test_repr_hides_key(self):
        self.assertNotIn('sekrit', repr(self.client))

    @override_settings(OLLAMA_API_KEY='')
    def test_get_client_none_without_key(self):
        self.assertIsNone(get_client())

    @override_settings(OLLAMA_API_KEY='k', OLLAMA_MODEL='m')
    def test_get_client_with_key(self):
        self.assertEqual(get_client().model, 'm')


class MalformedPayloadTest(SimpleTestCase):
    def setUp(self):
        self.client = OllamaClient('k', 'm', 'https://ollama.com/api', 30)

    def test_non_string_tool_name_or_content_is_unavailable(self):
        for message in (
            {'content': '', 'tool_calls': [{'function': {'name': ['x'], 'arguments': {}}}]},
            {'content': ['not', 'a', 'string']},
        ):
            with mock.patch('urllib.request.urlopen', return_value=fake_response({'message': message})):
                with self.assertRaises(AssistantUnavailable):
                    self.client.chat([], [])
