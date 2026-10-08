class FakeClient:
    """Scripted LLM client: each chat() call pops the next scripted reply."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools):
        self.calls.append({'messages': [dict(m) for m in messages], 'tools': tools})
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return {'content': reply.get('content', ''), 'tool_calls': reply.get('tool_calls', [])}


def tool_call(name, **arguments):
    return {'name': name, 'arguments': arguments}
