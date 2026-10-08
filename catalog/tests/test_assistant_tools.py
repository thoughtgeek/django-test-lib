import time
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings

from catalog.assistant import tools
from catalog.models import Author, Book, BookInstance, Genre


def make_request(user):
    request = RequestFactory().post('/')
    request.user = user
    request.session = {}
    return request


class ToolsTestCase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user('alice', password='x')
        self.bob = User.objects.create_user('bob', password='x')
        author = Author.objects.create(first_name='Jane', last_name='Austen')
        genre = Genre.objects.create(name='Fiction')
        self.book = Book.objects.create(title='Emma', author=author, summary='Matchmaking.', isbn='1111111111111')
        self.book.genre.add(genre)
        self.copy = BookInstance.objects.create(book=self.book, imprint='x', status='a')


class SearchTests(ToolsTestCase):
    def test_search_by_each_field(self):
        request = make_request(self.alice)
        for by, query in (('title', 'emm'), ('author', 'aust'), ('genre', 'fict')):
            result = tools.run_tool(request, 'search_books', {'query': query, 'by': by})
            self.assertEqual(result['untrusted_data'][0]['title'], 'Emma', by)
            self.assertEqual(result['untrusted_data'][0]['available_count'], 1)

    def test_search_is_orm_safe(self):
        result = tools.run_tool(make_request(self.alice), 'search_books', {'query': "' OR 1=1 --", 'by': 'title'})
        self.assertEqual(result['untrusted_data'], [])

    def test_result_cap(self):
        for n in range(12):
            Book.objects.create(title=f'Emma {n}', summary='s', isbn=f'22222222222{n:02}')
        result = tools.run_tool(make_request(self.alice), 'search_books', {'query': 'Emma', 'by': 'title'})
        self.assertEqual(len(result['untrusted_data']), tools.MAX_RESULTS)

    def test_control_characters_stripped(self):
        self.book.summary = 'ok\x00\x1b[31mred'
        self.book.save()
        result = tools.run_tool(make_request(self.alice), 'search_books', {'query': 'Emma', 'by': 'title'})
        self.assertNotIn('\x1b', result['untrusted_data'][0]['summary'])


class ValidationTests(ToolsTestCase):
    def test_rejections(self):
        request = make_request(self.alice)
        bad = [
            ('borrow', {'book_id': 1}),
            ('confirm_loan', {}),
            ('propose_loan', {'book_id': '1'}),
            ('propose_loan', {'book_id': True}),
            ('propose_loan', {'book_id': self.book.id, 'user_id': self.bob.id}),
            ('search_books', {'query': 'x', 'by': 'isbn'}),
            ('search_books', {'query': 'x' * 101, 'by': 'title'}),
            ('my_loans', {'user': 'bob'}),
            ('propose_loan', 'not a dict'),
        ]
        for name, args in bad:
            self.assertIn('error', tools.run_tool(request, name, args), (name, args))
        self.assertEqual(tools.get_proposals(request), [])
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, 'a')


class AvailabilityTests(ToolsTestCase):
    def test_counts_and_earliest_due(self):
        self.copy.status = 'o'
        self.copy.due_back = date.today() + timedelta(days=3)
        self.copy.borrower = self.bob
        self.copy.save()
        result = tools.run_tool(make_request(self.alice), 'book_availability', {'book_id': self.book.id})
        info = result['untrusted_data']
        self.assertEqual(info['copies_by_status']['On loan'], 1)
        self.assertEqual(info['earliest_due_back'], self.copy.due_back.isoformat())

    def test_unknown_book(self):
        self.assertIn('error', tools.run_tool(make_request(self.alice), 'book_availability', {'book_id': 999}))


