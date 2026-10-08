from io import StringIO
from datetime import date

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Author, Book, BookInstance, Genre, Language


def seed(*extra):
    call_command('seed_library', '--yes-dev-data', *extra, stdout=StringIO())


class SeedLibraryTest(TestCase):
    def counts(self):
        return tuple(m.objects.count() for m in (
            Author, Book, BookInstance, Genre, Language, User))

    def test_refuses_without_confirmation_flag(self):
        with self.assertRaises(CommandError):
            call_command('seed_library')
        self.assertEqual(self.counts(), (0, 0, 0, 0, 0, 0))

    def test_is_idempotent(self):
        seed()
        first = self.counts()
        seed()
        self.assertEqual(self.counts(), first)
        self.assertEqual(first[1:3], (12, 25))

    def test_every_status_present_and_one_overdue(self):
        seed()
        statuses = set(BookInstance.objects.values_list('status', flat=True))
        self.assertEqual(statuses, {'a', 'o', 'd', 'r'})
        self.assertTrue(BookInstance.objects.filter(due_back__lt=date.today()).exists())
        self.assertTrue(BookInstance.objects.filter(status='o', due_back__gt=date.today()).exists())

    def test_loans_have_borrowers(self):
        seed()
        self.assertFalse(BookInstance.objects.filter(status='o', borrower=None).exists())
        self.assertFalse(BookInstance.objects.exclude(status='o').exclude(borrower=None).exists())

    def test_permissions(self):
        seed()
        self.assertTrue(User.objects.get(username='librarian').has_perm('catalog.can_mark_returned'))
        self.assertFalse(User.objects.get(username='member').has_perm('catalog.can_mark_returned'))

    def test_rerun_keeps_changed_password_unless_reset(self):
        seed('--password', 'first-pass')
        member = User.objects.get(username='member')
        member.set_password('changed')
        member.save()
        seed('--password', 'other')
        self.assertTrue(User.objects.get(username='member').check_password('changed'))
        seed('--password', 'other', '--reset-passwords')
        self.assertTrue(User.objects.get(username='member').check_password('other'))
