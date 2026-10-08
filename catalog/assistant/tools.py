"""Tools the assistant model may call, and the confirmed-loan step it may not.

Every tool closes over ``request`` so it can only act for the signed-in user; none takes a user
argument. ``propose_loan`` only records a proposal in the user's session. Borrowing happens in
``confirm_loan``, which is not in the tool registry and is reached only from a CSRF-protected
POST made by the user.
"""
import re
import time
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Min, Q

from catalog.models import Book, BookInstance

PROPOSAL_KEY = 'assistant_proposal'
MAX_RESULTS = 8
SEARCH_FIELDS = {
    'title': 'title__icontains',
    'author': None,  # handled separately: matches first or last name
    'genre': 'genre__name__icontains',
}
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')

TOOL_SCHEMAS = [
    {'type': 'function', 'function': {
        'name': 'search_books',
        'description': 'Search the library catalog. Returns up to 8 books with availability counts.',
        'parameters': {'type': 'object', 'properties': {
            'query': {'type': 'string', 'description': 'Text to look for.'},
            'by': {'type': 'string', 'enum': ['title', 'author', 'genre']},
        }, 'required': ['query', 'by']}}},
    {'type': 'function', 'function': {
        'name': 'book_availability',
        'description': 'Count the copies of a book by status, and the earliest return date if none are available.',
        'parameters': {'type': 'object', 'properties': {
            'book_id': {'type': 'integer'},
        }, 'required': ['book_id']}}},
    {'type': 'function', 'function': {
        'name': 'propose_loan',
        'description': ('Propose borrowing an available copy of a book for the current user. This does NOT '
                        'borrow it: the user must press Confirm on the page.'),
        'parameters': {'type': 'object', 'properties': {
            'book_id': {'type': 'integer'},
        }, 'required': ['book_id']}}},
    {'type': 'function', 'function': {
        'name': 'my_loans',
        'description': "List the current user's borrowed copies and due dates.",
        'parameters': {'type': 'object', 'properties': {}}}},
]


def clean_text(value, limit):
    """Strip control characters and cap length of text that came from the catalog."""
    return _CONTROL_CHARS.sub('', str(value or ''))[:limit]


def data(payload):
    """Envelope marking tool output as data, never as instructions."""
    return {'untrusted_data': payload}


def _book_summary(book, available):
    return {
        'id': book.id,
        'title': clean_text(book.title, 200),
        'author': clean_text(book.author, 200) if book.author else None,
        'genres': [clean_text(g.name, 100) for g in book.genre.all()],
        'available_count': available,
        'summary': clean_text(book.summary, 200),
    }


def search_books(request, query, by):
    books = Book.objects.select_related('author').prefetch_related('genre')
    if by == 'author':
        books = books.filter(Q(author__first_name__icontains=query) | Q(author__last_name__icontains=query))
    else:
        books = books.filter(**{SEARCH_FIELDS[by]: query})
    books = books.annotate(
        available=Count('bookinstance', filter=Q(bookinstance__status='a'), distinct=True)).distinct()[:MAX_RESULTS]
    return data([_book_summary(b, b.available) for b in books])


def book_availability(request, book_id):
    book = Book.objects.filter(pk=book_id).first()
    if book is None:
        return {'error': 'No such book.'}
    copies = BookInstance.objects.filter(book=book)
    counts = {label: copies.filter(status=code).count() for code, label in BookInstance.LOAN_STATUS}
    result = {'id': book.id, 'title': clean_text(book.title, 200), 'copies_by_status': counts}
    if not counts['Available']:
        soonest = copies.filter(status='o').aggregate(d=Min('due_back'))['d']
        result['earliest_due_back'] = soonest.isoformat() if soonest else None
    return data(result)


def propose_loan(request, book_id):
    book = Book.objects.filter(pk=book_id).first()
    if book is None:
        return {'error': 'No such book.'}
    pending = get_proposal(request)
    if pending and pending['book_id'] != book.id:
        return {'proposed': False, 'reason': 'Another loan is already waiting for the user. Ask them to '
                'confirm or cancel it first, then propose this book in a later message. '
                'Do not tell the user this book is ready.'}
    copy = BookInstance.objects.filter(book=book, status='a', borrower__isnull=True).first()
    if copy is None:
        return {'proposed': False, 'reason': 'No copy of this book is available right now.'}
    request.session[PROPOSAL_KEY] = {
        'instance_id': str(copy.id), 'book_id': book.id,
        'title': clean_text(book.title, 200), 'created_at': time.time(),
    }
    return {'proposed': True, 'title': clean_text(book.title, 200), 'needs_user_confirmation': True}


def my_loans(request):
    loans = BookInstance.objects.filter(borrower=request.user).select_related('book')
    return data([
        {'title': clean_text(i.book.title, 200), 'due_back': i.due_back.isoformat() if i.due_back else None,
         'overdue': i.is_overdue}
        for i in loans[:20]])


def get_proposal(request):
    """Return the user's pending proposal, dropping it if it has expired."""
    proposal = request.session.get(PROPOSAL_KEY)
    if not proposal:
        return None
    if time.time() - proposal.get('created_at', 0) > settings.ASSISTANT_PROPOSAL_TTL_SECONDS:
        request.session.pop(PROPOSAL_KEY, None)
        return None
    return proposal


def cancel_proposal(request):
    return request.session.pop(PROPOSAL_KEY, None) is not None


def confirm_loan(request):
    """Complete the pending proposal for ``request.user``. Returns (ok, message).

    The proposal comes from the session only; nothing the client posts selects the copy.
    The status-guarded UPDATE is the real race protection (SQLite ignores row locks).
    """
    proposal = get_proposal(request)
    if proposal is None:
        return False, 'There is no pending loan to confirm (it may have expired).'
    request.session.pop(PROPOSAL_KEY, None)
    due = date.today() + timedelta(days=settings.ASSISTANT_LOAN_DAYS)
    with transaction.atomic():
        updated = BookInstance.objects.filter(
            pk=proposal['instance_id'], status='a', borrower__isnull=True,
        ).update(status='o', borrower=request.user, due_back=due)
    if updated != 1:
        return False, f"Sorry, that copy of “{proposal['title']}” is no longer available."
    return True, f"You borrowed “{proposal['title']}”. It is due back on {due.isoformat()}."


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100


# name -> (function, validator for the arguments dict)
REGISTRY = {
    'search_books': (search_books, lambda a: set(a) == {'query', 'by'} and _text(a['query'])
                     and a['by'] in SEARCH_FIELDS),
    'book_availability': (book_availability, lambda a: set(a) == {'book_id'} and _is_int(a['book_id'])),
    'propose_loan': (propose_loan, lambda a: set(a) == {'book_id'} and _is_int(a['book_id'])),
    'my_loans': (my_loans, lambda a: not a),
}


def run_tool(request, name, arguments):
    """Dispatch a model-requested tool call; invalid requests become error results."""
    entry = REGISTRY.get(name) if isinstance(name, str) else None
    if entry is None:
        return {'error': 'Unknown tool.'}
    function, valid = entry
    if not isinstance(arguments, dict) or not valid(arguments):
        return {'error': 'Invalid arguments.'}
    return function(request, **arguments)