class LoanTests(ToolsTestCase):
    def pid(self, request):
        return request.session[tools.PROPOSALS_KEY][0]['id']

    def test_propose_does_not_borrow(self):
        request = make_request(self.alice)
        result = tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        self.assertTrue(result['proposed'])
        self.copy.refresh_from_db()
        self.assertEqual((self.copy.status, self.copy.borrower), ('a', None))

    def test_propose_when_none_available(self):
        BookInstance.objects.update(status='o', borrower=self.bob)
        result = tools.run_tool(make_request(self.alice), 'propose_loan', {'book_id': self.book.id})
        self.assertFalse(result['proposed'])

    def test_confirm_borrows_for_session_user(self):
        request = make_request(self.alice)
        tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        ok, _ = tools.confirm_loan(request, self.pid(request))
        self.assertTrue(ok)
        self.copy.refresh_from_db()
        self.assertEqual((self.copy.status, self.copy.borrower), ('o', self.alice))
        self.assertEqual(self.copy.due_back, date.today() + timedelta(days=14))
        listing = tools.run_tool(request, 'my_loans', {})['untrusted_data']
        self.assertEqual([l['title'] for l in listing], ['Emma'])
        self.assertEqual(tools.get_proposals(request), [])

    def test_my_loans_only_own(self):
        BookInstance.objects.update(status='o', borrower=self.bob)
        self.assertEqual(tools.run_tool(make_request(self.alice), 'my_loans', {})['untrusted_data'], [])

    def test_confirm_without_proposal(self):
        ok, _ = tools.confirm_loan(make_request(self.alice), 'nope')
        self.assertFalse(ok)

    def test_confirm_after_copy_taken(self):
        request = make_request(self.alice)
        tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        BookInstance.objects.update(status='o', borrower=self.bob)
        ok, message = tools.confirm_loan(request, self.pid(request))
        self.assertFalse(ok)
        self.assertIn('no longer available', message)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.borrower, self.bob)
        self.assertEqual(tools.get_proposals(request), [])

    def test_expired_proposal(self):
        request = make_request(self.alice)
        tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        pid = self.pid(request)
        request.session[tools.PROPOSALS_KEY][0]['created_at'] = time.time() - 601
        ok, _ = tools.confirm_loan(request, pid)
        self.assertFalse(ok)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, 'a')

    def test_double_confirm_borrows_once(self):
        request = make_request(self.alice)
        tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        pid = self.pid(request)
        self.assertTrue(tools.confirm_loan(request, pid)[0])
        self.assertFalse(tools.confirm_loan(request, pid)[0])


class MultiProposalTests(ToolsTestCase):
    def setUp(self):
        super().setUp()
        author = Author.objects.create(first_name='B', last_name='B')
        self.other = Book.objects.create(title='Dracula', author=author, summary='s', isbn='9780000000002')
        self.other_copy = BookInstance.objects.create(book=self.other, imprint='y', status='a')

    def test_two_books_get_two_independent_proposals(self):
        request = make_request(self.alice)
        for book in (self.book, self.other):
            self.assertTrue(tools.run_tool(request, 'propose_loan', {'book_id': book.id})['proposed'])
        first, second = tools.get_proposals(request)
        self.assertNotEqual(first['id'], second['id'])
        self.assertTrue(tools.confirm_loan(request, first['id'])[0])
        self.assertEqual([p['id'] for p in tools.get_proposals(request)], [second['id']])
        self.other_copy.refresh_from_db()
        self.assertEqual(self.other_copy.status, 'a')
        self.assertTrue(tools.confirm_loan(request, second['id'])[0])
        self.assertEqual(BookInstance.objects.filter(borrower=self.alice).count(), 2)

    def test_cancel_one_leaves_the_other(self):
        request = make_request(self.alice)
        for book in (self.book, self.other):
            tools.run_tool(request, 'propose_loan', {'book_id': book.id})
        first, second = tools.get_proposals(request)
        self.assertTrue(tools.cancel_proposal(request, first['id']))
        self.assertEqual([p['id'] for p in tools.get_proposals(request)], [second['id']])

    def test_same_book_twice_is_one_proposal_and_second_copy_not_reserved_twice(self):
        spare = BookInstance.objects.create(book=self.book, imprint='z', status='a')
        request = make_request(self.alice)
        tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        again = tools.run_tool(request, 'propose_loan', {'book_id': self.book.id})
        self.assertTrue(again['proposed'])
        self.assertEqual(len(tools.get_proposals(request)), 1)
        spare.delete()

    def test_cap_refuses_clearly(self):
        author = Author.objects.first()
        request = make_request(self.alice)
        limit = settings.ASSISTANT_MAX_PROPOSALS
        for i in range(limit + 1):
            b = Book.objects.create(title=f'T{i}', author=author, summary='s', isbn=f'97800000001{i:02d}')
            BookInstance.objects.create(book=b, imprint='x', status='a')
            result = tools.run_tool(request, 'propose_loan', {'book_id': b.id})
        self.assertFalse(result['proposed'])
        self.assertEqual(len(tools.get_proposals(request)), limit)
